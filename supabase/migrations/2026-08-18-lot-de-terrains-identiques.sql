-- Un bien peut représenter plusieurs terrains identiques mis en vente ensemble.
--
-- POURQUOI
-- --------
-- Un lotisseur qui vend douze parcelles de 300 m² au même prix devait jusqu'ici
-- créer douze annonces identiques, ou une seule qui mentait sur la disponibilité.
-- Les deux sont mauvais : la première noie le catalogue sous des doublons que le
-- visiteur prend pour de la négligence, la seconde laisse croire qu'il ne reste
-- qu'un terrain.
--
-- CE QUE LA COLONNE VEUT DIRE
-- lot_nombre = nombre de terrains identiques encore disponibles dans ce lot.
--   NULL  → bien unique, cas de loin le plus courant, et valeur par défaut
--   >= 2  → lot de N terrains identiques
--
-- La valeur 1 est refusée : un lot d'un seul terrain est un terrain unique, et
-- accepter les deux écritures pour la même réalité garantit qu'un jour les
-- filtres compteront mal.
--
-- POURQUOI LE PRIX ET LA SUPERFICIE RESTENT CEUX D'UN SEUL TERRAIN
-- C'est la seule lecture qui reste juste quand il n'en reste qu'un. Si price
-- valait pour l'ensemble, il faudrait le corriger à chaque vente ; en le gardant
-- unitaire, vendre un terrain revient à décrémenter lot_nombre, et le passage de
-- 2 à NULL se fait sans retoucher au montant. L'affichage annonce donc « à partir
-- de X FCFA l'unité », jamais un total.
--
-- POURQUOI AUCUNE CONTRAINTE SUR LE TYPE
-- Le formulaire ne propose l'option que pour les terrains, ce qui répond au besoin
-- exprimé. La base ne l'impose pas : un lot d'appartements identiques dans un même
-- immeuble est une réalité du marché, et rien ici n'aurait à changer le jour où on
-- voudra l'ouvrir. Une contrainte de type se retire mal une fois des données en
-- place ; une règle de formulaire se modifie en une ligne.

alter table public.properties
  add column if not exists lot_nombre smallint;

alter table public.properties
  drop constraint if exists properties_lot_nombre_coherent;
alter table public.properties
  add constraint properties_lot_nombre_coherent
  check (lot_nombre is null or (lot_nombre >= 2 and lot_nombre <= 500));

comment on column public.properties.lot_nombre is
  'Nombre de terrains identiques disponibles dans ce lot. NULL = bien unique. Le prix et la superficie restent ceux d''UN terrain.';

-- La vitrine doit pouvoir l'afficher : sans cette colonne dans la vue, le
-- visiteur ne verrait aucune différence entre un terrain seul et un lot de douze.
create or replace view public.public_properties as
SELECT id, ref, type, operation, status, commune, region, quartier, departement,
       lat, lng, surface, price, description, chambres, salons, salles_bain,
       cuisine, equipements, verified_at, availability_checked_at,
       (EXISTS ( SELECT 1
                 FROM collaborators c
                WHERE c.user_id = p.owner_id AND c.verified_at IS NOT NULL)) AS agence_verifiee,
       created_at,
       sponsored_until IS NOT NULL AND sponsored_until > now() AS sponsorisee,
       statut_foncier, meuble, charges, caution, etage, annee_construction,
       date_disponibilite, description_en,
       lot_nombre
  FROM properties p
 WHERE is_published = true
   AND (status = ANY (ARRAY['Disponible'::property_status, 'Réservé'::property_status]))
   AND archived_at IS NULL;
