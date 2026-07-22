-- ============================================================================
-- PAB Immo — schéma complet de la base
-- ============================================================================
-- Extrait de la base de production (projet avanktgaxepzpqmsiauz) le 21/07/2026.
-- Ce fichier permet de reconstruire une base vide à l'identique : structure,
-- vues, fonctions, déclencheurs, index et règles de sécurité.
--
-- CE FICHIER NE CONTIENT AUCUNE DONNÉE, ET NE DOIT JAMAIS EN CONTENIR.
-- Le dépôt est public ; les tables contact_messages et appointments
-- contiennent des noms, téléphones et emails de prospects.
--
-- Ordre de restauration et pièges : voir docs/SAUVEGARDES.md
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Extensions
-- ----------------------------------------------------------------------------
create extension if not exists "pgcrypto"    with schema extensions;
create extension if not exists "uuid-ossp"   with schema extensions;
create extension if not exists "pg_net"      with schema extensions;  -- appels HTTP depuis les déclencheurs
create extension if not exists "postgis"     with schema public;      -- colonne geography + index gist


-- ----------------------------------------------------------------------------
-- 2. Types énumérés
-- ----------------------------------------------------------------------------
create type public.property_type   as enum ('Terrain', 'Maison', 'Appartement', 'Champ agricole');
create type public.operation_type  as enum ('Vente', 'Location');
create type public.property_status as enum ('Disponible', 'Réservé', 'Vendu', 'Loué');


-- ----------------------------------------------------------------------------
-- 3. Fonction d'identification de l'administrateur
-- ----------------------------------------------------------------------------
-- ATTENTION : l'identifiant est écrit en dur. Sur une restauration dans un
-- nouveau projet, il faut le remplacer par l'identifiant du compte admin
-- recréé, sinon plus personne n'a accès à rien.
create or replace function public.is_admin()
returns boolean
language sql
stable
as $function$
  select auth.uid() = '514ff065-fa33-454b-9701-c9aec9053862'::uuid;
$function$;


-- ----------------------------------------------------------------------------
-- 4. Tables — dans l'ordre des dépendances
-- ----------------------------------------------------------------------------

create table public.properties (
  id uuid default gen_random_uuid() not null,
  owner_id uuid default auth.uid() not null,
  ref text not null,
  type property_type not null,
  operation operation_type not null,
  status property_status default 'Disponible'::property_status not null,
  commune text not null,
  region text not null,
  quartier text,
  lat double precision not null,
  lng double precision not null,
  -- Colonne GÉNÉRÉE, pas une valeur par défaut : PostgreSQL refuse qu'un
  -- DEFAULT référence d'autres colonnes. L'extraction initiale l'avait
  -- transcrite en `default`, ce qui rendait ce fichier irrestaurable ;
  -- l'erreur n'est apparue qu'en rejouant réellement le script.
  location geography(Point,4326) generated always as ((st_setsrid(st_makepoint(lng, lat), 4326))::geography) stored,
  surface numeric(10,1) not null,
  price numeric(14,0) not null,
  description text,
  chambres smallint,
  salons smallint,
  salles_bain smallint,
  cuisine text,
  equipements text[],
  date_acquisition date,
  notes text,
  is_published boolean default false not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null,
  departement text,
  archived_at timestamp with time zone,
  -- Badges de confiance. verified_at ne peut être posé que par l'admin
  -- (déclencheur trg_properties_verification) ; availability_checked_at est
  -- déclaratif et rafraîchissable par le propriétaire du bien.
  verified_at timestamp with time zone,
  verified_by uuid,
  availability_checked_at timestamp with time zone,
  constraint properties_pkey PRIMARY KEY (id),
  constraint properties_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES auth.users(id) ON DELETE SET NULL,
  constraint properties_ref_key UNIQUE (ref),
  constraint properties_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id)
);

create table public.property_photos (
  id uuid default gen_random_uuid() not null,
  property_id uuid not null,
  storage_path text not null,
  "position" smallint default 0 not null,
  is_cover boolean default false not null,
  created_at timestamp with time zone default now() not null,
  constraint property_photos_pkey PRIMARY KEY (id),
  constraint property_photos_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
);

