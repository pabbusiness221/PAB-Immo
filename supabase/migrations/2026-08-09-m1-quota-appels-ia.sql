-- ============================================================================
-- M1 — plafonner les appels IA payants déclenchés depuis la vitrine
-- ============================================================================
-- traduire-description est publique par conception : elle sert les visiteurs
-- anglophones, pas l'administration. Elle était en revanche sans aucun
-- plafond. Vérifié le 9 août 2026 : la fonction répond à quiconque détient la
-- clé « publishable » du dépôt (401 sans clé, 404 avec, donc elle s'exécute).
-- Rien n'empêchait d'enchaîner les appels sur des biens non encore traduits
-- pour épuiser le quota Groq gratuit — et priver les vrais visiteurs de
-- traduction.
--
-- Même mécanique que enforce_submission_rate_limit (table submission_log,
-- empreinte SHA-256 de l'IP, plafond par appareil + plafond global, purge
-- intégrée), mais appelable depuis une fonction Edge : le déclencheur lit
-- `request.headers`, ce dont une fonction Edge ne dispose pas. Le sel de
-- hachage reste ici, côté base, comme pour le déclencheur — une seule
-- définition, pas deux qui divergeraient.
--
-- Le plafond n'est consulté que sur le CHEMIN PAYANT (cache manquant), jamais
-- pour servir une traduction déjà en base : un visiteur qui parcourt tout le
-- catalogue déjà traduit n'est jamais bloqué. Voir index.ts.
--
-- NON EXPOSÉE PUBLIQUEMENT : réservée au rôle de service. Ouverte à `anon`,
-- elle offrirait précisément le moyen d'épuiser le plafond global qu'elle est
-- censée protéger.
--
-- Contrôlé le 9 août 2026 :
--   • logique du compteur : 10 appels autorisés, 11e et 12e refusés
--   • droits : anon NON, authenticated NON, service_role OUI
--   • bien déjà traduit  → réponse servie, quota consommé = 0
--   • bien non traduit   → traduction produite et mise en cache, quota = 1
--
-- Idempotent : rejouable sans erreur.
-- ============================================================================

create or replace function public.consommer_quota_ia(
  p_bucket text,
  p_ip text,
  p_plafond integer default 10,
  p_plafond_global integer default 300
)
returns boolean
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  empreinte text;
  par_appareil integer;
  au_total integer;
begin
  empreinte := encode(
    extensions.digest(coalesce(nullif(p_ip, ''), 'inconnu') || '::pab-immo-v1', 'sha256'),
    'hex');

  select count(*) into par_appareil
    from public.submission_log
   where bucket = p_bucket
     and client_hash = empreinte
     and created_at > now() - interval '1 hour';

  if par_appareil >= p_plafond then
    return false;
  end if;

  select count(*) into au_total
    from public.submission_log
   where bucket = p_bucket
     and created_at > now() - interval '1 hour';

  if au_total >= p_plafond_global then
    return false;
  end if;

  insert into public.submission_log (bucket, client_hash)
       values (p_bucket, empreinte);

  delete from public.submission_log where created_at < now() - interval '2 hours';

  return true;
end;
$$;

revoke all on function public.consommer_quota_ia(text, text, integer, integer) from public;
revoke all on function public.consommer_quota_ia(text, text, integer, integer) from anon;
revoke all on function public.consommer_quota_ia(text, text, integer, integer) from authenticated;
grant execute on function public.consommer_quota_ia(text, text, integer, integer) to service_role;
