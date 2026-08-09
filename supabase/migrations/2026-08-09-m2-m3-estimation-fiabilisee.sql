-- ============================================================================
-- M2 + M3 — fiabiliser l'estimation vendeurs
-- ============================================================================
-- Deux défauts distincts relevés par l'audit du 9 août 2026, tous deux sur le
-- même chemin, d'où une seule migration.
--
-- ---------------------------------------------------------------------------
-- M3 — les communes ne se rapprochaient pas
-- ---------------------------------------------------------------------------
-- estimer_bien comparait la commune avec `=`, sur un champ saisi en texte
-- libre des deux côtés (formulaire vendeur ET fiches du portefeuille). Un
-- vendeur tapant « thies » ne trouvait rien, alors que la base contient
-- « Thiès ».
--
-- Constaté sur les données réelles : « Keur Moussa », « KEUR MOUSSA » et
-- « Communauté rurale de Keur Moussa » sont SIX biens d'une même localité,
-- éclatés en trois groupes de deux. Chaque groupe restant sous le seuil de
-- deux comparables, l'estimation ne sortait jamais — alors que la donnée
-- existait.
--
-- La normalisation est volontairement CONSERVATRICE : casse, accents, espaces
-- et préfixes administratifs seulement. Les suffixes directionnels ne sont pas
-- touchés — « Thiès », « Thies Nord » et « Thiès Ouest » sont trois communes
-- réellement distinctes et doivent le rester. Les fusionner fabriquerait des
-- comparables faux, ce qui est pire que pas de comparable du tout.
--
-- translate() plutôt que l'extension unaccent : immutable, sans dépendance, et
-- rien de plus à installer lors d'une restauration.
--
-- ---------------------------------------------------------------------------
-- M2 — la fourchette stockée venait du client
-- ---------------------------------------------------------------------------
-- La policy INSERT de seller_estimates est `with check (true)` (il le faut :
-- n'importe quel visiteur doit pouvoir déposer une demande). Mais le client
-- envoyait lui-même estimation_basse / estimation_haute / nb_comparables.
-- N'importe qui pouvait donc inscrire des chiffres inventés dans le CRM, que
-- l'agence aurait lus comme une estimation authentique produite par le site.
--
-- Un déclencheur BEFORE INSERT recalcule désormais ces trois champs à partir
-- de estimer_bien() : ce que le client envoie est ignoré. Aucune policy à
-- durcir, aucune colonne à retirer de l'API — la valeur est simplement
-- écrasée par celle du serveur.
--
-- Contrôlé le 9 août 2026 (transaction annulée, aucun faux prospect créé) :
-- insertion de 999 999 999 / 888 888 888 / 42 → stocké 4 167 000 / 25 000 000 / 2.
--
-- Idempotent : rejouable sans erreur.
-- ============================================================================

create or replace function public.normaliser_commune(p_commune text)
returns text
language sql
immutable
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

-- Reprend les deux verrous de confidentialité du correctif C2
-- (2026-08-09-estimer-bien-exclure-brouillons.sql) et y ajoute M3.
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
    and normaliser_commune(commune) = normaliser_commune(p_commune)
    and surface > 0
    and price > 0
    and is_published = true
  having count(*) >= 2
$$;

create or replace function public.recalculer_estimation()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  calcul record;
begin
  select * into calcul
    from public.estimer_bien(new.type, new.operation, new.commune, new.surface);

  if found then
    new.estimation_basse := calcul.estimation_basse;
    new.estimation_haute := calcul.estimation_haute;
    new.nb_comparables   := calcul.nb_comparables;
  else
    -- Sous le seuil de comparables : aucune fourchette n'est défendable.
    -- La demande reste enregistrée — c'est le prospect vendeur qui compte.
    new.estimation_basse := null;
    new.estimation_haute := null;
    new.nb_comparables   := 0;
  end if;

  return new;
end;
$$;

-- Nom préfixé « a_ » pour passer AVANT trg_seller_estimates_rate_limit dans
-- l'ordre alphabétique : inutile de recalculer une estimation si l'insertion
-- va être refusée pour abus.
drop trigger if exists a_trg_estimates_recalcul on public.seller_estimates;
create trigger a_trg_estimates_recalcul
  before insert on public.seller_estimates
  for each row execute function recalculer_estimation();