create table public.property_status_history (
  id uuid default gen_random_uuid() not null,
  property_id uuid not null,
  old_status property_status,
  new_status property_status not null,
  changed_at timestamp with time zone default now() not null,
  constraint property_status_history_pkey PRIMARY KEY (id),
  constraint property_status_history_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
);

create table public.property_views (
  id uuid default gen_random_uuid() not null,
  property_id uuid,
  session_id text,
  created_at timestamp with time zone default now() not null,
  constraint property_views_pkey PRIMARY KEY (id),
  constraint property_views_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
);

create table public.favorite_events (
  id uuid default gen_random_uuid() not null,
  property_id uuid,
  session_id text not null,
  action text default 'add'::text not null,
  created_at timestamp with time zone default now() not null,
  constraint favorite_events_pkey PRIMARY KEY (id),
  constraint favorite_events_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
);

create table public.contact_messages (
  id uuid default gen_random_uuid() not null,
  property_id uuid,
  name text not null,
  contact text not null,
  message text not null,
  is_read boolean default false not null,
  created_at timestamp with time zone default now() not null,
  constraint contact_messages_pkey PRIMARY KEY (id),
  constraint contact_messages_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE SET NULL
);

create table public.appointments (
  id uuid default gen_random_uuid() not null,
  property_id uuid,
  name text not null,
  contact text not null,
  preferred_date date not null,
  preferred_time text,
  message text,
  status text default 'En attente'::text not null,
  created_at timestamp with time zone default now() not null,
  constraint appointments_pkey PRIMARY KEY (id),
  -- Quatre valeurs seulement : la colonne est du texte libre, une faute de
  -- frappe y créait sinon un statut fantôme, exclu des filtres et des comptages.
  constraint appointments_status_check CHECK (status in ('En attente', 'Confirmé', 'Réalisée', 'Annulé')),
  constraint appointments_property_id_fkey FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE SET NULL
);

create table public.alert_subscriptions (
  id uuid default gen_random_uuid() not null,
  email text not null,
  type text,
  operation text,
  region text,
  budget_max numeric(14,0),
  is_active boolean default true not null,
  created_at timestamp with time zone default now() not null,
  constraint alert_subscriptions_pkey PRIMARY KEY (id)
);

create table public.collaborators (
  user_id uuid not null,
  display_name text not null,
  created_at timestamp with time zone default now() not null,
  -- Décision métier : un collaborateur EST une agence. Certification réservée
  -- à l'admin (déclencheur trg_collaborators_verification).
  verified_at timestamp with time zone,
  verified_by uuid,
  constraint collaborators_pkey PRIMARY KEY (user_id),
  constraint collaborators_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES auth.users(id) ON DELETE SET NULL,
  constraint collaborators_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

create table public.site_visits (
  id uuid default gen_random_uuid() not null,
  session_id text not null,
  created_at timestamp with time zone default now() not null,
  constraint site_visits_pkey PRIMARY KEY (id)
);

create table public.activity_logs (
  id uuid default gen_random_uuid() not null,
  actor_id uuid,
  action text not null,
  entity_type text default 'property'::text not null,
  entity_id uuid,
  details jsonb,
  created_at timestamp with time zone default now() not null,
  constraint activity_logs_pkey PRIMARY KEY (id),
  constraint activity_logs_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES auth.users(id) ON DELETE SET NULL
);


create table public.site_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz default now() not null,
  updated_by uuid,
  constraint site_settings_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES auth.users(id) ON DELETE SET NULL
);


-- Journal du frein anti-abus. Ne contient JAMAIS d'adresse IP : seulement une
-- empreinte non réversible, suffisante pour compter, inutilisable pour
-- identifier quelqu'un. Purgé automatiquement au-delà de deux heures.
create table public.submission_log (
  id bigserial primary key,
  bucket text not null,
  client_hash text not null,
  created_at timestamptz not null default now()
);


