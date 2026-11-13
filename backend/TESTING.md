# Brightloop backend — manual test plan

**Scope:** Users & Identity, Auth, and Catalog & Pricing. Subscriptions, billing,
invoices and payments are exercised through the web app and Swagger (`/docs`).

- API prefix: `/api/v1`
- Swagger: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>
- Test data is prefixed `TEST-` / `test.` so cleanup is safe.
- Run every SQL block in the Supabase SQL Editor as a **complete block**.

---

## 0. One-time setup

### 0.1 Run the migrations

In order, each file as a whole:

1. `backend/sql/003_catalog.sql`
2. `backend/sql/004_money_to_rupees.sql`

Verify:

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('products', 'product_variants', 'plans')
order by table_name;
```

Expected: 3 rows.

```sql
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'plans'
  and column_name like 'price%';
```

Expected exactly: `price_inr | bigint`. There must be **no** `price_paise`.

### 0.2 Start the API

```powershell
cd C:\CODING\KattakadaMohanan\backend
.\venv\Scripts\uvicorn app.main:app --reload
```

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json
```

Expected: `status=ok`, `supabase_configured=true`, `auth_configured=true`.
If `auth_configured=false`, `JWT_SECRET` is missing or shorter than 32 chars.

### 0.3 Make your existing user an admin for write tests

```sql
update public.users
set role = 'admin'
where email = 'arjun@brightloop.in';

select email, role, is_active, token_version
from public.users
order by created_at;
```

Your existing token picks up the new role on the next request, but re-login is
fine. **At the end of testing, demote yourself back to `customer`.**

### 0.4 Authorise in Swagger

1. Open `/docs`.
2. Click **Authorize**.
3. `username` = your email, `password` = your existing password.
4. Leave client id/secret blank, click **Authorize**.

This uses `POST /auth/token` (form login). `POST /auth/login` is the JSON
variant used by apps.

### 0.5 Create test accounts and catalog data

Run this in PowerShell. Replace the admin password with your local one.

```powershell
$base = "http://127.0.0.1:8000/api/v1"
$adminPassword = "YOUR-EXISTING-PASSWORD"

$login = Invoke-RestMethod "$base/auth/login" -Method Post -ContentType "application/json" `
  -Body (@{ email = "arjun@brightloop.in"; password = $adminPassword } | ConvertTo-Json)
$H = @{ Authorization = "Bearer $($login.access_token)" }

# Customers (register is public; role defaults to customer)
$cust = Invoke-RestMethod "$base/users/register" -Method Post -ContentType "application/json" `
  -Body (@{ email = "test.customer@brightloop.in"; password = "Test@2026"; name = "Test Customer" } | ConvertTo-Json)

$staff = Invoke-RestMethod "$base/users/register" -Method Post -ContentType "application/json" `
  -Body (@{ email = "test.staff@brightloop.in"; password = "Test@2026"; name = "Test Staff" } | ConvertTo-Json)

