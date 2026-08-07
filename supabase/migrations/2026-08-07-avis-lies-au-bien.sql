-- ============================================================================
-- Lier un avis au bien concerné
-- ============================================================================
-- Un avis générique (« Super agence ! ») convainc moins qu'un avis daté et
-- rattaché à un bien précis (« Terrain à Bargny, TF-2024-0912 »). Ce lien se
-- fait au moment le plus naturel : quand un dossier de prospect passe à
-- « Conclu », le portefeuille propose déjà d'envoyer une demande d'avis par
-- WhatsApp (même déclencheur que le compteur « clients accompagnés »), avec
-- un lien qui pré-remplit le bien concerné sur le formulaire public.
--
-- property_ref et property_label sont dénormalisés (pas de clé étrangère vers
-- properties.ref) : un bien vendu est ensuite archivé ou republié sous un
-- autre statut, mais l'avis doit rester lisible tel qu'il a été laissé, même
-- des années plus tard.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.
-- ============================================================================

alter table public.reviews
  add column if not exists property_ref text,
  add column if not exists property_label text;

-- CREATE OR REPLACE VIEW n'accepte que des colonnes ajoutées EN FIN de liste
-- (déjà rencontré avec statut_foncier : Postgres refuse sinon, croyant qu'on
-- renomme une colonne existante).
create or replace view public.public_reviews as
select id,
    author_name,
    rating,
    comment,
    created_at,
    property_ref,
    property_label
from public.reviews
where status = 'Publié'
order by created_at desc;