-- ----------------------------------------------------------------------------
-- 5. Vues publiques
-- ----------------------------------------------------------------------------
-- Ce que la vitrine et la fonction share-preview ont le droit de lire :
-- uniquement les biens publiés, non archivés, encore disponibles ou réservés.
-- Les colonnes internes (notes, date d'acquisition, propriétaire) sont exclues.

create or replace view public.public_properties as
  select p.id, p.ref, p.type, p.operation, p.status, p.commune, p.region, p.quartier, p.departement,
         p.lat, p.lng, p.surface, p.price, p.description,
         p.chambres, p.salons, p.salles_bain, p.cuisine, p.equipements,
         p.verified_at, p.availability_checked_at,
         -- Seul le badge est public : ni le nom de l'agence ni l'identité de
         -- son responsable ne sont exposés, ce sont des données personnelles.
         exists (select 1 from collaborators c
                 where c.user_id = p.owner_id and c.verified_at is not null) as agence_verifiee
  from properties p
  where p.is_published = true
    and p.status = any (array['Disponible'::property_status, 'Réservé'::property_status])
    and p.archived_at is null;

create or replace view public.public_property_photos as
  select pp.id, pp.property_id, pp.storage_path, pp."position", pp.is_cover
  from property_photos pp
  join properties p on p.id = pp.property_id
  where p.is_published = true
    and p.status = any (array['Disponible'::property_status, 'Réservé'::property_status])
    and p.archived_at is null;


-- Chiffres affichables sur la vitrine. UNIQUEMENT des agrégats : aucun nom,
-- aucun identifiant, aucune donnée personnelle.
create or replace view public.public_stats as
  select
    (select count(*) from collaborators where verified_at is not null)      as agences_verifiees,
    (select count(*) from properties
      where is_published = true and archived_at is null
        and status = any (array['Disponible'::property_status,'Réservé'::property_status])) as biens_publies,
    (select count(*) from property_status_history
      where new_status in ('Vendu','Loué'))                                 as transactions_conclues,
    -- Chiffre déclaratif, saisi depuis l'espace d'administration : aucune
    -- donnée ne le mesure, c'est l'agence qui l'affirme.
    (select (value #>> '{}')::int from site_settings where key = 'clients_accompagnes') as clients_accompagnes;

grant select on public.public_stats to anon, authenticated;


-- ----------------------------------------------------------------------------
-- 6. Fonctions de déclenchement
-- ----------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $function$
begin
  new.updated_at = now();
  return new;
end;
$function$;

-- Historise chaque changement de statut d'un bien.
create or replace function public.log_status_change()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
begin
  if (tg_op = 'UPDATE' and old.status is distinct from new.status) then
    insert into public.property_status_history (property_id, old_status, new_status)
    values (new.id, old.status, new.status);
  end if;
  return new;
end;
$function$;

-- Journal d'activité : création, modification, changement de statut,
-- archivage, restauration et suppression définitive d'un bien.
create or replace function public.log_property_activity()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  act text;
  details jsonb;
begin
  if tg_op = 'INSERT' then
    act := 'create_property';
    details := jsonb_build_object('ref', new.ref);

  elsif tg_op = 'UPDATE' then
    if old.archived_at is null and new.archived_at is not null then
      act := 'archive_property';
    elsif old.archived_at is not null and new.archived_at is null then
      act := 'restore_property';
    elsif old.status is distinct from new.status then
      act := 'update_status';
      details := jsonb_build_object('old_status', old.status, 'new_status', new.status);
    else
      act := 'update_property';
    end if;
    details := coalesce(details, '{}'::jsonb) || jsonb_build_object('ref', new.ref);

  elsif tg_op = 'DELETE' then
    act := 'delete_property_permanent';
    details := jsonb_build_object('ref', old.ref);
  end if;

  insert into public.activity_logs (actor_id, action, entity_type, entity_id, details)
  values (auth.uid(), act, 'property', coalesce(new.id, old.id), details);

  return coalesce(new, old);
end;
$function$;

-- Garde-fou des badges de confiance. La sécurité au niveau des lignes
-- autorise un collaborateur à modifier ses propres biens, toutes colonnes
-- confondues : elle ne sait pas restreindre une colonne. Sans ce déclencheur,
-- n'importe quel collaborateur pourrait s'attribuer le badge « vérifiée »,
-- qui ne vaudrait alors plus rien.
create or replace function public.enforce_verification_rights()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
begin
  if tg_op = 'INSERT' then
    if (new.verified_at is not null or new.verified_by is not null) and not is_admin() then
      raise exception 'Seul l''administrateur peut certifier une annonce.';
    end if;
  elsif tg_op = 'UPDATE' then
    if (new.verified_at is distinct from old.verified_at
        or new.verified_by is distinct from old.verified_by)
       and not is_admin() then
      raise exception 'Seul l''administrateur peut certifier une annonce.';
    end if;
  end if;

  -- L'auteur de la certification est déduit, jamais fourni par le client.
  if new.verified_at is not null and (tg_op = 'INSERT' or new.verified_at is distinct from old.verified_at) then
    new.verified_by := auth.uid();
  end if;
  if new.verified_at is null then
    new.verified_by := null;
  end if;

  return new;
end;
$function$;

-- Même garde-fou pour les agences : une agence qui se certifie elle-même
-- rendrait le badge sans valeur.
create or replace function public.enforce_agency_verification_rights()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
begin
  if tg_op = 'INSERT' then
    if (new.verified_at is not null or new.verified_by is not null) and not is_admin() then
      raise exception 'Seul l''administrateur peut certifier une agence.';
    end if;
  elsif tg_op = 'UPDATE' then
    if (new.verified_at is distinct from old.verified_at
        or new.verified_by is distinct from old.verified_by)
       and not is_admin() then
      raise exception 'Seul l''administrateur peut certifier une agence.';
    end if;
  end if;

  if new.verified_at is not null and (tg_op = 'INSERT' or new.verified_at is distinct from old.verified_at) then
    new.verified_by := auth.uid();
  end if;
  if new.verified_at is null then
    new.verified_by := null;
  end if;

  return new;
end;
$function$;

-- L'auteur et la date d'un réglage sont déduits, jamais fournis par le client.
create or replace function public.stamp_site_setting()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
begin
  new.updated_at := now();
  new.updated_by := auth.uid();
  return new;
end;
$function$;

-- Frein anti-abus des formulaires publics. Chaque insertion déclenchant un
-- email, une insertion anonyme illimitée permettait d'épuiser le quota
-- d'envoi et de priver d'emails les vrais prospects.
--
-- PIÈGE : dans une fonction SECURITY DEFINER, current_user vaut le
-- propriétaire (postgres), jamais l'appelant. Seul auth.role() distingue le
-- public d'une personne connectée. Une première version testait current_user
-- et ne bloquait donc rien.
create or replace function public.enforce_submission_rate_limit()
returns trigger
language plpgsql
security definer
set search_path to public, extensions
as $function$
declare
  entetes json;
  ip text;
  empreinte text;
  par_appareil int;
  au_total int;
  plafond_appareil int;
  plafond_global int := 200;
begin
  if coalesce(auth.role(), '') <> 'anon' then
    return new;
  end if;

  plafond_appareil := case tg_table_name when 'alert_subscriptions' then 3 else 5 end;

  entetes := nullif(current_setting('request.headers', true), '')::json;
  ip := coalesce(entetes ->> 'cf-connecting-ip',
                 entetes ->> 'sb-forwarded-for',
                 entetes ->> 'x-forwarded-for',
                 'inconnu');
  empreinte := encode(extensions.digest(ip || '::pab-immo-v1', 'sha256'), 'hex');

  select count(*) into par_appareil from public.submission_log
   where bucket = tg_table_name and client_hash = empreinte
     and created_at > now() - interval '1 hour';
  if par_appareil >= plafond_appareil then
    raise exception 'Vous avez déjà envoyé plusieurs demandes récemment. Merci de patienter une heure, ou de nous joindre directement par WhatsApp.'
      using errcode = 'check_violation';
  end if;

  select count(*) into au_total from public.submission_log
   where bucket = tg_table_name and created_at > now() - interval '1 hour';
  if au_total >= plafond_global then
    raise exception 'Le formulaire est momentanément indisponible. Merci de nous joindre par WhatsApp au +221 77 849 41 11.'
      using errcode = 'check_violation';
  end if;

  insert into public.submission_log (bucket, client_hash) values (tg_table_name, empreinte);
  delete from public.submission_log where created_at < now() - interval '2 hours';
  return new;
end;
$function$;

-- Prévient par email à chaque nouveau message, RDV ou inscription alerte.
-- Appelle la fonction Edge notify-lead (voir supabase/functions/).
create or replace function public.notify_lead_webhook()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
begin
  perform net.http_post(
    url := 'https://avanktgaxepzpqmsiauz.supabase.co/functions/v1/notify-lead',
    body := jsonb_build_object(
      'type', 'INSERT',
      'table', TG_TABLE_NAME,
      'schema', TG_TABLE_SCHEMA,
      'record', row_to_json(NEW),
      'old_record', null
    ),
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer sb_publishable_nAQnS82ru9h-beIDPKMqPA_JO_aSYc-'
    ),
    timeout_milliseconds := 5000
  );
  return new;
end;
$function$;

-- Prévient les inscrits aux alertes quand un bien devient visible.
-- Appelle la fonction Edge notify-alert-matches.
create or replace function public.notify_alert_matches()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  became_visible boolean;
begin
  became_visible := (
    NEW.is_published = true
    and NEW.status in ('Disponible', 'Réservé')
    and (
      TG_OP = 'INSERT'
      or (OLD.is_published is distinct from true)
      or (OLD.status not in ('Disponible', 'Réservé'))
    )
  );

  if became_visible then
    perform net.http_post(
      url := 'https://avanktgaxepzpqmsiauz.supabase.co/functions/v1/notify-alert-matches',
      body := row_to_json(NEW)::jsonb,
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer sb_publishable_nAQnS82ru9h-beIDPKMqPA_JO_aSYc-'
      ),
      timeout_milliseconds := 5000
    );
  end if;

  return new;
end;
$function$;


-- ----------------------------------------------------------------------------
-- 7. Déclencheurs
-- ----------------------------------------------------------------------------
create trigger trg_contact_messages_rate_limit    before insert on public.contact_messages    for each row execute function enforce_submission_rate_limit();
create trigger trg_appointments_rate_limit        before insert on public.appointments        for each row execute function enforce_submission_rate_limit();
create trigger trg_alert_subscriptions_rate_limit before insert on public.alert_subscriptions for each row execute function enforce_submission_rate_limit();
create trigger trg_site_settings_stamp           before insert or update on public.site_settings for each row execute function stamp_site_setting();
create trigger trg_collaborators_verification  before insert or update on public.collaborators for each row execute function enforce_agency_verification_rights();
create trigger trg_properties_verification      before insert or update on public.properties for each row execute function enforce_verification_rights();
create trigger trg_properties_updated_at        before update on public.properties            for each row execute function set_updated_at();
create trigger trg_properties_status_history    after update  on public.properties            for each row execute function log_status_change();
create trigger trg_properties_activity          after insert or update or delete on public.properties for each row execute function log_property_activity();
create trigger notify_alert_matches_trigger     after insert or update on public.properties   for each row execute function notify_alert_matches();
create trigger notify_lead_on_contact_message   after insert  on public.contact_messages      for each row execute function notify_lead_webhook();
create trigger notify_lead_on_appointment       after insert  on public.appointments          for each row execute function notify_lead_webhook();
create trigger notify_lead_on_alert_subscription after insert on public.alert_subscriptions   for each row execute function notify_lead_webhook();


-- ----------------------------------------------------------------------------
-- 8. Index
-- ----------------------------------------------------------------------------
create index properties_owner_idx            on public.properties using btree (owner_id);
create index properties_status_idx           on public.properties using btree (status);
create index properties_type_idx             on public.properties using btree (type);
create index properties_archived_idx         on public.properties using btree (archived_at);
create index properties_verified_idx         on public.properties using btree (verified_at);
create index properties_location_idx         on public.properties using gist (location);
create index property_photos_property_idx    on public.property_photos using btree (property_id);
create index property_views_property_idx     on public.property_views using btree (property_id);
create index property_views_created_idx      on public.property_views using btree (created_at desc);
create index favorite_events_property_idx    on public.favorite_events using btree (property_id);
create index favorite_events_created_idx     on public.favorite_events using btree (created_at desc);
create index contact_messages_created_idx    on public.contact_messages using btree (created_at desc);
create index appointments_created_idx        on public.appointments using btree (created_at desc);
create index alert_subscriptions_created_idx on public.alert_subscriptions using btree (created_at desc);
create index site_visits_session_idx         on public.site_visits using btree (session_id);
create index site_visits_created_idx         on public.site_visits using btree (created_at desc);
create index activity_logs_actor_idx         on public.activity_logs using btree (actor_id);
create index activity_logs_created_idx       on public.activity_logs using btree (created_at desc);
create index submission_log_lookup_idx       on public.submission_log (bucket, client_hash, created_at desc);


-- ----------------------------------------------------------------------------
-- 9. Sécurité au niveau des lignes (RLS)
-- ----------------------------------------------------------------------------
-- Principe : le public peut écrire (message, RDV, alerte, statistique de
-- consultation) mais ne peut rien relire. La lecture est réservée au
-- propriétaire du bien concerné, ou à l'admin.

alter table public.properties             enable row level security;
alter table public.property_photos        enable row level security;
alter table public.property_status_history enable row level security;
alter table public.property_views         enable row level security;
alter table public.favorite_events        enable row level security;
alter table public.contact_messages       enable row level security;
alter table public.appointments           enable row level security;
alter table public.alert_subscriptions    enable row level security;
alter table public.collaborators          enable row level security;
alter table public.site_visits            enable row level security;
alter table public.activity_logs          enable row level security;
alter table public.site_settings          enable row level security;
alter table public.submission_log         enable row level security;

-- Biens et photos : propriétaire ou admin, en lecture comme en écriture.
create policy "Acces biens : proprietaire ou admin" on public.properties
  for all to public
  using (owner_id = auth.uid() or is_admin())
  with check (owner_id = auth.uid() or is_admin());

create policy "Acces photos : proprietaire ou admin" on public.property_photos
  for all to public
  using (is_admin() or exists (select 1 from properties p where p.id = property_photos.property_id and p.owner_id = auth.uid()))
  with check (is_admin() or exists (select 1 from properties p where p.id = property_photos.property_id and p.owner_id = auth.uid()));

create policy "Acces historique : proprietaire ou admin" on public.property_status_history
  for select to public
  using (is_admin() or exists (select 1 from properties p where p.id = property_status_history.property_id and p.owner_id = auth.uid()));

-- Mesures d'audience : tout le monde écrit, seul le propriétaire (ou l'admin) lit.
create policy "Tout le monde peut enregistrer une consultation" on public.property_views
  for insert to anon, authenticated with check (true);
