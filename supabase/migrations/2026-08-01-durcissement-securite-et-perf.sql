-- ============================================================================
-- Durcissement sécurité + performances, suite à l'audit du 1er août 2026
-- ============================================================================
-- Ces changements ont d'abord été appliqués directement sur la base de
-- production. Ce fichier les enregistre pour que le dépôt redevienne la
-- référence : sans lui, reconstruire la base à partir de supabase/schema.sql
-- restaurerait silencieusement l'ancienne posture de sécurité (un seul admin
-- codé en dur, auth.users exposée, plafond d'envoi contournable) ET casserait
-- la vitrine, qui interroge désormais une vue absente du dépôt.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.
--
-- Ordre imposé : la table admins doit exister avant is_admin(), et is_admin()
-- avant les vues et politiques qui l'appellent.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Plusieurs administrateurs, au lieu d'un identifiant figé
-- ----------------------------------------------------------------------------
-- is_admin() comparait auth.uid() à un UUID écrit en dur. Un seul compte
-- pouvait donc administrer le site, et sa perte aurait été définitive : aucun
-- autre compte n'aurait pu se redonner les droits.
--
-- Aucune politique d'écriture n'est posée sur cette table : la liste ne se
-- modifie que par une migration, jamais depuis l'application. Accorder les
-- droits d'administration doit rester un geste délibéré et tracé.
create table if not exists public.admins (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  note       text,
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id)
);

alter table public.admins enable row level security;

drop policy if exists "Liste des admins visible par les admins" on public.admins;
create policy "Liste des admins visible par les admins" on public.admins
  for select using (is_admin());

revoke insert, update, delete, truncate on public.admins from anon, authenticated;

-- SECURITY DEFINER + search_path fixe : la fonction doit pouvoir lire
-- public.admins même quand l'appelant n'y a aucun droit direct, et ne doit pas
-- pouvoir être détournée par un schéma placé en tête de search_path.
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $function$
  select exists (
    select 1 from public.admins a where a.user_id = (select auth.uid())
  );
$function$;

-- Les deux comptes administrateurs au 1er août 2026. Les UUID viennent de
-- auth.users ; les emails ne sont ici qu'à titre de repère humain.
insert into public.admins (user_id, note) values
  ('514ff065-fa33-454b-9701-c9aec9053862', 'pab.business221@gmail.com — administrateur d''origine'),
  ('bff28930-e7ca-4883-a9b3-fe7a3ff1f3d9', 'papeabibouba@gmail.com — second administrateur, ajouté le 2026-08-01')
on conflict (user_id) do nothing;


-- ----------------------------------------------------------------------------
-- 2. collaborators_etat : ne plus exposer auth.users
-- ----------------------------------------------------------------------------
-- La vue joignait auth.users et n'était protégée que par sa propre clause
-- WHERE. Le filtre était correct, mais la sécurité reposait sur une convention
-- interne à la définition de la vue plutôt que sur le moteur : une
-- modification imprudente de ce WHERE aurait exposé la date de dernière
-- connexion de tous les collaborateurs, sans qu'aucune politique ne s'y
-- oppose. Signalé en ERREUR par l'analyseur Supabase.
--
-- Remplacé par un accès étroit : une seule colonne, une seule ligne,
-- autorisation vérifiée à l'intérieur de la fonction elle-même.
create or replace function public.dernier_login(cible uuid)
returns timestamptz
language sql
stable
security definer
set search_path = public
as $function$
  select u.last_sign_in_at
  from auth.users u
  where u.id = cible
    and (is_admin() or cible = (select auth.uid()));
$function$;

-- anon conserve le droit d'exécution : la fonction se protège déjà seule (elle
-- renvoie NULL si l'appelant n'est ni admin ni le collaborateur concerné). Le
-- lui retirer transformait un résultat vide en erreur explicite.
grant execute on function public.dernier_login(uuid) to anon, authenticated;

