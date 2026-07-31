-- ============================================================================
-- Fiche agence : ce qu'il faut pour gérer une agence, pas seulement un compte
-- ============================================================================
-- La table `collaborators` ne portait que le nom affiché et la certification.
-- Une agence partenaire, c'est aussi un interlocuteur, un téléphone, une zone
-- d'intervention — des informations que l'admin devait jusqu'ici garder de
-- tête ou dans un carnet à part.
--
-- Le nom de la table ne change pas (« collaborateur » reste le vocabulaire du
-- code et des politiques RLS existantes) : seules les FONCTIONNALITÉS
-- deviennent celles d'une agence. Renommer la table aurait cassé les
-- politiques, les clés étrangères et les deux pages, sans rien apporter.
--
-- Idempotent : rejouable sans erreur sur une base déjà migrée.

alter table public.collaborators
  add column if not exists contact_name text,
  add column if not exists phone        text,
  add column if not exists email        text,
  add column if not exists zone         text,
  add column if not exists notes        text,
  -- Trace de l'invitation : qui a ouvert le compte, et quand. Sans cela,
  -- impossible de distinguer une agence invitée d'une agence créée à la main
  -- directement dans Supabase.
  add column if not exists invited_at   timestamptz,
  add column if not exists invited_by   uuid references auth.users(id) on delete set null;

comment on column public.collaborators.contact_name is
  'Personne à joindre dans l''agence (le nom affiché reste celui de l''agence).';
comment on column public.collaborators.zone is
  'Zone d''intervention déclarée, ex. « Dakar, Thiès ». Informatif : ne filtre rien.';
comment on column public.collaborators.invited_at is
  'Date d''envoi de l''invitation par l''admin, via la fonction inviter-agence.';


-- ----------------------------------------------------------------------------
-- Vue d'appoint : l'admin doit voir si l'agence a activé son compte
-- ----------------------------------------------------------------------------
-- Une invitation envoyée n'est pas une invitation acceptée. Sans cette
-- information, l'admin ne peut pas savoir s'il doit relancer une agence qui
-- n'a jamais choisi son mot de passe.
--
-- PIÈGE ÉVITÉ ICI : une vue PostgreSQL s'exécute par défaut avec les droits de
-- son PROPRIÉTAIRE, pas de celui qui l'interroge (security_invoker = false).
-- Elle contourne donc la RLS de `collaborators`. Sans le filtre ci-dessous,
-- n'importe quelle agence connectée pourrait lire le téléphone et l'email de
-- TOUTES les autres — exactement la fuite que les politiques existantes
-- empêchent. Le `where` rejoue donc explicitement la règle : l'admin voit
-- tout, une agence ne voit qu'elle-même.
create or replace view public.collaborators_etat as
  select
    c.user_id,
    c.display_name,
    c.contact_name,
    c.phone,
    c.email,
    c.zone,
    c.notes,
    c.verified_at,
    c.invited_at,
    c.created_at,
    u.last_sign_in_at,
    (u.last_sign_in_at is not null) as compte_active
  from public.collaborators c
  join auth.users u on u.id = c.user_id
  where public.is_admin() or c.user_id = auth.uid();

revoke all on public.collaborators_etat from anon;
grant select on public.collaborators_etat to authenticated;
