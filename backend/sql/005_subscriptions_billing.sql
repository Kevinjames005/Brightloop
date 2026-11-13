-- =============================================================================
-- Brightloop Subscription Management Platform
-- 005 - Subscriptions, Quotations, Billing, Invoices, Payments, Taxes, Discounts
-- Run after 004_money_to_rupees.sql. Idempotent.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Extend products, product_variants, and plans
-- ---------------------------------------------------------------------------
alter table public.products
    add column if not exists product_type text not null default 'software',
    add column if not exists sales_price bigint not null default 0,
    add column if not exists cost_price bigint not null default 0,
    add column if not exists notes text;

alter table public.product_variants
    add column if not exists attribute_name text default 'Brand',
    add column if not exists attribute_value text default 'Standard',
    add column if not exists price_extra bigint not null default 0;

alter table public.plans
    add column if not exists min_quantity integer not null default 1,
    add column if not exists start_date date,
    add column if not exists end_date date,
    add column if not exists auto_close boolean not null default false,
    add column if not exists allow_early_close boolean not null default true,
    add column if not exists allow_pause boolean not null default true,
    add column if not exists allow_renewal boolean not null default true;

-- ---------------------------------------------------------------------------
-- 2. Taxes
-- ---------------------------------------------------------------------------
create table if not exists public.taxes (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    rate        numeric not null default 0,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists taxes_active_idx on public.taxes (is_active);

-- ---------------------------------------------------------------------------
-- 3. Discounts
-- ---------------------------------------------------------------------------
create table if not exists public.discounts (
    id                  uuid primary key default gen_random_uuid(),
    code                text not null,
    description         text,
    discount_type       text not null default 'percentage',
    discount_value      numeric not null default 0,
    min_purchase_amount bigint not null default 0,
    min_quantity        integer not null default 0,
    start_date          timestamptz,
    end_date            timestamptz,
    max_uses            integer,
    used_count          integer not null default 0,
    applies_to          text not null default 'whole_subscription',
    product_id          uuid references public.products(id) on delete set null,
    is_active           boolean not null default true,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint discounts_code_key unique (code),
    constraint discounts_type_chk check (discount_type in ('percentage', 'fixed')),
    constraint discounts_applies_to_chk check (applies_to in ('whole_subscription', 'product'))
);

create index if not exists discounts_code_idx on public.discounts (code);
create index if not exists discounts_active_idx on public.discounts (is_active);

-- ---------------------------------------------------------------------------
-- 4. Quotation Templates
-- ---------------------------------------------------------------------------
create table if not exists public.quotation_templates (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    description text,
    plan_id     uuid references public.plans(id) on delete set null,
    valid_days  integer not null default 30,
    lines       jsonb not null default '[]'::jsonb,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 5. Subscriptions & Subscription Lines
-- ---------------------------------------------------------------------------
create table if not exists public.subscriptions (
    id                  uuid primary key default gen_random_uuid(),
    subscription_number text not null unique,
    customer_id         uuid not null references public.users(id) on delete restrict,
    plan_id             uuid not null references public.plans(id) on delete restrict,
    status              text not null default 'draft',
    start_date          date not null default current_date,
    expiry_date         date,
    payment_terms       text not null default 'immediate',
    next_billing_date   date,
    last_billed_date    date,
    auto_close          boolean not null default false,
    discount_id         uuid references public.discounts(id) on delete set null,
    notes               text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint subscriptions_status_chk check (status in ('draft', 'quotation', 'confirmed', 'active', 'paused', 'closed'))
);

create index if not exists subscriptions_customer_idx on public.subscriptions (customer_id);
create index if not exists subscriptions_status_idx on public.subscriptions (status);
create index if not exists subscriptions_billing_date_idx on public.subscriptions (next_billing_date);

create table if not exists public.subscription_lines (
    id              uuid primary key default gen_random_uuid(),
    subscription_id uuid not null references public.subscriptions(id) on delete cascade,
    product_id      uuid not null references public.products(id) on delete restrict,
    variant_id      uuid references public.product_variants(id) on delete set null,
    quantity        integer not null default 1,
    unit_price      bigint not null default 0,
    tax_id          uuid references public.taxes(id) on delete set null,
    tax_rate        numeric not null default 0,
    amount          bigint not null default 0,
    created_at      timestamptz not null default now()
);

create index if not exists sub_lines_subscription_idx on public.subscription_lines (subscription_id);

-- ---------------------------------------------------------------------------
-- 6. Invoices & Invoice Lines
-- ---------------------------------------------------------------------------
create table if not exists public.invoices (
    id                   uuid primary key default gen_random_uuid(),
    invoice_number       text not null unique,
    subscription_id      uuid references public.subscriptions(id) on delete set null,
    customer_id          uuid not null references public.users(id) on delete restrict,
    status               text not null default 'draft',
    subtotal             bigint not null default 0,
    tax_total            bigint not null default 0,
    discount_total       bigint not null default 0,
    total_amount         bigint not null default 0,
    amount_paid          bigint not null default 0,
    billing_period_start date,
    billing_period_end   date,
    issue_date           date not null default current_date,
    due_date             date not null default current_date,
    sent_at              timestamptz,
    notes                text,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),

    constraint invoices_status_chk check (status in ('draft', 'confirmed', 'paid', 'cancelled'))
);

create index if not exists invoices_customer_idx on public.invoices (customer_id);
create index if not exists invoices_subscription_idx on public.invoices (subscription_id);
create index if not exists invoices_status_idx on public.invoices (status);
create index if not exists invoices_due_date_idx on public.invoices (due_date);

create table if not exists public.invoice_lines (
    id              uuid primary key default gen_random_uuid(),
    invoice_id      uuid not null references public.invoices(id) on delete cascade,
    product_id      uuid references public.products(id) on delete set null,
    description     text not null,
    quantity        integer not null default 1,
    unit_price      bigint not null default 0,
    tax_rate        numeric not null default 0,
    tax_amount      bigint not null default 0,
    discount_amount bigint not null default 0,
    total_amount    bigint not null default 0,
    created_at      timestamptz not null default now()
);

create index if not exists inv_lines_invoice_idx on public.invoice_lines (invoice_id);

-- ---------------------------------------------------------------------------
-- 7. Payments
-- ---------------------------------------------------------------------------
create table if not exists public.payments (
    id             uuid primary key default gen_random_uuid(),
    payment_number text not null unique,
    invoice_id     uuid not null references public.invoices(id) on delete restrict,
    amount         bigint not null default 0,
    payment_method text not null default 'bank_transfer',
    payment_date   date not null default current_date,
    note           text,
    created_at     timestamptz not null default now()
);

create index if not exists payments_invoice_idx on public.payments (invoice_id);
create index if not exists payments_date_idx on public.payments (payment_date);

-- ---------------------------------------------------------------------------
-- 8. Password Resets
-- ---------------------------------------------------------------------------
create table if not exists public.password_resets (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references public.users(id) on delete cascade,
    token      text not null unique,
    expires_at timestamptz not null,
    used       boolean not null default false,
    created_at timestamptz not null default now()
);

-- Notify PostgREST to reload schema
notify pgrst, 'reload schema';
