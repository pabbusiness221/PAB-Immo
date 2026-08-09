-- ============================================================================
-- Réduction de la surface d'attaque RPC — suite de l'audit du 9 août 2026
-- ============================================================================
-- Passe finale sur les avertissements du linter Supabase. Chaque point a été
-- vérifié avant et après, côté anonyme ET côté admin : un durcissement qui
-- casserait le portefeuille serait pire que le défaut qu'il corrige.
--
-- ---------------------------------------------------------------------------
-- 1. normaliser_commune : search_path modifiable
-- ---------------------------------------------------------------------------
-- Défaut introduit le jour même par la migration M3. La fonction n'appelle
-- que des primitives de pg_catalog (lower, translate, regexp_replace, btrim,
-- nullif) : un search_path vide suffit, et supprime toute possibilité de
-- détourner l'un de ces appels via un schéma placé en tête de chemin.
-- ---------------------------------------------------------------------------

create or replace function public.normaliser_commune(p_commune text)
returns text
language sql
immutable
set search_path = ''
as $$
  select nullif(
    btrim(
      regexp_replace(
        regexp_replace(
          translate(
            lower(btrim(coalesce(p_commune, ''))),
            'àáâãäåèéêëìíîïòóôõöùúûüçñÿ',
            'aaaaaaeeeeiiiiooooouuuucny'
          ),
          '^(commune|communaute rurale|communaute|region|ville|departement|arrondissement)\s+(de|du|d''|d’)\s*',
          ''
        ),
        '\s+', ' ', 'g'
      )
    ),
  '');
$$;

-- ---------------------------------------------------------------------------
-- 2. Les onze fonctions de déclencheur quittent l'API publique
-- ---------------------------------------------------------------------------
-- Elles apparaissaient toutes sous /rest/v1/rpc/. PostgreSQL ne vérifie PAS
-- le droit EXECUTE lorsqu'un déclencheur se déclenche : la révocation est donc
-- sans aucun effet sur le fonctionnement des tables, et retire onze points
-- d'entrée inutiles. Contrôlé après coup : rattacher_lead répond désormais
-- PGRST202 (fonction inconnue) et les insertions publiques marchent toujours.
--
-- ATTENTION : retirer à `anon` et `authenticated` ne suffit pas. Le droit
-- EXECUTE est accordé par défaut au pseudo-rôle PUBLIC, dont ces deux-là
-- héritent — c'est l'erreur commise au premier essai, les fonctions
-- répondaient encore. Il faut révoquer sur PUBLIC.
-- ---------------------------------------------------------------------------

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as signature
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    join pg_type t on t.oid = p.prorettype
    where n.nspname = 'public' and p.prosecdef and t.typname = 'trigger'
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.signature);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 3. Fonctions d'administration : hors de portée d'un anonyme
-- ---------------------------------------------------------------------------
-- sante_notifications() était la seule réellement bavarde. Vérifié avant
-- correctif : un visiteur anonyme obtenait la date du dernier envoi d'e-mail
-- et les volumes sur sept jours. Aucune donnée personnelle, mais de la
-- télémétrie d'exploitation qui ne regarde que l'agence.
--
-- stats_prospects() et dernier_login() filtrent déjà en interne (is_admin(),
-- auth.uid()) — contrôlé, un anonyme n'obtenait que des zéros ou NULL. On
-- retire tout de même l'accès : deux verrous valent mieux qu'un, et c'est
-- exactement la leçon de C1.
-- ---------------------------------------------------------------------------

revoke all on function public.sante_notifications() from public, anon;
revoke all on function public.stats_prospects()     from public, anon;
revoke all on function public.dernier_login(uuid)   from public, anon;

grant execute on function public.sante_notifications() to authenticated, service_role;
grant execute on function public.stats_prospects()     to authenticated, service_role;
grant execute on function public.dernier_login(uuid)   to authenticated, service_role;

-- is_admin() n'est VOLONTAIREMENT pas touchée. Elle est évaluée à l'intérieur
-- des policies RLS, avec les droits de l'appelant : la révoquer casserait
-- toutes les politiques qui s'en servent — y compris celles qui autorisent un
-- visiteur anonyme à déposer un message. Le linter la signalera toujours ;
-- c'est un faux positif pour cette architecture.

-- ---------------------------------------------------------------------------
-- 4. notification_health : lisible par tout compte connecté
-- ---------------------------------------------------------------------------
-- La vue lisait avec les droits de son propriétaire, donc sans RLS : les
-- collaborateurs voyaient la santé des envois d'e-mails de l'agence.
-- notification_log porte déjà une policy « réservé à l'admin » ;
-- security_invoker la fait simplement appliquer. Rien d'autre à écrire.
-- Contrôlé : l'admin voit toujours sa ligne, le bandeau rouge fonctionne.
-- ---------------------------------------------------------------------------

alter view public.notification_health set (security_invoker = true);

-- ---------------------------------------------------------------------------
-- 5. Clé étrangère sans index
-- ---------------------------------------------------------------------------
-- Chaque suppression d'un compte administrateur imposait un parcours complet
-- de la table pour vérifier les références.
-- ---------------------------------------------------------------------------

create index if not exists idx_admins_created_by on public.admins (created_by);

-- ---------------------------------------------------------------------------
-- CE QUI RESTE SIGNALÉ PAR LE LINTER, ET POURQUOI ON N'Y TOUCHE PAS
-- ---------------------------------------------------------------------------
-- • security_definer_view sur public_properties, public_property_photos,
--   public_reviews, public_stats — VOULU. Ces vues filtrent elles-mêmes ce
--   qu'elles exposent et doivent contourner le RLS des tables sous-jacentes
--   pour servir un visiteur anonyme. Y mettre security_invoker les rendrait
--   vides et casserait la vitrine. outils/verifier-rls.py prouve à chaque
--   exécution qu'elles ne montrent rien d'autre que le catalogue publié.
--
-- • spatial_ref_sys sans RLS, postgis dans public — objets système de PostGIS,
--   propriété de supabase_admin. Non modifiables depuis le projet.
--
-- • estimer_bien exécutable par anon — VOULU, c'est la fonction publique
--   d'estimation. Sa portée a été corrigée le même jour (voir
--   2026-08-09-estimer-bien-exclure-brouillons.sql).
--
-- • unused_index — la base compte 18 biens et 5 prospects : « jamais
--   utilisé » signifie ici « pas encore ». Les supprimer serait une
--   optimisation prématurée qui coûterait cher à la première montée en
--   charge. À réexaminer quand le catalogue aura grandi.
--
-- • multiple_permissive_policies — fusionner « réservé à l'admin » et
--   « visible par le propriétaire du bien » en une seule politique est
--   logiquement équivalent, mais touche au contrôle d'accès pour un gain de
--   performance nul à cette échelle. C1 est né d'une modification jugée
--   anodine sur une vue : on ne refait pas le même pari sur des policies.
--
-- Idempotent : rejouable sans erreur.
-- ============================================================================