create policy "Consultations visibles par proprietaire ou admin" on public.property_views
  for select to public
  using (is_admin() or exists (select 1 from properties p where p.id = property_views.property_id and p.owner_id = auth.uid()));

create policy "Tout le monde peut enregistrer un favori" on public.favorite_events
  for insert to anon, authenticated with check (true);
create policy "Favoris visibles par proprietaire ou admin" on public.favorite_events
  for select to public
  using (is_admin() or exists (select 1 from properties p where p.id = favorite_events.property_id and p.owner_id = auth.uid()));

create policy "Tout le monde peut enregistrer une visite" on public.site_visits
  for insert to anon, authenticated with check (true);
create policy "Visites reservees a l'admin" on public.site_visits
  for select to public using (is_admin());

-- Prospects : le public dépose et ne relit jamais. L'admin voit tout ;
-- un collaborateur voit les demandes portant sur ses propres biens, en
-- lecture seule (la modification et la suppression restent à l'admin).
create policy "Tout le monde peut envoyer un message" on public.contact_messages
  for insert to anon, authenticated with check (true);
create policy "Messages reserves a l'admin" on public.contact_messages
  for select to public using (is_admin());
create policy "Messages visibles par le proprietaire du bien" on public.contact_messages
  for select to public
  using (exists (select 1 from properties p where p.id = contact_messages.property_id and p.owner_id = auth.uid()));
create policy "Maj messages reservee a l'admin" on public.contact_messages
  for update to public using (is_admin()) with check (is_admin());
create policy "Suppression messages reservee a l'admin" on public.contact_messages
  for delete to public using (is_admin());

create policy "Tout le monde peut demander un RDV" on public.appointments
  for insert to anon, authenticated with check (true);
create policy "RDV reserves a l'admin" on public.appointments
  for select to public using (is_admin());
create policy "RDV visibles par le proprietaire du bien" on public.appointments
  for select to public
  using (exists (select 1 from properties p where p.id = appointments.property_id and p.owner_id = auth.uid()));
create policy "Maj RDV reservee a l'admin" on public.appointments
  for update to public using (is_admin()) with check (is_admin());
create policy "Suppression RDV reservee a l'admin" on public.appointments
  for delete to public using (is_admin());

create policy "Tout le monde peut s'inscrire aux alertes" on public.alert_subscriptions
  for insert to anon, authenticated with check (true);
create policy "Alertes reservees a l'admin" on public.alert_subscriptions
  for select to public using (is_admin());
create policy "Suppression alertes reservee a l'admin" on public.alert_subscriptions
  for delete to public using (is_admin());

create policy "Collaborateurs visibles par l'admin" on public.collaborators
  for select to public using (is_admin());
-- La vitrine doit reconnaître qu'un compte connecté est un collaborateur pour
-- lui proposer le retour vers son espace. Strictement limité à SA ligne.
create policy "Un collaborateur lit sa propre fiche" on public.collaborators
  for select to authenticated using (user_id = auth.uid());
create policy "Admin gere les collaborateurs" on public.collaborators
  for all to public using (is_admin()) with check (is_admin());

create policy "Journal reserve a l'admin" on public.activity_logs
  for select to public using (is_admin());

-- Réglages entièrement privés : la lecture publique passe par public_stats,
-- qui n'expose que les clés délibérément choisies.
create policy "Reglages reserves a l'admin" on public.site_settings
  for all to public using (is_admin()) with check (is_admin());

create policy "Journal anti-abus reserve a l'admin" on public.submission_log
  for select to public using (is_admin());


-- ----------------------------------------------------------------------------
-- 10. Règles du bucket de stockage
-- ----------------------------------------------------------------------------
-- Ces règles vivent dans le schéma `storage`, pas dans `public` : elles
-- échappaient donc à cette sauvegarde. Sans elles, une base restaurée ne
-- pourrait ni recevoir ni supprimer une photo.
--
-- Le bucket property-photos doit exister et être PUBLIC : c'est ce qui permet
-- de servir les images par URL directe, sans authentification. Le créer depuis
-- la console (Storage → New bucket → Public), puis jouer ce qui suit.
--
-- Noter qu'aucune règle de lecture publique n'est nécessaire : un bucket
-- public sert ses objets sans passer par la sécurité au niveau des lignes.
-- En ajouter une rendrait le dossier ÉNUMÉRABLE par n'importe qui — c'était
-- le cas jusqu'au 21/07/2026.

create policy "Upload photos : proprietaire ou admin"
  on storage.objects for insert to authenticated
  with check (
    bucket_id = 'property-photos'
    and (is_admin() or exists (
      select 1 from public.properties p
       where p.id::text = (storage.foldername(objects.name))[1]
         and p.owner_id = auth.uid()))
  );

create policy "Suppression photos : proprietaire ou admin"
  on storage.objects for delete to authenticated
  using (
    bucket_id = 'property-photos'
    and (is_admin() or exists (
      select 1 from public.properties p
       where p.id::text = (storage.foldername(objects.name))[1]
         and p.owner_id = auth.uid()))
  );

create policy "Listing photos : proprietaire ou admin"
  on storage.objects for select to authenticated
  using (
    bucket_id = 'property-photos'
    and (is_admin() or exists (
      select 1 from public.properties p
       where p.id::text = (storage.foldername(objects.name))[1]
         and p.owner_id = auth.uid()))
  );


-- ----------------------------------------------------------------------------
-- 11. Ce que ce fichier ne couvre PAS
-- ----------------------------------------------------------------------------
-- · Les données (voir docs/SAUVEGARDES.md, elles ne vont jamais dans le dépôt)
-- · Les comptes auth.users et leurs mots de passe
-- · Le contenu du bucket de stockage property-photos (les fichiers image)
-- · La création du bucket lui-même, à faire depuis la console en mode public
-- · Les secrets des fonctions Edge (RESEND_API_KEY, NOTIFY_EMAIL, …)
-- · La configuration du projet Supabase (URL, clés, fournisseurs d'auth)
