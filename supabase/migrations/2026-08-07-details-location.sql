-- ============================================================================
-- Champs manquants pour une décision de location sans appel préalable
-- ============================================================================
-- Pour un studio ou un appartement à louer, « meublé » et « caution » sont
-- des critères de décision de premier rang. Leur absence du modèle forçait
-- un appel juste pour les connaître — un appel qui n'aurait souvent servi
-- qu'à ça. Cette migration ajoute :
--   meuble               — meublé / non meublé (NULL = non renseigné)
--   charges               — charges mensuelles en FCFA, en plus du loyer
--   caution               — dépôt de garantie en FCFA
--   etage                 — texte libre ("RDC", "3e étage sur 5"…) : les
--                           façons de désigner un étage varient trop pour un
--                           entier propre
--   annee_construction    — année de construction
--   date_disponibilite    — date de disponibilité pour emménagement, distincte
--                           d'availability_checked_at (qui ne dit que la
--                           fraîcheur de la dernière vérification, pas la date
--                           d'entrée possible)
--
-- Tous nullables : un bien déjà en base ne doit pas se retrouver avec une
-- valeur inventée pour un champ jamais renseigné.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.
-- ============================================================================

alter table public.properties
  add column if not exists meuble boolean,
  add column if not exists charges numeric,
  add column if not exists caution numeric,
  add column if not exists etage text,
  add column if not exists annee_construction smallint,
  add column if not exists date_disponibilite date;

-- CREATE OR REPLACE VIEW n'accepte que des colonnes ajoutées EN FIN de liste
-- (déjà rencontré avec statut_foncier). La position dans le SELECT n'a aucune
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
    statut_foncier,
    meuble,
    charges,
    caution,
    etage,
    annee_construction,
    date_disponibilite
from public.properties p
where is_published = true and (status = any (array['Disponible'::property_status, 'Réservé'::property_status])) and archived_at is null;
