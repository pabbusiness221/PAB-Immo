-- ============================================================
-- 2026-08-16 — Colonnes réservées aux insertions anonymes,
--              et remise en service du veilleur de notifications
-- ============================================================
--
-- Trois constats de l'audit de sécurité du 16 août.
--
--
-- 1. LES INSERTIONS PUBLIQUES POUVAIENT POSER N'IMPORTE QUELLE COLONNE
--
-- Les policies d'insertion portaient WITH CHECK (true) et le droit INSERT
-- était accordé sur la table entière, donc sur toutes ses colonnes. Vérifié
-- en conditions réelles avec la seule clé publique :
--
--   contact_messages.is_read = true   -> 201 accepté. Le message n'incrémente
--     alors plus le compteur de non-lus, n'apparaît pas sous le filtre « non
--     lus » et ne porte pas la classe unread : il arrive invisible.
--   appointments.status = 'Confirmé'  -> 201 accepté. Un rendez-vous entrait
--     dans l'agenda déjà confirmé, sans que personne ne l'ait confirmé.
--   created_at = '2099-01-01'         -> 201 accepté. Le message restait en
--     tête de liste indéfiniment — ou, daté de 2020, au fond.
--
-- Deux tables résistaient déjà, chacune à sa façon : reviews par un
-- WITH CHECK (status = 'En attente'), collaborator_requests par une contrainte
-- CHECK. La protection existait donc, elle n'avait simplement pas été appliquée
-- partout. On généralise les deux mécanismes plutôt que d'en inventer un
-- troisième.
--
-- Deux remèdes selon le cas :
--   - colonne JAMAIS envoyée par les formulaires (id, created_at, is_active,
--     reviewed_*) : on retire le droit. Toutes ont un défaut en base, vérifié
--     avant écriture, donc rien ne se casse.
--   - colonne envoyée mais dont la valeur doit être imposée (is_read, status) :
--     on garde le droit et on contraint la VALEUR par RLS. Contraindre par la
--     policy plutôt que par le client est le seul moyen sûr : le client peut
--     être contourné, la policy non.
--
--
-- 2. sante_notifications() RENSEIGNAIT TOUT COMPTE AUTHENTIFIÉ
--
-- La fonction est SECURITY DEFINER et son exécution est accordée à
-- authenticated, mais son corps ne vérifiait aucun rôle. Or l'inscription
-- publique est ouverte : n'importe qui pouvait créer un compte et lire le
-- volume d'envois et la date du dernier envoi réussi. Mesuré en simulant un
-- compte ordinaire : envois_7j = 6, dernier_envoi_reussi renseigné.
--
-- stats_prospects(), écrite dans le même style, portait bien sa garde
-- (« where public.is_admin() ») : l'oubli était isolé, pas systémique.
--
--
-- 3. …MAIS LE VEILLEUR S'EN SERVAIT, ET IL EST MORT DEPUIS LE 9 AOÛT
--
-- surveiller-notifications.yml interroge cette fonction toutes les six heures
-- avec la seule clé publique. Le durcissement du 9 août a révoqué le droit à
-- anon sans toucher au workflow : depuis, l'appel renvoie 401 et l'action
-- échoue. Huit exécutions consécutives en échec au moment de l'audit.
--
-- C'est pire qu'un veilleur absent : il crie toutes les six heures pour une
-- raison qui n'est pas celle qu'il surveille, et on apprend à ne plus l'écouter.
--
-- D'où la séparation en deux fonctions :
--   - sante_notifications()          — le détail, réservé à l'administration ;
--   - sante_notifications_publique() — un simple état de santé, lisible par le
--     veilleur. Elle ne renvoie AUCUN compteur ni date : les journaux d'une
--     GitHub Action sont publics sur un dépôt public, ce qui exclut d'y écrire
--     des volumes d'activité.
-- ============================================================


-- --- 1. Colonnes autorisées à l'insertion anonyme ------------------------
-- On repart de zéro pour chaque table : REVOKE sur la table, puis GRANT sur
-- la seule liste des colonnes que les formulaires envoient réellement.

revoke insert on public.site_visits from anon, authenticated;
grant insert (session_id) on public.site_visits to anon, authenticated;

revoke insert on public.property_views from anon, authenticated;
grant insert (property_id, session_id) on public.property_views to anon, authenticated;

revoke insert on public.favorite_events from anon, authenticated;
grant insert (property_id, session_id, action) on public.favorite_events to anon, authenticated;

revoke insert on public.contact_messages from anon, authenticated;
grant insert (property_id, name, contact, message, is_read)
  on public.contact_messages to anon, authenticated;

