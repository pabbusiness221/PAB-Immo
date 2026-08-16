-- Plafonner les écritures anonymes sur les trois tables de mesure d'audience.
--
-- POURQUOI
-- --------
-- Le déclencheur enforce_submission_rate_limit protège les cinq formulaires
-- (messages, rendez-vous, alertes, candidatures, avis) mais pas property_views,
-- site_visits ni favorite_events. Ces trois tables acceptent l'insertion
-- anonyme — c'est nécessaire, un visiteur n'a pas de compte — et rien ne
-- limitait le nombre d'insertions. Un script répétant l'appel autorisé pouvait
-- donc fabriquer « 3 000 biens consultés » sans rien contourner.
--
-- L'enjeu n'est pas une fuite : ces tables ne contiennent aucune donnée
-- personnelle. C'est l'intégrité de la seule mesure d'audience dont dispose
-- l'agence, et qui sert à décider quels biens mettre en avant. S'y ajoutait une
-- croissance de lignes sans borne.
--
-- POURQUOI UN DÉCLENCHEUR SÉPARÉ ET PAS LE MÊME
-- Trois différences de nature avec un formulaire :
--
--  1. Le volume légitime est mille fois supérieur. Le plafond global de 200 par
--     heure du limiteur de formulaires deviendrait un plafond sur le trafic
--     réel : passé 200 consultations dans l'heure, on jetterait de vraies
--     données. C'est le mal qu'on veut éviter, en sens inverse.
--
--  2. On n'a rien à dire au visiteur. Un formulaire refusé doit expliquer
--     pourquoi et proposer WhatsApp. Ici le visiteur n'a rien demandé : la
--     mesure est invisible pour lui. Le déclencheur renvoie donc NULL — la
--     ligne est abandonnée sans erreur, sans message, sans trace côté client.
--     L'auteur d'un script n'apprend pas non plus qu'il a été plafonné.
--
--  3. Ces tables portent déjà session_id, ce que n'ont pas les formulaires.
--     Cela permet un premier palier par navigateur, plus fin qu'un palier par
--     adresse IP.
--
-- POURQUOI DEUX PALIERS
-- Un plafond par IP seul ne convient pas ici : au Sénégal les opérateurs
-- mobiles partagent une même adresse publique entre un très grand nombre
-- d'abonnés (CGNAT). Un seuil serré sur l'IP écarterait des visiteurs réels.
-- D'où :
--   palier 1, par navigateur (session_id) : seuil serré, il vise la boucle ;
--   palier 2, par IP : seuil large, il vise la boucle qui fait tourner les
--                      session_id, sans pénaliser des voisins de NAT ;
--   palier 3, global   : coupe-circuit contre un afflux distribué, réglé assez
--                        haut pour n'agir qu'en cas d'attaque franche.
--
-- Un session_id absent (property_views l'autorise) n'ouvre pas de brèche :
-- « is not distinct from » regroupe toutes les lignes sans identifiant dans un
-- seul seau, qui reçoit le seuil serré.
--
-- D'OÙ VIENNENT LES SEUILS
-- Mesuré sur les données existantes, pic observé par navigateur et par heure :
--   property_views  14   site_visits  5   favorite_events  10
-- Les seuils du palier 1 valent 5 à 6 fois ce pic. Le trafic actuel est donc
-- très loin de les atteindre, et ils resteront valables si l'audience grandit
-- d'un ordre de grandeur.

-- Le palier 1 compte sur la table elle-même : sans index, chaque insertion
-- devient un parcours complet. Le volume est faible aujourd'hui, il ne le
-- restera pas.
create index if not exists property_views_session_heure_idx
  on public.property_views (session_id, created_at desc);
create index if not exists site_visits_session_heure_idx
  on public.site_visits (session_id, created_at desc);
create index if not exists favorite_events_session_heure_idx
  on public.favorite_events (session_id, created_at desc);

create or replace function public.limiter_mesures_audience()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  entetes json;
  ip text;
  empreinte text;
  par_navigateur int;
  par_ip int;
  au_total int;
  plafond_navigateur int;
  plafond_ip int;
  plafond_global int := 5000;
begin
  -- Seul le public anonyme est concerné. L'administration ne fait que lire ces
  -- tables ; si un jour elle y écrit, ce ne sera pas pour en fausser le compte.
  if coalesce(auth.role(), '') <> 'anon' then
    return new;
  end if;

  plafond_navigateur := case tg_table_name
    when 'site_visits'     then 30
    when 'favorite_events' then 60
    else 80   -- property_views
  end;

  -- Large, parce qu'un même opérateur mobile présente des milliers d'abonnés
  -- sous une seule adresse.
  plafond_ip := case tg_table_name
    when 'site_visits'     then 250
    when 'favorite_events' then 400
    else 600  -- property_views
  end;

  -- Palier 1 — par navigateur. Le compte se lit sur la table visée, qui porte
  -- déjà session_id et created_at : aucune écriture de journal à ce palier.
  execute format(
    'select count(*) from public.%I
      where session_id is not distinct from $1
        and created_at > now() - interval ''1 hour''',
    tg_table_name)
    into par_navigateur
    using new.session_id;

  if par_navigateur >= plafond_navigateur then
    return null;
  end if;

  entetes := nullif(current_setting('request.headers', true), '')::json;
  -- x-forwarded-for est écarté volontairement : le client le pose lui-même, et
  -- le faire varier suffirait à remettre le palier 2 à zéro. cf-connecting-ip
  -- et sb-forwarded-for viennent de l'infrastructure. Même raisonnement que
  -- dans enforce_submission_rate_limit.
  ip := coalesce(entetes ->> 'cf-connecting-ip',
                 entetes ->> 'sb-forwarded-for',
                 'inconnu');
  empreinte := encode(extensions.digest(ip || '::pab-immo-v1', 'sha256'), 'hex');

  -- Palier 2 — par adresse, via le journal partagé avec les formulaires. Les
  -- noms de seau ne peuvent pas se télescoper : ce sont des noms de tables.
  select count(*) into par_ip
    from public.submission_log
   where bucket = tg_table_name
     and client_hash = empreinte
     and created_at > now() - interval '1 hour';

  if par_ip >= plafond_ip then
    return null;
  end if;

  -- Palier 3 — coupe-circuit global.
  select count(*) into au_total
    from public.submission_log
   where bucket = tg_table_name
     and created_at > now() - interval '1 hour';

  if au_total >= plafond_global then
    return null;
  end if;

  insert into public.submission_log (bucket, client_hash)
       values (tg_table_name, empreinte);

  -- Le limiteur de formulaires purge à chaque envoi, ce qui est tenable pour
  -- quelques soumissions par jour. Ici l'insertion est mille fois plus
  -- fréquente : on ne purge qu'une fois sur cent, ce qui suffit à borner la
  -- table sans imposer un parcours à chaque consultation.
  if random() < 0.01 then
    delete from public.submission_log where created_at < now() - interval '2 hours';
  end if;

  return new;
end;
$$;

comment on function public.limiter_mesures_audience() is
  'Plafonne les insertions anonymes de mesure d''audience (navigateur, IP, global). Abandonne la ligne sans erreur au-delà du seuil.';

drop trigger if exists limiter_property_views on public.property_views;
create trigger limiter_property_views
  before insert on public.property_views
  for each row execute function public.limiter_mesures_audience();

drop trigger if exists limiter_site_visits on public.site_visits;
create trigger limiter_site_visits
  before insert on public.site_visits
  for each row execute function public.limiter_mesures_audience();

drop trigger if exists limiter_favorite_events on public.favorite_events;
create trigger limiter_favorite_events
  before insert on public.favorite_events
  for each row execute function public.limiter_mesures_audience();
