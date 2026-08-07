-- ============================================================================
-- Description anglaise du bien — traduite à la volée, mise en cache
-- ============================================================================
-- Étape 2 du multilingue : les descriptions de biens sont rédigées en
-- français par l'agence et jamais retraduites à la main. Plutôt que de payer
-- un appel IA à chaque visite anglophone, le premier visiteur qui consulte un
-- bien en anglais déclenche la traduction (edge function traduire-description,
-- côté serveur, clé Groq jamais exposée) ; elle est ensuite mise en cache ici
-- pour tous les visiteurs suivants.
--
-- NULL par défaut : un bien jamais consulté en anglais n'a simplement pas de
-- traduction, pas une traduction vide ou inventée.
--
-- Invalidation : si l'agence modifie la description française, l'admin remet
-- ce champ à NULL (voir saveProperty() dans Portefeuille-Immo.html) pour
-- qu'une nouvelle traduction, à jour, soit générée au prochain visiteur.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.
-- ============================================================================

alter table public.properties
  add column if not exists description_en text;

-- CREATE OR REPLACE VIEW n'accepte que des colonnes ajoutées EN FIN de liste
-- (déjà rencontré avec statut_foncier).
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
    date_disponibilite,
    description_en
from public.properties p
where is_published = true and (status = any (array['Disponible'::property_status, 'Réservé'::property_status])) and archived_at is null;