revoke insert on public.appointments from anon, authenticated;
grant insert (property_id, name, contact, preferred_date, preferred_time, message, status)
  on public.appointments to anon, authenticated;

revoke insert on public.alert_subscriptions from anon, authenticated;
grant insert (email, type, operation, region, budget_max)
  on public.alert_subscriptions to anon, authenticated;

revoke insert on public.collaborator_requests from anon, authenticated;
grant insert (agency_name, contact_name, contact, zone, portfolio_size, message)
  on public.collaborator_requests to anon, authenticated;

-- reviews : status n'est pas accordé. Le formulaire ne l'envoie pas, le défaut
-- 'En attente' s'applique, et le WITH CHECK existant le vérifie ensuite.
revoke insert on public.reviews from anon, authenticated;
grant insert (author_name, rating, comment, property_ref, property_label)
  on public.reviews to anon, authenticated;


-- --- 2. Valeurs imposées pour les deux colonnes qui restent envoyées ------
-- is_read : le formulaire envoie false. On refuse true — un message ne peut
-- pas naître déjà lu. IS NOT TRUE couvre aussi le cas où la colonne est omise.
drop policy if exists "Tout le monde peut envoyer un message" on public.contact_messages;
create policy "Tout le monde peut envoyer un message"
  on public.contact_messages for insert
  to anon, authenticated
  with check (is_read is not true);

-- status : même raisonnement, et même formulation que la policy des avis, qui
-- tenait déjà. Un rendez-vous naît « En attente », jamais confirmé.
drop policy if exists "Tout le monde peut demander un RDV" on public.appointments;
create policy "Tout le monde peut demander un RDV"
  on public.appointments for insert
  to anon, authenticated
  with check (status = 'En attente');


-- --- 3. Santé des notifications : détail à l'admin, état au veilleur ------
create or replace function public.sante_notifications()
returns table(ok boolean, echecs_7j bigint, envois_7j bigint,
              dernier_envoi_reussi timestamptz, dernier_echec timestamptz,
              demandes_recues_7j bigint, message text)
language sql
stable
security definer
set search_path to 'public'
as $function$
  with sante as (
    select * from public.notification_health
  ),
  demandes as (
    select
      (select count(*) from public.contact_messages where created_at > now() - interval '7 days')
    + (select count(*) from public.appointments where created_at > now() - interval '7 days')
      as demandes_recues_7j
  )
  select
    case
      when sante.echecs_7j > 0 then false
      when demandes.demandes_recues_7j > 0 and sante.envois_7j = 0 then false
      else true
    end as ok,
    sante.echecs_7j,
    sante.envois_7j,
    sante.dernier_envoi_reussi,
    sante.dernier_echec,
    demandes.demandes_recues_7j,
    case
      when sante.echecs_7j > 0 then
        sante.echecs_7j || ' échec(s) d''envoi sur 7 jours. Dernier détail : ' || coalesce(sante.dernier_message, '—')
      when demandes.demandes_recues_7j > 0 and sante.envois_7j = 0 then
        demandes.demandes_recues_7j || ' demande(s) reçue(s) en 7 jours mais aucun email envoyé : la chaîne de notification semble arrêtée.'
      else 'OK'
    end as message
  from sante, demandes
  -- La garde qui manquait. Les chiffres restent identiques pour l'admin.
  where public.is_admin();
$function$;

-- Version publique : un booléen et une phrase générique, rien d'autre. Assez
-- pour qu'une alerte se déclenche, trop peu pour renseigner qui que ce soit.
create or replace function public.sante_notifications_publique()
returns table(ok boolean, message text)
language sql
stable
security definer
set search_path to 'public'
as $function$
  with sante as (
    select * from public.notification_health
  ),
  demandes as (
    select
      (select count(*) from public.contact_messages where created_at > now() - interval '7 days')
    + (select count(*) from public.appointments where created_at > now() - interval '7 days')
      as demandes_recues_7j
  )
  select
    case
      when sante.echecs_7j > 0 then false
      when demandes.demandes_recues_7j > 0 and sante.envois_7j = 0 then false
      else true
    end as ok,
    case
      when sante.echecs_7j > 0 or (demandes.demandes_recues_7j > 0 and sante.envois_7j = 0)
        then 'Chaine de notification a verifier. Detail dans le portefeuille.'
      else 'OK'
    end as message
  from sante, demandes;
$function$;

revoke all on function public.sante_notifications_publique() from public;
grant execute on function public.sante_notifications_publique() to anon, authenticated, service_role;