-- security_invoker : la vue ne touchant plus auth.users, elle peut appliquer
-- les droits et la RLS de l'appelant plutôt que ceux de son créateur.
create or replace view public.collaborators_etat
with (security_invoker = true) as
select
  c.user_id,
  c.display_name,
  c.contact_name,
  c.phone,
  c.email,
  c.zone,
  c.notes,
  c.verified_at,
  c.invited_at,
  c.created_at,
  public.dernier_login(c.user_id) as last_sign_in_at,
  public.dernier_login(c.user_id) is not null as compte_active
from public.collaborators c
where is_admin() or c.user_id = (select auth.uid());


-- ----------------------------------------------------------------------------
-- 3. Photo de couverture : une ligne par bien
-- ----------------------------------------------------------------------------
-- La vitrine chargeait TOUTES les photos de TOUS les biens au démarrage alors
-- que la liste n'affiche qu'une couverture par annonce. À 500 biens et 6
-- photos, c'est 3 000 lignes transférées pour 500 utilisées — sur la connexion
-- mobile sénégalaise, qui est la contrainte réelle du site.
--
-- ATTENTION : vitrine.html interroge cette vue. La supprimer casse la liste
-- des biens.
create or replace view public.public_property_cover_photos
with (security_invoker = true) as
select distinct on (property_id)
  id, property_id, storage_path, "position", is_cover
from public.public_property_photos
order by property_id, is_cover desc, "position" asc, id asc;

grant select on public.public_property_cover_photos to anon, authenticated;


-- ----------------------------------------------------------------------------
-- 4. Plafond d'envoi : retirer l'en-tête fourni par le client
-- ----------------------------------------------------------------------------
-- L'empreinte se repliait sur x-forwarded-for, que le client fournit
-- lui-même : faire varier cet en-tête suffisait à repartir de zéro à chaque
-- envoi, et donc à noyer les cinq formulaires publics.
create or replace function public.enforce_submission_rate_limit()
returns trigger
language plpgsql
security definer
set search_path = public, extensions
as $function$
declare
  entetes json;
  ip text;
  empreinte text;
  par_appareil int;
  au_total int;
  plafond_appareil int;
  plafond_global int := 200;
begin
  if coalesce(auth.role(), '') <> 'anon' then
    return new;
  end if;

  plafond_appareil := case tg_table_name
    when 'alert_subscriptions' then 3
    else 5
  end;

  entetes := nullif(current_setting('request.headers', true), '')::json;
  -- cf-connecting-ip et sb-forwarded-for sont posés par l'infrastructure et
  -- restent fiables. À défaut, on regroupe tout sous une empreinte commune
  -- plutôt que d'offrir un contournement gratuit.
  ip := coalesce(entetes ->> 'cf-connecting-ip',
                 entetes ->> 'sb-forwarded-for',
                 'inconnu');
  empreinte := encode(extensions.digest(ip || '::pab-immo-v1', 'sha256'), 'hex');

  select count(*) into par_appareil
    from public.submission_log
   where bucket = tg_table_name
     and client_hash = empreinte
     and created_at > now() - interval '1 hour';

  if par_appareil >= plafond_appareil then
    raise exception 'Vous avez déjà envoyé plusieurs demandes récemment. Merci de patienter une heure, ou de nous joindre directement par WhatsApp.'
      using errcode = 'check_violation';
  end if;

  select count(*) into au_total
    from public.submission_log
   where bucket = tg_table_name
     and created_at > now() - interval '1 hour';

  if au_total >= plafond_global then
    raise exception 'Le formulaire est momentanément indisponible. Merci de nous joindre par WhatsApp au +221 77 849 41 11.'
      using errcode = 'check_violation';
  end if;

  insert into public.submission_log (bucket, client_hash)
       values (tg_table_name, empreinte);

  delete from public.submission_log where created_at < now() - interval '2 hours';

  return new;
end;
$function$;


