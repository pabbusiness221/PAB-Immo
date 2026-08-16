-- La mise en ligne sur la vitrine devient un acte réservé à l'administrateur.
--
-- POURQUOI
-- --------
-- « Publier sur la vitrine client » était une simple case à cocher dans le
-- formulaire du portefeuille, sans garde-fou : ni dans la page, ni dans la base.
-- Un collaborateur pouvait donc mettre en ligne ce qu'il voulait, à la seconde,
-- sans que personne ne le voie passer. Les deux autres marques publiques —
-- « certifiée » et la mise en avant — étaient déjà protégées côté base par
-- enforce_verification_rights() et enforce_sponsoring_rights() ; la publication
-- était la seule à ne pas l'être.
--
-- Désormais : le collaborateur *demande* la publication, l'administrateur
-- l'autorise. La demande est enregistrée, la mise en ligne non.
--
-- POURQUOI is_published RESTE LA SEULE VÉRITÉ
-- On n'ajoute pas de drapeau parallèle. is_published continue de commander à lui
-- seul ce que voit le public, ce qui a trois conséquences heureuses :
--   · la vue public_properties n'est pas touchée ;
--   · notify_alert_matches(), qui n'envoie les alertes que sur is_published =
--     true, se met à prévenir les abonnés au moment de la validation et non de
--     la demande — sans une ligne de changement ;
--   · rien de ce qui existe ne peut publier par mégarde : le seul chemin vers
--     is_published = true passe par is_admin().
--
-- POURQUOI L'ÉTAT SE DÉDUIT DE DATES ET NON D'UN ENUM
-- Premier réflexe : effacer valide_le à chaque retour en validation. Mauvaise
-- idée — le déclencheur se serait heurté à son propre garde-fou, qui interdit
-- justement d'écrire les colonnes de décision hors administration, et l'on
-- perdait l'historique. On compare donc les dates : soumis_le postérieur à
-- valide_le veut dire « resoumis depuis la dernière validation ». Rien n'est
-- effacé, la règle tient en quatre lignes, et etat_publication l'exprime une
-- seule fois pour toute l'application.
--
-- CE QUI RENVOIE UNE ANNONCE EN VALIDATION
-- Le principe posé est que la publication effective est toujours l'acte de
-- l'administrateur. Il serait donc vain de valider une annonce propre si son
-- auteur peut ensuite en changer le prix. Un non-administrateur qui modifie ce
-- qu'un visiteur voit — prix, description, photos, surface, pièces,
-- localisation — retire l'annonce de la vitrine et la remet en attente. Ce qui
-- ne change rien pour le visiteur passe directement : notes internes, date
-- d'acquisition. Et le passage en « Loué » ou « Vendu » passe aussi, puisqu'il
-- ne fait que réduire l'exposition, jamais l'étendre.
--
-- ANTÉRIORITÉ
-- Les biens déjà en ligne le restent : aucun ne disparaît de la vitrine du fait
-- de cette migration. On leur pose une date de validation rétrospective, celle
-- de leur certification quand elle existe, leur création sinon.

alter table public.properties
  add column if not exists soumis_le   timestamptz,
  add column if not exists valide_le   timestamptz,
  add column if not exists valide_par  uuid,
  add column if not exists refuse_le   timestamptz,
  add column if not exists refuse_par  uuid,
  add column if not exists motif_refus text;

comment on column public.properties.soumis_le is
  'Date de la dernière demande de publication par le propriétaire du bien.';
comment on column public.properties.valide_le is
  'Date de la dernière autorisation de mise en ligne par un administrateur. Jamais effacée : sert d''historique et de repère face à soumis_le.';
comment on column public.properties.motif_refus is
  'Raison communiquée au collaborateur en cas de refus. Visible par lui.';

-- L'état lisible, défini une seule fois. Immuable au sens de PostgreSQL : elle
-- ne compare que ses propres arguments, sans jamais lire l'heure courante — ce
-- qui permet de l'exposer en colonne générée, donc de la faire suivre
-- automatiquement dans tous les select du portefeuille.
create or replace function public.etat_publication(
  is_published boolean,
  soumis_le    timestamptz,
  valide_le    timestamptz,
  refuse_le    timestamptz
) returns text
language sql
immutable
as $$
  select case
    when is_published then 'En ligne'
    when refuse_le is not null
         and (soumis_le is null or refuse_le >= soumis_le) then 'Refusé'
    when soumis_le is not null
         and (valide_le is null or soumis_le > valide_le) then 'En attente'
    else 'Brouillon'
  end;
$$;

comment on function public.etat_publication(boolean, timestamptz, timestamptz, timestamptz) is
  'État de publication d''un bien, déduit des dates. Source unique : exposée en colonne générée properties.etat_publication.';

