-- =============================================================================
-- Brightloop Subscription Management Platform
-- 004 - Store plan prices in whole rupees (replaces paise)
-- Run after 003_catalog.sql. Idempotent.
--
-- Existing price_paise values are converted to the nearest rupee (half up).
-- Example: 269900 paise -> 2699 rupees.
--
-- WARNING: whole-rupee storage cannot represent sub-rupee prices (e.g. ₹99.50)
-- and reduces precision for tax/discount arithmetic. Rounding must be defined
-- by the billing engine for every calculation.
-- =============================================================================

do $$
begin
    -- Only convert when the old column still exists and the new one does not,
    -- so re-running this migration is safe.
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'plans'
          and column_name = 'price_paise'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'plans'
          and column_name = 'price_inr'
    ) then
        alter table public.plans rename column price_paise to price_inr;

        -- 269900 paise = 2699.00 INR -> 2699 INR
        update public.plans
           set price_inr = round(price_inr::numeric / 100)::bigint;
    end if;
end
$$;

-- Replace the old (paise) bounds with rupee bounds.
alter table public.plans drop constraint if exists plans_price_paise_non_negative_chk;
alter table public.plans drop constraint if exists plans_price_paise_max_chk;
alter table public.plans drop constraint if exists plans_price_inr_non_negative_chk;
alter table public.plans drop constraint if exists plans_price_inr_max_chk;

alter table public.plans
    add constraint plans_price_inr_non_negative_chk check (price_inr >= 0),
    -- 10^13 rupees = ₹10 trillion, matching the old 10^15 paise ceiling.
    add constraint plans_price_inr_max_chk check (price_inr <= 10000000000000);

comment on column public.plans.price_inr is
    'Price in whole rupees (integer). Sub-rupee amounts are not supported.';

do $$
begin
    if exists (
        select 1 from pg_class
        where relname = 'plans_price_idx' and relkind = 'i'
    ) then
        alter index public.plans_price_idx rename to plans_price_inr_idx;
    end if;
end
$$;

notify pgrst, 'reload schema';
