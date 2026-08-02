-- ============================================================================
-- Statut foncier des biens (Titre foncier / Bail / Délibération)
-- ============================================================================
-- Au Sénégal, le statut juridique d'un terrain est la première question que
-- se pose un acheteur sérieux — avant le prix, avant la superficie — et la
-- première source de litige. Cette information n'existait auparavant que
-- noyée dans le texte libre de la description : ni filtrable, ni affichable
-- en évidence, ni vérifiable.
--
-- Par défaut à 'Non renseigné' : les biens déjà en base ne doivent pas se
-- retrouver avec une affirmation juridique qui n'a jamais été vérifiée.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.
-- ============================================================================

do $$ begin
  create type statut_foncier_type as enum ('Titre foncier', 'Bail', 'Délibération', 'Non renseigné');
exception when duplicate_object then null;
end $$;

alter table public.properties
  add column if not exists statut_foncier statut_foncier_type not null default 'Non renseigné';

-- CREATE OR REPLACE VIEW n'accepte que des colonnes ajoutées EN FIN de liste :
-- l'insérer au milieu ferait croire à Postgres qu'on renomme une colonne
-- existante (rencontré en le testant : « cannot change name of view column
-- "verified_at" to "statut_foncier" »). La position dans le SELECT n'a aucune
-- importance pour le code JS, qui lit les colonnes par nom.
create or replace view public.public_properties as
select id,
    ref,
    type,
    operation,
    status,
    commune,
    region,
    quartier,
    departement,
    lat,
    lng,
    surface,
    price,
    description,
    chambres,
    salons,
    salles_bain,
    cuisine,
    equipements,
    verified_at,
    availability_checked_at,
    (exists (select 1 from collaborators c where c.user_id = p.owner_id and c.verified_at is not null)) as agence_verifiee,
    created_at,
    sponsored_until is not null and sponsored_until > now() as sponsorisee,
    statut_foncier
from public.properties p
where is_published = true and (status = any (array['Disponible'::property_status, 'Réservé'::property_status])) and archived_at is null;
