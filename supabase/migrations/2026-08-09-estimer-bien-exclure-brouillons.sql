-- ============================================================================
-- CORRECTIF DE SÉCURITÉ — estimer_bien() ne doit pas voir les brouillons
-- ============================================================================
-- Faille : la fonction interrogeait `properties` sans AUCUN filtre de
-- visibilité (ni is_published, ni archived_at, ni status). Étant SECURITY
-- DEFINER et ouverte à `anon`, elle permettait à n'importe qui d'interroger le
-- catalogue non publié depuis l'extérieur.
--
-- En appelant la RPC avec p_surface = 1, la « fourchette » renvoie directement
-- le prix au m². Et lorsqu'un seul bien correspond, min et max désignent le
-- MÊME bien : l'agrégat cesse d'en être un et divulgue un prix exact. Le
-- commentaire d'origine affirmait pourtant ne « rien révéler des annonces des
-- autres propriétaires » — l'implémentation le contredisait.
--
-- Vérifié le 9 août 2026 avant correctif (visiteur anonyme, clé publique) :
--   Saly / Maison / Vente              → 400 000 FCFA/m²   (0 bien public)
--   Almadies / Appartement / Location  →   6 000 FCFA/m²   (0 bien public)
-- Après correctif : les deux renvoient [].
--
-- ---------------------------------------------------------------------------
-- Deux verrous, cumulatifs
-- ---------------------------------------------------------------------------
-- 1. `is_published = true`
--    Exclut les brouillons — du stock jamais rendu public. Les biens vendus,
--    loués ou archivés restent inclus : leur prix A ÉTÉ public, et c'est
--    précisément la donnée de marché sur laquelle l'estimation s'appuie
--    (intention d'origine, conservée). C'est bien `is_published`, et non
--    `status` ni `archived_at`, qui trace la frontière « a-t-il déjà été rendu
--    public ? » — - contrôlé sur les données réelles : les 3 fuites étaient des
--    brouillons (is_published = false), la 4e un bien loué anciennement publié.
--
-- 2. `having count(*) >= 2`
--    Sous deux comparables, la fourchette divulgue un prix exact. Cette règle
--    existait déjà dans vitrine.html, mais UNIQUEMENT côté client : un appel
--    direct à la RPC la contournait. Une règle de confidentialité appartient
--    au serveur.
--
-- ---------------------------------------------------------------------------
-- Comportement sous le seuil
-- ---------------------------------------------------------------------------
-- La fonction ne renvoie aucune ligne. Contrôlé dans le navigateur sur la
-- vraie page : la vitrine affiche « Pas assez de biens comparables… », aucune
-- erreur JavaScript, et le formulaire de contact reste affiché — le prospect
-- vendeur est donc toujours capté, ce qui est l'objectif commercial de la
-- section. L'insertion enregistre alors estimation_basse/haute = null et
-- nb_comparables = 0.
--
-- ---------------------------------------------------------------------------
-- Conséquence à connaître
-- ---------------------------------------------------------------------------
-- Avec le catalogue actuel (18 biens publiés), une seule combinaison
-- commune/type/opération atteint 2 comparables. L'estimation chiffrée sera
-- donc rare tant que le portefeuille n'aura pas grossi. Ce n'est pas un
-- régression : c'est la règle des 2 comparables enfin appliquée honnêtement.
-- Deux leviers l'amélioreront, sans toucher à la sécurité : normaliser la
-- commune (« KEUR MOUSSA » et « Keur Moussa » comptent aujourd'hui comme deux
-- communes distinctes et fractionnent les comparables), et publier plus de
-- biens.
--
-- Idempotent : rejouable sans erreur.
-- ============================================================================

create or replace function public.estimer_bien(
  p_type property_type,
  p_operation operation_type,
  p_commune text,
  p_surface numeric
)
returns table(estimation_basse numeric, estimation_haute numeric, nb_comparables integer)
language sql
security definer
set search_path = public
stable
as $$
  select
    round(min(price / surface) * p_surface / 1000) * 1000,
    round(max(price / surface) * p_surface / 1000) * 1000,
    count(*)::integer
  from properties
  where type = p_type
    and operation = p_operation
    and commune = p_commune
    and surface > 0
    and price > 0
    and is_published = true
  having count(*) >= 2
$$;
