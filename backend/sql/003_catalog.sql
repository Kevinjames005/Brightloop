-- =============================================================================
-- Brightloop Subscription Management Platform
-- 003 - Catalog & Pricing (products -> variants -> plans)
-- Run after 002_user_auth.sql. Idempotent.
--
-- Money rule: every amount is a whole number of paise, stored as bigint.
-- No numeric/float columns exist for money anywhere in this schema.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Billing interval enum
-- ---------------------------------------------------------------------------
do $$
begin
    create type public.billing_interval as enum ('day', 'week', 'month', 'year');
exception
    when duplicate_object then null;
end
$$;

-- ---------------------------------------------------------------------------
-- 2. Products
-- ---------------------------------------------------------------------------
create table if not exists public.products (
    id          uuid        primary key default gen_random_uuid(),
    sku         text        not null,
    name        text        not null,
    description text,
    is_active   boolean     not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    constraint products_sku_format_chk
        check (sku ~ '^[A-Z0-9][A-Z0-9_-]{1,31}$'),
    constraint products_name_not_blank_chk
        check (length(btrim(name)) > 0),
    constraint products_description_len_chk
        check (description is null or length(description) <= 2000)
);

create unique index if not exists products_sku_key on public.products (sku);
create index if not exists products_active_idx on public.products (is_active);

comment on table public.products is
    'Catalog products. Deactivated (never hard-deleted) while history exists.';

-- ---------------------------------------------------------------------------
-- 3. Product variants
-- ---------------------------------------------------------------------------
create table if not exists public.product_variants (
    id          uuid        primary key default gen_random_uuid(),
    product_id  uuid        not null,
    sku         text        not null,
    name        text        not null,
    description text,
    is_active   boolean     not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    constraint product_variants_product_fk
        foreign key (product_id) references public.products (id)
        on update cascade on delete restrict,
    constraint product_variants_sku_format_chk
        check (sku ~ '^[A-Z0-9][A-Z0-9_-]{1,31}$'),
    constraint product_variants_name_not_blank_chk
        check (length(btrim(name)) > 0),
    constraint product_variants_description_len_chk
        check (description is null or length(description) <= 2000)
);

create unique index if not exists product_variants_sku_key
    on public.product_variants (sku);
create unique index if not exists product_variants_product_name_key
    on public.product_variants (product_id, lower(name));
create index if not exists product_variants_product_idx
    on public.product_variants (product_id);
create index if not exists product_variants_active_idx
    on public.product_variants (is_active);

-- ---------------------------------------------------------------------------
-- 4. Plans (pricing)
-- ---------------------------------------------------------------------------
create table if not exists public.plans (
    id               uuid        primary key default gen_random_uuid(),
    variant_id       uuid        not null,
    name             text        not null,
    billing_interval public.billing_interval not null default 'month',
    interval_count   smallint    not null default 1,
    price_paise      bigint      not null,
    currency         char(3)     not null default 'INR',
    trial_days       smallint    not null default 0,
    is_active        boolean     not null default true,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),

    constraint plans_variant_fk
        foreign key (variant_id) references public.product_variants (id)
        on update cascade on delete restrict,
    constraint plans_name_not_blank_chk
        check (length(btrim(name)) > 0),
    -- Money rules: integer paise only, never negative, sane upper bound.
    constraint plans_price_paise_non_negative_chk
        check (price_paise >= 0),
    constraint plans_price_paise_max_chk
        check (price_paise <= 1000000000000000),
    constraint plans_interval_count_chk
        check (interval_count between 1 and 36),
    constraint plans_trial_days_chk
        check (trial_days between 0 and 365),
    constraint plans_currency_inr_chk
        check (currency = 'INR')
);

create unique index if not exists plans_variant_name_key
    on public.plans (variant_id, lower(name));
create index if not exists plans_variant_idx on public.plans (variant_id);
create index if not exists plans_active_idx on public.plans (is_active);
create index if not exists plans_price_idx on public.plans (price_paise);

comment on table public.plans is
    'Sellable plans. price_paise is bigint paise (₹1 = 100 paise); no floats.';
comment on column public.plans.price_paise is
    'Price in whole paise. Existing subscriptions must snapshot this value.';

-- ---------------------------------------------------------------------------
-- 5. Keep updated_at fresh (function created by 001_users.sql)
-- ---------------------------------------------------------------------------
drop trigger if exists products_set_updated_at on public.products;
create trigger products_set_updated_at
    before update on public.products
    for each row execute function public.set_updated_at();

drop trigger if exists product_variants_set_updated_at on public.product_variants;
create trigger product_variants_set_updated_at
    before update on public.product_variants
    for each row execute function public.set_updated_at();

drop trigger if exists plans_set_updated_at on public.plans;
create trigger plans_set_updated_at
    before update on public.plans
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. Lock down (the API uses service_role, which bypasses RLS)
-- ---------------------------------------------------------------------------
alter table public.products enable row level security;
alter table public.product_variants enable row level security;
alter table public.plans enable row level security;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all on table public.products from anon;
        revoke all on table public.product_variants from anon;
        revoke all on table public.plans from anon;
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all on table public.products from authenticated;
        revoke all on table public.product_variants from authenticated;
        revoke all on table public.plans from authenticated;
    end if;
end
$$;

notify pgrst, 'reload schema';
