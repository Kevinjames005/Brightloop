-- =============================================================================
-- Brightloop Subscription Management Platform
-- 001 - Users module
-- Run this in the Supabase Dashboard -> SQL Editor (or `supabase db push`).
-- Idempotent: safe to run more than once.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Role enum
-- ---------------------------------------------------------------------------
do $$
begin
    create type public.user_role as enum ('admin', 'staff', 'customer');
exception
    when duplicate_object then null;
end
$$;

-- ---------------------------------------------------------------------------
-- 2. Users table
-- ---------------------------------------------------------------------------
create table if not exists public.users (
    id              uuid primary key default gen_random_uuid(),
    email           text        not null,
    password_hash   text        not null,
    name            text        not null,
    role            public.user_role not null default 'customer',
    is_active       boolean     not null default true,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    constraint users_email_lowercase_chk check (email = lower(email)),
    constraint users_email_format_chk    check (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    constraint users_name_not_blank_chk  check (length(btrim(name)) > 0)
);

-- Case-insensitive uniqueness (emails are normalised to lowercase by the API).
create unique index if not exists users_email_key on public.users (email);

-- Supports admin/staff listing and dashboard filters.
create index if not exists users_role_idx on public.users (role);

comment on table  public.users is
    'Platform accounts. Passwords are bcrypt hashes; never store plaintext.';
comment on column public.users.password_hash is
    'bcrypt digest produced by passlib. Never expose through the API.';

-- ---------------------------------------------------------------------------
-- 3. Keep updated_at fresh
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists users_set_updated_at on public.users;
create trigger users_set_updated_at
    before update on public.users
    for each row
    execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. Lock the table down
--    The API talks to Postgres with the service_role key, which bypasses RLS.
--    Enabling RLS with no policies means anon/authenticated clients (e.g. a
--    browser using the Supabase JS SDK) can never read password hashes.
-- ---------------------------------------------------------------------------
alter table public.users enable row level security;

-- Supabase always defines anon/authenticated; the guard keeps this script
-- runnable on a plain PostgreSQL instance too.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all on table public.users from anon;
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all on table public.users from authenticated;
    end if;
end
$$;

-- ---------------------------------------------------------------------------
-- 5. Bootstrap the first administrator
--    Register through POST /api/v1/users/register (role defaults to
--    'customer'), then promote the account:
--
--    update public.users set role = 'admin' where email = 'you@company.com';
-- ---------------------------------------------------------------------------