# Promote the staff account
Invoke-RestMethod "$base/users/$($staff.id)/role" -Method Patch -Headers $H -ContentType "application/json" `
  -Body (@{ role = "staff" } | ConvertTo-Json) | Out-Null

# Products
$P1 = Invoke-RestMethod "$base/products" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ sku = "TEST-CRM"; name = "Test CRM"; description = "CRM suite" } | ConvertTo-Json)
$P2 = Invoke-RestMethod "$base/products" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ sku = "TEST-HR"; name = "Test HR" } | ConvertTo-Json)
$P3 = Invoke-RestMethod "$base/products" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ sku = "TEST-PAY"; name = "Test Pay" } | ConvertTo-Json)

# Variants
$V1 = Invoke-RestMethod "$base/variants" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ product_id = $P1.id; sku = "TEST-CRM-STD"; name = "Standard"; description = "Up to 25 seats" } | ConvertTo-Json)
$V2 = Invoke-RestMethod "$base/variants" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ product_id = $P1.id; sku = "TEST-CRM-PRO"; name = "Pro" } | ConvertTo-Json)
$V3 = Invoke-RestMethod "$base/variants" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ product_id = $P2.id; sku = "TEST-HR-STD"; name = "Standard" } | ConvertTo-Json)

# Plans (integer rupees)
$PL1 = Invoke-RestMethod "$base/plans" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ variant_id = $V1.id; name = "TEST Standard Monthly"; billing_interval = "month"; interval_count = 1; price_inr = 999 } | ConvertTo-Json)
$PL2 = Invoke-RestMethod "$base/plans" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ variant_id = $V1.id; name = "TEST Standard Quarterly"; billing_interval = "month"; interval_count = 3; price_inr = 2699; trial_days = 14 } | ConvertTo-Json)
$PL3 = Invoke-RestMethod "$base/plans" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ variant_id = $V1.id; name = "TEST Standard Annual"; billing_interval = "year"; interval_count = 1; price_inr = 9999 } | ConvertTo-Json)
$PL4 = Invoke-RestMethod "$base/plans" -Method Post -Headers $H -ContentType "application/json" `
  -Body (@{ variant_id = $V2.id; name = "TEST Pro Monthly"; billing_interval = "month"; price_inr = 1999 } | ConvertTo-Json)

"USER customer = $($cust.id)"
"USER staff    = $($staff.id)"
"PRODUCT P1    = $($P1.id)"
"PRODUCT P2    = $($P2.id)"
"PRODUCT P3    = $($P3.id)"
"VARIANT V1    = $($V1.id)"
"VARIANT V2    = $($V2.id)"
"VARIANT V3    = $($V3.id)"
"PLAN PL1      = $($PL1.id)"
"PLAN PL2      = $($PL2.id)"
"PLAN PL3      = $($PL3.id)"
"PLAN PL4      = $($PL4.id)"
```

If any request fails with `409`, cleanup from section 5 and rerun.

Log in as the two test users and keep their tokens:

```powershell
$custToken = (Invoke-RestMethod "$base/auth/login" -Method Post -ContentType "application/json" `
  -Body (@{ email = "test.customer@brightloop.in"; password = "Test@2026" } | ConvertTo-Json)).access_token
$CH = @{ Authorization = "Bearer $custToken" }

$staffToken = (Invoke-RestMethod "$base/auth/login" -Method Post -ContentType "application/json" `
  -Body (@{ email = "test.staff@brightloop.in"; password = "Test@2026" } | ConvertTo-Json)).access_token
$SH = @{ Authorization = "Bearer $staffToken" }
```

### 0.6 Automated live smoke test (optional)

`scripts/live_smoke.ps1` drives the real API with the admin account. It creates
its own `SMOKE-<suffix>` data (including `smoke.<suffix>.*@brightloop.in` users),
checks the happy path plus key RBAC/validation guards, and hard-deletes the data
at the end through `scripts/cleanup_smoke.py`.

Prerequisites:

- Migrations `003` and `004` have been run.
- The API is running and the account in `-AdminEmail` has the `admin` role.
- You are in `C:\CODING\KattakadaMohanan\backend`.

Start with a no-write preflight:

```powershell
.\scripts\live_smoke.ps1 -PreflightOnly
```

It checks `/health`, admin login and the catalog tables, and creates nothing.
If it reports `role 'customer'`, run the promotion in section 0.3 first.

Run the full smoke test (you will be prompted for the admin password):

```powershell
.\scripts\live_smoke.ps1
```

Useful options:

```powershell
# Keep the generated rows for inspection; prints cleanup SQL
.\scripts\live_smoke.ps1 -KeepData -Suffix 20261031A