-- ----------------------------------------------------------------------------
-- 5. Point de contrôle pour la surveillance externe
-- ----------------------------------------------------------------------------
-- Interrogé toutes les 6 h par .github/workflows/surveiller-notifications.yml.
-- Ne renvoie que des compteurs agrégés et un message technique — jamais un
-- nom, un email ou le contenu d'un message — afin de pouvoir être appelé sans
-- session admin, avec la clé publique déjà présente dans le code du site.
--
-- Détecte aussi le cas que le bandeau interne de l'admin ne couvre pas : des
-- demandes reçues mais aucun email parti, c'est-à-dire une panne totale et
-- silencieuse de la chaîne de notification.
create or replace function public.sante_notifications()
returns table(
  ok boolean,
  echecs_7j bigint,
  envois_7j bigint,
  dernier_envoi_reussi timestamptz,
  dernier_echec timestamptz,
  demandes_recues_7j bigint,
  message text
)
language sql
stable
security definer
set search_path = public
as $function$
  with sante as (
    select * from public.notification_health
  ),
  demandes as (
    select
      (select count(*) from public.contact_messages where created_at > now() - interval '7 days')
    + (select count(*) from public.appointments where created_at > now() - interval '7 days')
      as demandes_recues_7j
  )
  select
    case
      when sante.echecs_7j > 0 then false
      when demandes.demandes_recues_7j > 0 and sante.envois_7j = 0 then false
      else true
    end as ok,
    sante.echecs_7j,
    sante.envois_7j,
    sante.dernier_envoi_reussi,
    sante.dernier_echec,
    demandes.demandes_recues_7j,
    case
      when sante.echecs_7j > 0 then
        sante.echecs_7j || ' échec(s) d''envoi sur 7 jours. Dernier détail : ' || coalesce(sante.dernier_message, '—')
      when demandes.demandes_recues_7j > 0 and sante.envois_7j = 0 then
        demandes.demandes_recues_7j || ' demande(s) reçue(s) en 7 jours mais aucun email envoyé : la chaîne de notification semble arrêtée.'
      else 'OK'
    end as message
  from sante, demandes;
$function$;

grant execute on function public.sante_notifications() to anon, authenticated;


-- ----------------------------------------------------------------------------
-- 6. search_path fixe sur les fonctions qui en manquaient
-- ----------------------------------------------------------------------------
-- Sans search_path figé, une fonction peut être détournée par un schéma placé
-- en tête de recherche. Sans effet tant que personne ne peut créer de schéma,
-- mais c'est une protection gratuite.
alter function public.contact_key(text)                set search_path = public;
alter function public.set_updated_at()                 set search_path = public;
alter function public.review_horodater_moderation()    set search_path = public;
alter function public.bloquer_ecriture_referentiel()   set search_path = public;
alter function public.candidature_horodater_examen()   set search_path = public;
alter function public.leads_horodater_cloture()        set search_path = public;