alter table public.properties
  drop column if exists etat_publication;
alter table public.properties
  add column etat_publication text
  generated always as (
    public.etat_publication(is_published, soumis_le, valide_le, refuse_le)
  ) stored;

create index if not exists properties_a_valider_idx
  on public.properties (soumis_le desc)
  where is_published = false;

-- ------------------------------------------------------------------
-- Le garde-fou. Calqué sur enforce_verification_rights(), qui protège
-- déjà la certification de la même façon.
-- ------------------------------------------------------------------
create or replace function public.enforce_publication_rights()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  -- Une opération serveur — migration, service_role, tâche planifiée — n'a pas
  -- de JWT client et n'est donc pas soumise à ce contrôle, qui vise les deux
  -- rôles joignables depuis le navigateur. Le test porte sur le rôle et non sur
  -- l'absence d'identité : l'anonyme aussi a une identité nulle, et le
  -- confondre avec le serveur lui ouvrirait la publication.
  cote_serveur boolean := coalesce(auth.role(), '') not in ('anon', 'authenticated');
  administrateur boolean;
  vitrine_modifiee boolean := false;
  deja_en_attente boolean := false;
begin
  administrateur := cote_serveur or is_admin();
  -- Les colonnes de décision ne viennent jamais du client. Ce contrôle passe en
  -- premier, sur les valeurs telles que fournies : ce que la fonction pose
  -- elle-même plus bas n'est donc pas concerné.
  if not administrateur then
    if tg_op = 'INSERT' then
      if new.valide_le is not null or new.valide_par is not null
         or new.refuse_le is not null or new.refuse_par is not null
         or new.motif_refus is not null then
        raise exception 'Seul l''administrateur peut autoriser ou refuser une publication.';
      end if;
    elsif new.valide_le  is distinct from old.valide_le
       or new.valide_par is distinct from old.valide_par
       or new.refuse_le  is distinct from old.refuse_le
       or new.refuse_par is distinct from old.refuse_par
       or new.motif_refus is distinct from old.motif_refus then
      raise exception 'Seul l''administrateur peut autoriser ou refuser une publication.';
    end if;
  end if;

  if tg_op = 'INSERT' then
    if administrateur then
      if new.is_published then
        new.valide_le  := now();
        new.valide_par := auth.uid();
      end if;
    elsif new.is_published then
      -- La demande est retenue, la mise en ligne refusée en silence : le
      -- collaborateur a coché « demander la publication », il n'a rien fait de
      -- fautif, et la page lui affiche « En attente ».
      new.is_published := false;
      new.soumis_le    := now();
    end if;
    return new;
  end if;

  if administrateur then
    if new.is_published and not old.is_published then
      new.valide_le  := now();
      new.valide_par := auth.uid();
      -- Une autorisation efface un refus antérieur.
      new.refuse_le   := null;
      new.refuse_par  := null;
      new.motif_refus := null;
    elsif new.motif_refus is distinct from old.motif_refus
          and new.motif_refus is not null then
      -- Refus motivé : la date et l'auteur sont déduits, jamais fournis.
      new.is_published := false;
      new.refuse_le    := now();
      new.refuse_par   := auth.uid();
    elsif new.motif_refus is null and old.motif_refus is not null then
      -- Refus retiré sans publier pour autant : sans cela l'annonce resterait
      -- « Refusé » indéfiniment, puisque l'état se lit sur refuse_le.
      new.refuse_le  := null;
      new.refuse_par := null;
    end if;
    return new;
  end if;

  -- À partir d'ici : propriétaire non administrateur.

  -- Déjà en attente ? Alors ne pas retoucher soumis_le : chaque enregistrement
  -- du formulaire repasse par ici, et rafraîchir la date enverrait un email de
  -- plus à chaque sauvegarde pour une annonce que l'administrateur n'a pas
  -- encore regardée.
  deja_en_attente := public.etat_publication(
    old.is_published, old.soumis_le, old.valide_le, old.refuse_le) = 'En attente';

  -- Une tentative de mise en ligne devient une demande.
  if new.is_published and not old.is_published then
    new.is_published := false;
    if not deja_en_attente then
      new.soumis_le := now();
    end if;
  end if;

  -- Modifier ce que voit un visiteur sur une annonce en ligne la retire de la
  -- vitrine et la remet en attente.
  vitrine_modifiee := (
       new.type               is distinct from old.type
    or new.operation          is distinct from old.operation
    or new.price              is distinct from old.price
    or new.surface            is distinct from old.surface
    or new.description        is distinct from old.description
    or new.description_en     is distinct from old.description_en
    or new.commune            is distinct from old.commune
    or new.region             is distinct from old.region
    or new.quartier           is distinct from old.quartier
    or new.departement        is distinct from old.departement
    or new.lat                is distinct from old.lat
    or new.lng                is distinct from old.lng
    or new.chambres           is distinct from old.chambres
    or new.salons             is distinct from old.salons
    or new.salles_bain        is distinct from old.salles_bain
    or new.cuisine            is distinct from old.cuisine
    or new.equipements        is distinct from old.equipements
    or new.statut_foncier     is distinct from old.statut_foncier
    or new.meuble             is distinct from old.meuble
    or new.charges            is distinct from old.charges
    or new.caution            is distinct from old.caution
    or new.etage              is distinct from old.etage
    or new.annee_construction is distinct from old.annee_construction
    or new.date_disponibilite is distinct from old.date_disponibilite
  );

  -- Pas de garde deja_en_attente ici : une annonce en ligne n'est jamais en
  -- attente, la condition serait morte.
  if old.is_published and vitrine_modifiee then
    new.is_published := false;
    new.soumis_le    := now();
  end if;

  return new;
