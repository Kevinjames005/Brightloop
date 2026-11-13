-- =============================================================================
-- Brightloop Subscription Management Platform
-- 002 - Session invalidation support
-- Run after 001_users.sql. Idempotent.
-- =============================================================================

-- Bumped whenever credentials change (e.g. password change). Each access token
-- embeds the version it was issued with; a mismatch revokes the token.
alter table public.users
    add column if not exists token_version integer not null default 0;

comment on column public.users.token_version is
    'Incremented on credential changes to revoke previously issued access tokens.';

-- Make PostgREST pick up the new column immediately.
notify pgrst, 'reload schema';
