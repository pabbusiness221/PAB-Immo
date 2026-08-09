-- ============================================================================
-- Retrait de l'estimation vendeurs
-- ============================================================================
-- La fonctionnalité est retirée du site à la demande de l'agence.
--
-- Vérifié avant suppression : seller_estimates était vide, et aucun prospect
-- de la table leads n'en provenait. Aucune coordonnée n'est donc perdue. Ce
-- contrôle a été fait en premier, parce qu'une table de prospects supprimée
-- ne se récupère pas.
--
-- ---------------------------------------------------------------------------
-- ATTENTION : cette migration rejoue l'opération qui a causé C1
-- ---------------------------------------------------------------------------
-- Retirer des colonnes d'une vue impose un DROP puis un CREATE. PostgreSQL
-- n'autorise le CREATE OR REPLACE que pour AJOUTER des colonnes en fin de
-- liste, jamais pour en enlever.
--
-- Or c'est précisément cette recréation qui, le 7 août 2026, a fait perdre à
-- leads_enrichis sa clause `with (security_invoker = true)` et exposé tout le
-- fichier prospects (noms, téléphones, notes commerciales) à n'importe quel
-- visiteur anonyme, sans qu'aucune erreur ne le signale.
--
-- La clause est donc reposée explicitement, et les droits rendus à
-- l'identique. Contrôlé après application : security_invoker = true, un
-- appel anonyme renvoie [], l'admin voit toujours ses 5 fiches.
-- outils/verifier-rls.py rejoue ce contrôle à chaque exécution.
-- ============================================================================

-- 1. La vue cesse de dépendre de seller_estimates.
drop view if exists public.leads_enrichis;

create view public.leads_enrichis
with (security_invoker = true) as
select l.id,
    l.contact_key,
    l.name,
    l.contact,
    l.stage,
    l.property_id,
    l.notes,
    l.first_seen_at,
    l.last_activity_at,
    l.closed_at,
    p.ref as property_ref,
    p.commune as property_commune,
    p.type::text as property_type,
    coalesce(m.nb, 0::bigint) as nb_messages,
    coalesce(r.nb, 0::bigint) as nb_rdv,
    coalesce(r.nb_realises, 0::bigint) as nb_visites_realisees,
    extract(day from now() - l.last_activity_at)::integer as jours_sans_nouvelles
from leads l
    left join properties p on p.id = l.property_id
    left join (
      select contact_key(contact_messages.contact) as cle, count(*) as nb
      from contact_messages
      group by (contact_key(contact_messages.contact))
    ) m on m.cle = l.contact_key
    left join (
      select contact_key(appointments.contact) as cle,
             count(*) as nb,
             count(*) filter (where appointments.status = 'Réalisée'::text) as nb_realises
      from appointments
      group by (contact_key(appointments.contact))
    ) r on r.cle = l.contact_key;

grant select, insert, update, delete, references, trigger, truncate
  on public.leads_enrichis to anon, authenticated, service_role;

-- 2. Les déclencheurs de la table, puis la table elle-même.
drop trigger if exists a_trg_estimates_recalcul on public.seller_estimates;
drop trigger if exists trg_seller_estimates_rate_limit on public.seller_estimates;
drop trigger if exists trg_estimates_lead on public.seller_estimates;
drop table if exists public.seller_estimates;

-- 3. Les fonctions qui ne servaient qu'à l'estimation.
--    rattacher_lead() et enforce_submission_rate_limit() sont CONSERVÉES :
--    elles étaient partagées avec contact_messages et appointments, qui
--    continuent de s'en servir. Les supprimer casserait le pipeline de
--    prospects acheteurs et l'anti-abus des formulaires publics.
drop function if exists public.recalculer_estimation();
drop function if exists public.estimer_bien(property_type, operation_type, text, numeric);
drop function if exists public.normaliser_commune(text);