end;
$$;

drop trigger if exists trg_properties_publication on public.properties;
create trigger trg_properties_publication
  before insert or update on public.properties
  for each row execute function public.enforce_publication_rights();

-- ------------------------------------------------------------------
-- Les photos vivent dans une autre table : sans ce déclencheur, changer
-- l'image d'une annonce validée échapperait entièrement au contrôle,
-- alors que c'est le contenu le plus visible de la vitrine.
-- ------------------------------------------------------------------
create or replace function public.photos_renvoyer_en_validation()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  bien uuid;
begin
  if coalesce(auth.role(), '') not in ('anon', 'authenticated') or is_admin() then
    return coalesce(new, old);
  end if;

  bien := coalesce(new.property_id, old.property_id);

  -- On ne touche volontairement ni valide_le ni refuse_le : les écrire ici
  -- ferait lever le garde-fou de enforce_publication_rights(), qui interdit au
  -- non-administrateur de modifier les colonnes de décision. soumis_le suffit,
  -- puisque l'état se déduit de la comparaison des dates.
  update public.properties
     set is_published = false,
         soumis_le    = now()
   where id = bien
     and is_published = true;

  return coalesce(new, old);
end;
$$;

drop trigger if exists trg_photos_publication on public.property_photos;
create trigger trg_photos_publication
  after insert or update or delete on public.property_photos
  for each row execute function public.photos_renvoyer_en_validation();

-- ------------------------------------------------------------------
-- Prévenir l'administrateur qu'un bien attend son autorisation.
-- ------------------------------------------------------------------
create or replace function public.notifier_bien_a_valider()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  nouvelle_demande boolean;
begin
  nouvelle_demande := (
    new.is_published = false
    and new.soumis_le is not null
    and (tg_op = 'INSERT' or new.soumis_le is distinct from old.soumis_le)
  );

  if not nouvelle_demande then
    return new;
  end if;

  -- Un administrateur qui travaille sur son propre bien n'a pas à s'écrire, et
  -- une migration n'a pas à envoyer d'email.
  if coalesce(auth.role(), '') not in ('anon', 'authenticated') or is_admin() then
    return new;
  end if;

  -- Charge utile construite champ par champ, et non par row_to_json : la ligne
  -- complète embarquerait les notes internes et la géométrie location, dont
  -- l'email n'a que faire.
  perform net.http_post(
    url := 'https://avanktgaxepzpqmsiauz.supabase.co/functions/v1/notify-lead',
    body := jsonb_build_object(
      'type', 'A_VALIDER',
      'table', 'properties',
      'record', jsonb_build_object(
        'id', new.id,
        'ref', new.ref,
        'type', new.type,
        'operation', new.operation,
        'commune', new.commune,
        'region', new.region,
        'price', new.price,
        'surface', new.surface,
        'owner_id', new.owner_id,
        'soumis_le', new.soumis_le,
        'motif_refus_precedent', new.motif_refus
      )
    ),
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer sb_publishable_nAQnS82ru9h-beIDPKMqPA_JO_aSYc-'
    ),
    timeout_milliseconds := 5000
  );

  return new;
end;
$$;

drop trigger if exists trg_properties_a_valider on public.properties;
create trigger trg_properties_a_valider
  after insert or update on public.properties
  for each row execute function public.notifier_bien_a_valider();

-- ------------------------------------------------------------------
-- Antériorité : rien ne disparaît de la vitrine.
-- ------------------------------------------------------------------
update public.properties
   set valide_le  = coalesce(verified_at, created_at),
       valide_par = verified_by
 where is_published = true
   and valide_le is null;