# Remove rows left by an earlier run
.\scripts\live_smoke.ps1 -CleanupOnly -Suffix 20261031A
```

The suffix is printed at the start and end. If automatic cleanup fails, the
script prints the SQL to run in the Supabase SQL Editor. The smoke test exercises
the main flow; it does not replace the manual checks in sections 1-3.

---

## 1. Auth & Users

### 1.1 Registration validation

`POST /users/register`

| Body `password` | Expected |
|---|---|
| `Ab@1` | `422` — longer than 8 characters |
| `abcdefgh!` | `422` — needs an uppercase letter |
| `ABCDEFGH!` | `422` — needs a lowercase letter |
| `Abcdefghi` | `422` — needs a special character |
| `Abc defgh!` | `422` — no whitespace |
| `Test@2026` | accepted |

Valid body:

```json
{
  "email": "Test.New@Brightloop.IN",
  "password": "Test@2026",
  "name": "  Test   New  "
}
```

Expected `201`:

- [ ] `email` is stored as `test.new@brightloop.in`
- [ ] `name` is `Test New`
- [ ] `role` is `customer` (default)
- [ ] response keys do **not** include `password_hash`
- [ ] duplicate registration with `test.new@brightloop.in` → `409`
- [ ] duplicate with different case `TEST.NEW@brightloop.in` → `409`
- [ ] name `" "` or `"A"` → `422`
- [ ] invalid email → `422`
- [ ] `role: "admin"` → `403` because `BOOTSTRAP_TOKEN` is currently unset
- [ ] `role: "staff"` without the bootstrap header → `403` as well

### 1.2 Login

`POST /auth/login`

```json
{ "email": "test.customer@brightloop.in", "password": "Test@2026" }
```

- [ ] `200` with `access_token`, `token_type: "bearer"`, `expires_in`, `user`
- [ ] wrong password → `401` `"Invalid email or password."`
- [ ] unknown email → **same** `401` message (no account enumeration)
- [ ] email with spaces/different case → `200`
- [ ] Swagger **Authorize** (form `/auth/token`) works
- [ ] deactivated account → `403` (test in 1.6)

### 1.3 Profile and token checks

- [ ] `GET /users/me` with a token → `200`
- [ ] no token → `401`
- [ ] `Authorization: Bearer garbage` → `401`
- [ ] modify the last character of a valid token → `401`
- [ ] `/users/me` response has no `password_hash`
- [ ] `GET /users` items also have no `password_hash`

### 1.4 Admin directory

`GET /users` (admin token)

- [ ] response is an envelope: `items`, `total`, `limit`, `offset`
- [ ] `?role=staff` returns only staff
- [ ] `?is_active=false` returns an empty page initially (recheck after 1.6)
- [ ] `?q=test` matches email/name substrings
- [ ] `?limit=1&offset=0` and `?limit=1&offset=1` return different items, same `total`
- [ ] `?limit=101` → `422`
- [ ] `?offset=-1` → `422`
- [ ] `?q=a,b` → `422` (PostgREST reserved characters)
- [ ] `?q=a(b)` → `422`
- [ ] `?role=owner` → `422`
- [ ] customer token → `403`
- [ ] staff token → `403`

### 1.5 Role changes

Use the **existing** `$CH` token throughout this section to verify that role
changes are re-read from the database on every request.

- [ ] admin changes `test.customer` to `staff` → `200`, role `staff`
- [ ] with the same `$CH` token, `GET /users/me` now shows `role: "staff"`
- [ ] admin changes `test.customer` **back** to `customer` → `200`
- [ ] with the same `$CH` token, `GET /users/me` now shows `role: "customer"`
      (so the catalog "customer" checks later are still valid)
- [ ] promote with invalid role `"owner"` → `422`
- [ ] promote a random UUID → `404`
- [ ] admin tries to change **own** role → `409`
- [ ] customer (`$CH`) tries to change anyone's role → `403`

### 1.6 Deactivate / reactivate

Using `test.staff` (currently staff):

- [ ] `POST /users/{staff_id}/deactivate` → `200`, `is_active: false`
- [ ] their **existing** token on `/users/me` → `401` `"This account is no longer active."`
- [ ] login as them → `403` `"This account has been deactivated..."`
- [ ] deactivate them **again** → `200` (idempotent, still inactive)
- [ ] `GET /users?is_active=false` now returns only deactivated accounts
      (at this point, at least `test.staff`)
- [ ] `POST /users/{staff_id}/activate` → `200`
- [ ] login works again
- [ ] **caveat:** their old token works again too — deactivation does not bump
      `token_version`. This is accepted behaviour for now.
- [ ] deactivate random UUID → `404`
- [ ] admin tries to deactivate themselves → `409`
- [ ] customer (`$CH`) tries to deactivate someone → `403`

### 1.7 Change password

Use `test.staff`, **not** your own account.

1. Log in as `test.staff` / `Test@2026`, save the token as **token A**.
2. `POST /users/me/change-password`

| Body | Expected |
|---|---|
| `current_password` wrong | `400` "Current password is incorrect." |
| `new_password` = current | `400` "must be different" |
| `new_password` = `weak` | `422` |
| current correct, new `Test@2027` | `200` + **token B** |

- [ ] token A on `/users/me` → `401` `"Session expired. Please log in again."`
- [ ] login with `Test@2026` → `401`
- [ ] login with `Test@2027` → `200`
- [ ] token B on `/users/me` → `200`
- [ ] `token_version` increased by 1 (see SQL in 3.5)

Update `$SH` before continuing to the catalog section (token A is now revoked):

```powershell
$staffToken = (Invoke-RestMethod "$base/auth/login" -Method Post -ContentType "application/json" `
  -Body (@{ email = "test.staff@brightloop.in"; password = "Test@2027" } | ConvertTo-Json)).access_token
$SH = @{ Authorization = "Bearer $staffToken" }
```

### 1.8 Bootstrap token (optional)

Currently `BOOTSTRAP_TOKEN` is **not configured**, so admin/staff self-registration
is disabled. To test the enabled path:

1. Add to `backend/.env`:
   `BOOTSTRAP_TOKEN=local-test-bootstrap-secret`
2. Restart uvicorn.
3. `POST /users/register` with `"role": "admin"` and header
   `X-Bootstrap-Token: local-test-bootstrap-secret` → `201`.
4. Same request with a wrong token → `403`.
5. No header → `403`.
6. Remove the line, restart again.

### 1.9 Token expiry (optional, slow)

1. Add `ACCESS_TOKEN_EXPIRE_MINUTES=1` to `.env`, restart.
2. Log in and wait 65 seconds.
3. `GET /users/me` → `401` `"Invalid or expired token."`
4. Remove the line / restore `60`, restart.

---

## 2. Catalog & Pricing

### 2.1 Products

- [ ] `GET /products` returns `items`, `total`, `limit`, `offset`
- [ ] admin sees 3 test products
- [ ] `?q=crm` matches SKU/name
- [ ] `?limit=2&offset=0`, then `offset=2` → correct pages, same `total`
- [ ] `?limit=0` / `?limit=101` / `?offset=-1` → `422`
- [ ] `?is_active=false` as admin → empty until something is deactivated
- [ ] `?q=a,b` → `422`; `?q=a(b)` → `422`

Create a product with lowercase/whitespace SKU:

```json
{ "sku": "  test-lower  ", "name": "  Test   Lower  ", "description": "  x  " }
```

- [ ] `201`, `sku` = `TEST-LOWER`, `name` = `Test Lower`, `description` = `x`
- [ ] duplicate `test-lower` → `409`
- [ ] SKU `A` → `422`
- [ ] SKU `TEST CRM` (space) → `422`
- [ ] name `" "` → `422`
- [ ] `PATCH /products/{id}` with only `{"name": "Test CRM v2"}` → `200`, SKU unchanged
- [ ] `PATCH` `{"description": null}` → `200`, description cleared
- [ ] `PATCH` empty body `{}` → `422`
- [ ] `PATCH` `{"name": null}` → `422`
- [ ] `PATCH` SKU to an existing SKU → `409`
- [ ] `GET /products/{random-uuid}` → `404`
- [ ] `GET /products/not-a-uuid` → `422`

### 2.2 Variants

- [ ] `POST /variants` with missing `product_id` UUID → `404`
- [ ] valid variant under `P1` → `201`
- [ ] duplicate SKU → `409`
- [ ] duplicate name `standard` (lowercase of `Standard`) → `409`
- [ ] duplicate name in a **different** product → allowed (`V3` vs `V1`)
- [ ] `GET /variants?product_id={P1}` → 2 variants
- [ ] missing `product_id` query → `422`
- [ ] random `product_id` → `404`
- [ ] `PATCH /variants/{id}` name only → `200`, SKU unchanged
- [ ] `PATCH` empty / null name → `422`
- [ ] `PATCH` SKU to existing → `409`
- [ ] `POST /variants` with SKU `A` or `TEST CRM` → `422`

### 2.3 Plans and money

`POST /plans`

- [ ] `price_inr: 999` → `201`, stored/returned as integer `999`
- [ ] `currency` is `INR`
- [ ] zero price → `201` under `V3` (free plan is allowed)
- [ ] `DELETE /plans/{throwaway}` → `204`; admin sees it inactive, customer `404`
- [ ] `price_inr: 999.5` → `422`
- [ ] `price_inr: "999"` → `422`
- [ ] `price_inr: true` → `422`
- [ ] `price_inr: -1` → `422`
- [ ] missing price → `422`
- [ ] `interval_count: 0` / `37` → `422`
- [ ] `trial_days: -1` / `366` → `422`
- [ ] `billing_interval: "fortnight"` → `422`
- [ ] missing/invalid `variant_id` → `404` / `422`
- [ ] duplicate plan name `"test standard monthly"` → `409`
- [ ] same plan name under a different variant → allowed
- [ ] `PATCH /plans/{id}` price only → `200`, name unchanged
- [ ] `PATCH` plan float / negative → `422`
- [ ] `PATCH` empty body → `422`

For guaranteed raw JSON (Swagger sometimes coerces numbers), use PowerShell:

```powershell
$body = '{"variant_id":"' + $V1.id + '","name":"TEST Float","price_inr":999.5}'
try {
  Invoke-RestMethod "$base/plans" -Method Post -Headers $H -ContentType "application/json" -Body $body
} catch {
  [int]$_.Exception.Response.StatusCode   # expect 422
}
```

### 2.4 Reads, ordering, RBAC, customer visibility

- [ ] `GET /plans?variant_id={V1}` returns 3 plans (the zero-price plan is under `V3`)
- [ ] plans are sorted by `price_inr` ascending: `999, 2699, 9999`
- [ ] `?q=annual` returns 1
- [ ] `?q=a,b` → `422`
- [ ] `?limit=2` returns 2 items, `total=3`
- [ ] all prices are JSON integers, not strings/floats
- [ ] customer token: `GET /products`, `/variants`, `/plans` → `200`
- [ ] customer `POST /products` → `403`
- [ ] customer `PATCH /products/{id}` → `403`
- [ ] customer `DELETE /plans/{id}` → `403`
- [ ] staff token: `GET` catalog → `200`
- [ ] staff `POST /products` → `403`
- [ ] anonymous `GET /products` → `401`
- [ ] customer `?is_active=false` → `total: 0` (recheck after 2.5, when
      inactive rows actually exist)

### 2.5 Soft delete, cascade and reactivation

Perform in this order.

1. `DELETE /variants/{V2}` (Pro) → `204`
   - [ ] `GET /variants/{V2}` as admin → `200`, `is_active: false`
   - [ ] `GET /variants/{V2}` as customer → `404`
   - [ ] `PL4` (Pro Monthly) is now inactive
   - [ ] customer `GET /plans/{PL4}` → `404`; admin → `200` inactive
   - [ ] customer `GET /variants?product_id={P1}&is_active=false` → `total: 0`
   - [ ] staff/admin same query → sees the inactive `V2`

2. `DELETE /variants/{V1}` (Standard) → `204`
   - [ ] `PL1`, `PL2`, `PL3` are all inactive
   - [ ] customer plan list for `V1` → `total: 0`

3. Try to reactivate `PL1` while `V1` is inactive:
   - [ ] `PATCH /plans/{PL1}` `{"is_active": true}` → `409`

4. Reactivate V1 and one plan so the product cascade below has active children:
   - [ ] `PATCH /variants/{V1}` `{"is_active": true}` → `200`
   - [ ] `PATCH /plans/{PL1}` `{"is_active": true}` → `200`
   - [ ] customer `GET /plans/{PL1}` → `200`

5. `DELETE /products/{P1}` → `204`
   - [ ] customer `GET /products/{P1}` → `404`
   - [ ] admin `GET /products/{P1}` → `200`, `is_active: false`
   - [ ] customer product list excludes `TEST-CRM`
   - [ ] all variants/plans under `P1` are inactive
   - [ ] `POST /variants` under inactive `P1` → `409`
   - [ ] `POST /plans` under an inactive variant → `409`
   - [ ] **Pause here:** run the cascade query in 3.2 before step 6

6. Reactivate bottom-up:
   - [ ] first, `PATCH /variants/{V1}` `{"is_active": true}` → `409` (product still inactive)
   - [ ] `PATCH /plans/{PL1}` `{"is_active": true}` → `409` (variant still inactive)
   - [ ] `PATCH /products/{P1}` `{"is_active": true}` → `200`
   - [ ] `PATCH /variants/{V1}` `{"is_active": true}` → `200`
   - [ ] `PATCH /plans/{PL1}` `{"is_active": true}` → `200`
   - [ ] customer sees product, variant and plan again

7. Test PATCH-based deactivation on the untouched `P3`:
   - [ ] `PATCH /products/{P3}` `{"is_active": false}` → `200`
   - [ ] `V3` is inactive; customer `GET /products/{P3}` → `404`
   - [ ] `PATCH /products/{P3}` `{"is_active": true}` → `200`
   - [ ] `PATCH /variants/{V3}` `{"is_active": true}` → `200`
   - [ ] customer sees `P3` and `V3` again

8. `DELETE /products/{random-uuid}` → `404`

---

## 3. Database invariants

Run these while the `TEST-` rows still exist (before cleanup). Some checks depend
on the state left by section 2.5; where noted, run them at that point.

### 3.1 Soft delete keeps rows

```sql
select sku, is_active from public.products where sku like 'TEST-%' order by sku;
select sku, is_active from public.product_variants where sku like 'TEST-%' order by sku;
select name, price_inr, is_active from public.plans where name like 'TEST%' order by price_inr;
```

- [ ] each row still exists; `is_active` reflects the last action (false unless
      reactivated in 2.5)
- [ ] `price_inr` values are integers (`999`, `2699`, `9999`), never `999.0`

### 3.2 Cascade consistency

```sql
select p.sku as product, p.is_active as product_active,
       v.sku as variant, v.is_active as variant_active,
       pl.name as plan, pl.is_active as plan_active
from public.products p
left join public.product_variants v on v.product_id = p.id
left join public.plans pl on pl.variant_id = v.id
where p.sku like 'TEST-%'
order by p.sku, v.sku, pl.price_inr;
```

- [ ] while `P1` is inactive (between 2.5 steps 5 and 6), every child under it
      is `false`

No active child under an inactive parent:

```sql
select count(*) as active_variants_under_inactive_products
from public.product_variants v
join public.products p on p.id = v.product_id
where not p.is_active and v.is_active;

select count(*) as active_plans_under_inactive_variants
from public.plans pl
join public.product_variants v on v.id = pl.variant_id
where not v.is_active and pl.is_active;
```

- [ ] both counts are `0`

### 3.3 Foreign keys are RESTRICT

```sql
do $$
begin
    begin
        delete from public.products where sku = 'TEST-CRM';
        raise exception 'FK NOT ENFORCED';
    exception
        when foreign_key_violation then
            raise notice 'OK: product delete blocked by variants FK';
    end;
end
$$;
```

- [ ] message: `OK: product delete blocked by variants FK`

### 3.4 Money check constraint

```sql
do $$
begin
    begin
        insert into public.plans (variant_id, name, price_inr)
        select id, 'TEST Negative', -1
        from public.product_variants
        where sku = 'TEST-CRM-STD';
        raise exception 'CHECK NOT ENFORCED';
    exception
        when check_violation then
            raise notice 'OK: negative price_inr blocked';
    end;
end
$$;
```

- [ ] message: `OK: negative price_inr blocked`

### 3.5 RLS, hashes and token version

```sql
select relname, relrowsecurity
from pg_class
where relname in ('users', 'products', 'product_variants', 'plans')
order by relname;
```

- [ ] all four rows show `relrowsecurity = true`

```sql
select email, left(password_hash, 4) as hash_prefix,
       password_hash = 'Test@2026' as is_plaintext,
       token_version
from public.users
where email like 'test.%'
order by email;
```

- [ ] `hash_prefix` is `$2b$`
- [ ] `is_plaintext` is `false`
- [ ] `test.staff` `token_version` is `1` (or `2` if you changed the password
      back during cleanup)

### 3.6 Money column is bigint

```sql
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'plans'
  and column_name = 'price_inr';
```

- [ ] `price_inr | bigint`

---

## 4. Cleanup

Run in this order. There are no subscriptions yet, so hard deletes are safe.

```sql
delete from public.plans
where variant_id in (
    select v.id
    from public.product_variants v
    join public.products p on p.id = v.product_id
    where p.sku like 'TEST-%'
);

delete from public.product_variants
where product_id in (
    select id from public.products where sku like 'TEST-%'
);

delete from public.products
where sku like 'TEST-%';

delete from public.users
where email like 'test.%@brightloop.in';

update public.users
set role = 'customer'
where email = 'arjun@brightloop.in';
```

Verify:

```sql
select count(*) as leftover_products from public.products where sku like 'TEST-%';
select count(*) as leftover_variants from public.product_variants where sku like 'TEST-%';
select count(*) as leftover_plans from public.plans where name like 'TEST%';
select email, role from public.users order by email;
```

- [ ] all leftovers are `0`
- [ ] only your real accounts remain, with `arjun` back to `customer`

If a `live_smoke.ps1` run left rows and the automatic cleanup failed, run
the same order for its data:

```sql
delete from public.plans where name like 'SMOKE-%';
delete from public.product_variants where sku like 'SMOKE-%';
delete from public.products where sku like 'SMOKE-%';
delete from public.users where email like 'smoke.%@brightloop.in';
```

Then repeat the verification queries with `SMOKE-%` / `smoke.%`.

If you changed your own password during testing, set it back through
`POST /users/me/change-password`.

---

## 5. Known caveats (expected behaviour, not bugs)

- **Whole-rupee storage:** `₹99.50` is impossible. Tax/proration/discount
  calculations will need an explicit rounding policy in the billing module.
- **Deactivation does not revoke tokens.** A token issued before deactivation
  starts working again if the account is reactivated within its 60-minute life.
  Password changes *do* revoke tokens (`token_version`).
- **Cascades are not one transaction.** Deactivating a product issues several
  Supabase calls (plans → variants → product). A mid-way failure can leave some
  children inactive; retrying the delete is safe.
- **Customers only see active rows.** Passing `is_active=false` as a customer
  returns an empty page rather than inactive records.
- **Catalog reads require authentication.** There is no public storefront
  endpoint; the customer portal must log in first.
- **No rate limiting yet.** Login brute-force protection is not implemented.
- **Plan price updates do not affect subscriptions.** Subscriptions must snapshot
  the rupee price when that module is built.
- **Not built yet:** subscriptions, billing runs, payments, invoices, discounts,
  tax, proration, dunning.