-- ----------------------------------------------------------------------------
-- 7. Fonctions internes non appelables directement par l'API
-- ----------------------------------------------------------------------------
-- Ces fonctions ne servent que de déclencheurs : rien ne justifie qu'elles
-- soient exposées en RPC. stats_prospects() fait exception et garde le droit
-- pour « authenticated » — le panneau Prospects l'appelle avec la session de
-- l'admin, et il n'existe pas de rôle Postgres « admin » distinct (le contrôle
-- se fait à l'intérieur, via is_admin()).
revoke execute on function public.enforce_agency_verification_rights() from anon, authenticated;
revoke execute on function public.enforce_sponsoring_rights()          from anon, authenticated;
revoke execute on function public.enforce_submission_rate_limit()      from anon, authenticated;
revoke execute on function public.enforce_verification_rights()        from anon, authenticated;
revoke execute on function public.log_property_activity()              from anon, authenticated;
revoke execute on function public.log_status_change()                  from anon, authenticated;
revoke execute on function public.notify_alert_matches()               from anon, authenticated;
revoke execute on function public.notify_lead_webhook()                from anon, authenticated;
revoke execute on function public.rattacher_lead()                     from anon, authenticated;
revoke execute on function public.stamp_site_setting()                 from anon, authenticated;
revoke execute on function public.stats_prospects()                    from anon, authenticated;
grant  execute on function public.stats_prospects()                    to   authenticated;


-- ----------------------------------------------------------------------------
-- 8. Index sur les clés étrangères non couvertes
-- ----------------------------------------------------------------------------
-- Sans effet à 24 biens, indispensable à quelques milliers : une clé étrangère
-- sans index force un parcours complet de la table à chaque jointure et à
-- chaque suppression en cascade.
create index if not exists idx_appointments_property_id            on public.appointments(property_id);
create index if not exists idx_collaborator_requests_reviewed_by   on public.collaborator_requests(reviewed_by);
create index if not exists idx_collaborators_invited_by            on public.collaborators(invited_by);
create index if not exists idx_collaborators_verified_by           on public.collaborators(verified_by);
create index if not exists idx_contact_messages_property_id        on public.contact_messages(property_id);
create index if not exists idx_leads_property_id                   on public.leads(property_id);
create index if not exists idx_properties_sponsored_by             on public.properties(sponsored_by);
create index if not exists idx_properties_verified_by              on public.properties(verified_by);
create index if not exists idx_property_status_history_property_id on public.property_status_history(property_id);
create index if not exists idx_reviews_reviewed_by                 on public.reviews(reviewed_by);
create index if not exists idx_site_settings_updated_by            on public.site_settings(updated_by);


-- ----------------------------------------------------------------------------
-- 9. Politiques RLS : auth.uid() évalué une fois, pas par ligne
-- ----------------------------------------------------------------------------
-- Écrit « auth.uid() », l'appel est refait pour CHAQUE ligne examinée. Entouré
-- de « (select …) », PostgreSQL le calcule une seule fois par requête. Le
-- résultat est identique ; seul le coût change, et il devient sensible dès que
-- les tables grossissent.
alter policy "Acces biens : proprietaire ou admin" on public.properties
  using ((owner_id = (select auth.uid())) or is_admin())
  with check ((owner_id = (select auth.uid())) or is_admin());

alter policy "Acces photos : proprietaire ou admin" on public.property_photos
  using (is_admin() or exists (select 1 from public.properties p where p.id = property_photos.property_id and p.owner_id = (select auth.uid())))
  with check (is_admin() or exists (select 1 from public.properties p where p.id = property_photos.property_id and p.owner_id = (select auth.uid())));

alter policy "Acces historique : proprietaire ou admin" on public.property_status_history
  using (is_admin() or exists (select 1 from public.properties p where p.id = property_status_history.property_id and p.owner_id = (select auth.uid())));

alter policy "Messages visibles par le proprietaire du bien" on public.contact_messages
  using (exists (select 1 from public.properties p where p.id = contact_messages.property_id and p.owner_id = (select auth.uid())));

alter policy "RDV visibles par le proprietaire du bien" on public.appointments
  using (exists (select 1 from public.properties p where p.id = appointments.property_id and p.owner_id = (select auth.uid())));

alter policy "Consultations visibles par proprietaire ou admin" on public.property_views
  using (is_admin() or exists (select 1 from public.properties p where p.id = property_views.property_id and p.owner_id = (select auth.uid())));

alter policy "Favoris visibles par proprietaire ou admin" on public.favorite_events
  using (is_admin() or exists (select 1 from public.properties p where p.id = favorite_events.property_id and p.owner_id = (select auth.uid())));

alter policy "Prospects visibles par le proprietaire du bien" on public.leads
  using (exists (select 1 from public.properties p where p.id = leads.property_id and p.owner_id = (select auth.uid())));

alter policy "Un collaborateur lit sa propre fiche" on public.collaborators
  using (user_id = (select auth.uid()));
