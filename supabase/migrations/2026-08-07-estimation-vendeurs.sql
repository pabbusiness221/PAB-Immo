-- ============================================================================
-- Estimation indicative et capture des prospects vendeurs
-- ============================================================================
-- Le site n'adressait jusqu'ici que les acheteurs/locataires. Un propriétaire
-- qui veut vendre ou louer n'avait aucune raison de laisser ses coordonnées.
-- Cette migration ajoute :
--   1. estimer_bien() — fonction publique qui calcule une fourchette de prix
--      à partir de l'historique RÉEL de l'agence (properties), y compris les
--      biens archivés : un bien vendu reste une donnée de marché pertinente
--      même une fois retiré de la vitrine. Elle ne renvoie qu'un agrégat
--      (fourchette + nombre de comparables) — jamais les biens individuels
--      qui la composent, pour ne rien révéler des annonces des autres
--      propriétaires.
--   2. seller_estimates — la demande elle-même (bien décrit + coordonnées),
--      déposée par n'importe quel visiteur, lisible seulement par l'admin.
--   3. Les mêmes déclencheurs que contact_messages/appointments : anti-abus
--      (enforce_submission_rate_limit) et rattachement automatique au
--      pipeline de prospects (rattacher_lead) — un prospect vendeur suit
--      exactement le même parcours (Nouveau → Contacté → … → Conclu) que
--      les prospects acheteurs, sans réinventer une deuxième liste.
--   4. leads_enrichis expose la dernière estimation demandée par ce contact,
--      pour que l'admin voie le bien décrit sans devoir rouvrir une autre
--      table.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.
-- ============================================================================

create table if not exists public.seller_estimates (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  contact text not null,
  -- Toujours NULL : présent uniquement pour que rattacher_lead() (partagé
  -- avec contact_messages et appointments, qui lisent new.property_id) reste
  -- utilisable ici sans être dupliqué ni modifié.
  property_id uuid,
  type property_type not null,
  operation operation_type not null,
  commune text not null,
  quartier text,
  surface numeric not null,
  estimation_basse numeric,
  estimation_haute numeric,
  nb_comparables integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.seller_estimates enable row level security;

do $$ begin
  create policy "Tout le monde peut demander une estimation"
    on public.seller_estimates for insert
    to public
    with check (true);
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Estimations reservees a l'admin"
    on public.seller_estimates for select
    to public
    using (is_admin());
exception when duplicate_object then null;
end $$;

do $$ begin
  create policy "Suppression estimations reservee a l'admin"
    on public.seller_estimates for delete
    to public
    using (is_admin());
exception when duplicate_object then null;
end $$;

grant select, insert, delete on public.seller_estimates to anon, authenticated;

drop trigger if exists trg_seller_estimates_rate_limit on public.seller_estimates;
create trigger trg_seller_estimates_rate_limit
  before insert on public.seller_estimates
  for each row execute function enforce_submission_rate_limit();

drop trigger if exists trg_estimates_lead on public.seller_estimates;
create trigger trg_estimates_lead
  after insert on public.seller_estimates
  for each row execute function rattacher_lead();

-- Fourchette = prix/m² min et max des biens comparables (même type, même
-- opération, même commune) sur tout l'historique, multiplié par la surface
-- demandée. Simple et honnête : avec le peu de biens d'une agence de cette
-- taille, une moyenne ± une marge inventée serait une fausse précision.
--
-- ⚠️ VERSION CORRIGÉE LE 9 AOÛT 2026 — voir
-- 2026-08-09-estimer-bien-exclure-brouillons.sql, qui remplace cette
-- définition. Telle qu'écrite ici, la fonction n'appliquait AUCUN filtre de
-- visibilité : étant SECURITY DEFINER et ouverte à `anon`, elle laissait
-- interroger de l'extérieur le prix au m² de biens jamais publiés. La version
-- ci-dessous est conservée pour l'historique ; c'est la migration du 9 août
-- qui fait foi.
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
$$;

grant execute on function public.estimer_bien(property_type, operation_type, text, numeric) to anon, authenticated;

-- CREATE OR REPLACE VIEW n'accepte que des colonnes ajoutées EN FIN de liste
-- (déjà rencontré avec statut_foncier). La sous-requête latérale évite le
-- doublon de ligne qu'un simple LEFT JOIN produirait si un même contact avait
-- demandé plusieurs estimations : seule la plus récente est montrée.
--
-- ⚠️ NE JAMAIS OMETTRE `with (security_invoker = true)` ICI.
-- CREATE OR REPLACE VIEW sans clause WITH ne conserve pas les options
-- existantes : il les réinitialise. La version initiale de cette migration
-- l'avait omise, ce qui a fait relire la vue avec les droits de son
-- propriétaire, contourner le RLS de `leads` et exposer tous les prospects
-- (nom, contact, notes) à n'importe quel visiteur anonyme via l'API REST
-- publique. Corrigé le 9 août 2026 ; voir
-- 2026-08-09-retablir-security-invoker-leads-enrichis.sql.
create or replace view public.leads_enrichis
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
    extract(day from now() - l.last_activity_at)::integer as jours_sans_nouvelles,
    e.type as estimation_type,
    e.operation as estimation_operation,
    e.commune as estimation_commune,
    e.surface as estimation_surface,
    e.estimation_basse as estimation_basse,
    e.estimation_haute as estimation_haute
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
    ) r on r.cle = l.contact_key
    left join lateral (
      select se.type, se.operation, se.commune, se.surface, se.estimation_basse, se.estimation_haute
      from public.seller_estimates se
      where contact_key(se.contact) = l.contact_key
      order by se.created_at desc
      limit 1
    ) e on true;
