<#
.SYNOPSIS
    Live smoke test for the Brightloop backend (users, auth, catalog, pricing).

.DESCRIPTION
    Drives the real API with the service admin account, creates isolated data
    prefixed with SMOKE-<suffix>, checks the happy path and key RBAC/validation
    guards, then hard-deletes the test data through scripts/cleanup_smoke.py.

    The account passed via -AdminEmail must already have the admin role.

.PARAMETER BaseUrl
    API base URL. Default: http://127.0.0.1:8000/api/v1

.PARAMETER AdminEmail
    Existing admin account. Default: arjun@brightloop.in

.PARAMETER AdminPassword
    Password for the admin account. If omitted, you are prompted securely.

.PARAMETER Suffix
    Alphanumeric suffix for the test data (1-17 chars). Defaults to a timestamp.

.PARAMETER KeepData
    Do not hard-delete the test data. The cleanup SQL is printed at the end.

.PARAMETER PreflightOnly
    Check health, admin login, admin role and catalog schema, then exit without
    creating any data.

.PARAMETER CleanupOnly
    Only hard-delete smoke rows for the supplied suffix. Does not call the API.

.EXAMPLE
    .\scripts\live_smoke.ps1

.EXAMPLE
    .\scripts\live_smoke.ps1 -PreflightOnly

.EXAMPLE
    .\scripts\live_smoke.ps1 -Suffix 20261031A -KeepData

.EXAMPLE
    .\scripts\live_smoke.ps1 -CleanupOnly -Suffix 20261031A
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000/api/v1",
    [string]$AdminEmail = "arjun@brightloop.in",
    [string]$AdminPassword,
    [string]$Suffix,
    [switch]$KeepData,
    [switch]$PreflightOnly,
    [switch]$CleanupOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}
catch {
    # Older .NET runtimes may not expose the enum; Invoke-WebRequest defaults apply.
}

$BaseUrl = $BaseUrl.TrimEnd("/")
$RootUrl = $BaseUrl -replace "/api/v1$", ""

if (-not $Suffix) {
    $Suffix = (Get-Date -Format "yyyyMMddHHmmss") + (Get-Random -Minimum 100 -Maximum 999)
}
if ($Suffix -notmatch "^[A-Za-z0-9]{1,17}$") {
    throw "Suffix must be 1-17 alphanumeric characters."
}

# SKUs and plan names are normalised to uppercase; emails are lowercase.
$Suffix = $Suffix.ToUpperInvariant()
$EmailSuffix = $Suffix.ToLowerInvariant()
$Run = "SMOKE-$Suffix"

$CustomerEmail = "smoke.$EmailSuffix.customer@brightloop.in"
$StaffEmail = "smoke.$EmailSuffix.staff@brightloop.in"
$PasswordEmail = "smoke.$EmailSuffix.password@brightloop.in"
$Password = "Smoke@2026"
$NewPassword = "Smoke@2027"

$script:Passed = 0
$script:Failed = 0

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Block
    )

    Write-Host "  ...  $Name" -NoNewline
    try {
        $result = & $Block
        Write-Host "`r  PASS $Name" -ForegroundColor Green
        $script:Passed++
        return $result
    }
    catch {
        Write-Host "`r  FAIL $Name" -ForegroundColor Red
        Write-Host "       $($_.Exception.Message)" -ForegroundColor Yellow
        $script:Failed++
        throw
    }
}

function Assert-Status {
    param($Response, [int]$Expected, [string]$What)

    if ($null -eq $Response) {
        throw "$What -> no response object"
    }
    if ($Response.Status -ne $Expected) {
        $detail = [string]$Response.Raw
        if ($Response.Data -and ($Response.Data.PSObject.Properties.Name -contains "detail")) {
            $d = $Response.Data.detail
            $detail = if ($d -is [string]) { $d } else { $d | ConvertTo-Json -Depth 6 -Compress }
        }
        throw "$What -> HTTP $($Response.Status), expected $Expected. $detail"
    }
}

function Assert-True {
    param($Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    if ($Actual -ne $Expected) {
        throw "$Message (expected '$Expected', got '$Actual')"
    }
}

function Call-Url {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Url,
        [hashtable]$Headers,
        $Body
    )

    $params = @{
        Uri         = $Url
        Method      = $Method
        TimeoutSec  = 30
        ErrorAction = "Stop"
    }
    if ($PSVersionTable.PSVersion.Major -lt 6) {
        $params["UseBasicParsing"] = $true
    }
    if ($Headers) {
        $params.Headers = $Headers
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        if ($Body -is [string]) {
            $params.Body = $Body
        }
        else {
            $params.Body = ($Body | ConvertTo-Json -Depth 8 -Compress)
        }
    }

    try {
        $response = Invoke-WebRequest @params
        $data = $null
        if ($response.Content) {
            try { $data = $response.Content | ConvertFrom-Json }
            catch { $data = $response.Content }
        }
        return [pscustomobject]@{
            Status = [int]$response.StatusCode
            Data   = $data
            Raw    = [string]$response.Content
        }
    }
    catch {
        $status = 0
        if ($_.Exception.Response) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = 0 }
        }

        $raw = ""
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $raw = [string]$_.ErrorDetails.Message
        }
        elseif ($_.Exception.Response) {
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $raw = $reader.ReadToEnd()
                    $reader.Dispose()
                }
            }
            catch {
                # Response body is optional; status code is what matters.
            }
        }

        $data = $null
        if ($raw) {
            try { $data = $raw | ConvertFrom-Json }
            catch { $data = $raw }
        }
        return [pscustomobject]@{
            Status = $status
            Data   = $data
            Raw    = $raw
        }
    }
}

function Call-Api {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [hashtable]$Headers,
        $Body
    )
    return Call-Url -Method $Method -Url ($BaseUrl + $Path) -Headers $Headers -Body $Body
}

function New-AuthHeader {
    param([Parameter(Mandatory)][string]$Token)
    return @{ Authorization = "Bearer $Token" }
}

function Login {
    param(
        [Parameter(Mandatory)][string]$Email,
        [Parameter(Mandatory)][string]$Pwd
    )
    $r = Call-Api -Method "POST" -Path "/auth/login" -Body @{ email = $Email; password = $Pwd }
    Assert-Status $r 200 "login $Email"
    Assert-True ($r.Data.PSObject.Properties.Name -contains "access_token") "login $Email returned no access_token"
    return $r.Data
}

function Get-CleanupSql {
    return @"
delete from public.plans where name like '$Run%';
delete from public.product_variants where sku like '$Run-%';
delete from public.products where sku like '$Run-%';
delete from public.users where email like 'smoke.$EmailSuffix.%';
"@
}

function Invoke-Cleanup {
    $backendDir = Split-Path -Parent $PSScriptRoot
    $cleanupScript = Join-Path $PSScriptRoot "cleanup_smoke.py"
    $python = Join-Path $backendDir "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        $python = "python"
    }
    if (-not (Test-Path -LiteralPath $cleanupScript)) {
        throw "Cleanup helper not found: $cleanupScript"
    }

    Write-Host "  Cleanup ($Suffix) ... " -NoNewline
    & $python $cleanupScript --suffix $Suffix
    if ($LASTEXITCODE -ne 0) {
        throw "cleanup helper failed with exit code $LASTEXITCODE"
    }
}

# --------------------------------------------------------------------------- #
# Cleanup-only mode
# --------------------------------------------------------------------------- #

if ($CleanupOnly) {
    try {
        Invoke-Cleanup
        exit 0
    }
    catch {
        Write-Host "Cleanup failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Run this in the Supabase SQL Editor:"
        Write-Host (Get-CleanupSql)
        exit 1
    }
}

if (-not $AdminPassword) {
    $secure = Read-Host -Prompt "Password for $AdminEmail" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
if (-not $AdminPassword) {
    throw "Admin password is required."
}

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

Write-Host "Brightloop live smoke test" -ForegroundColor Cyan
Write-Host "API:    $BaseUrl"
Write-Host "Suffix: $Suffix"
Write-Host ("Mode:   {0}" -f $(if ($PreflightOnly) { "preflight only" } else { "full" }))

$fatal = $null

try {
    Invoke-Step "health endpoint" {
        $r = Call-Url -Method "GET" -Url "$RootUrl/health"
        Assert-Status $r 200 "health"
        Assert-Equal $r.Data.status "ok" "health status"
        Assert-True ($r.Data.supabase_configured -eq $true) "supabase_configured is false"
        Assert-True ($r.Data.auth_configured -eq $true) "auth_configured is false"
    } | Out-Null

    $admin = Invoke-Step "admin login" {
        $u = Login $AdminEmail $AdminPassword
        if ($u.user.role -ne "admin") {
            throw "This account has role '$($u.user.role)', not admin. Promote it with: update public.users set role='admin' where email='$AdminEmail';"
        }
        return $u
    }
    $AH = New-AuthHeader $admin.access_token

    Invoke-Step "catalog schema is deployed" {
        $r = Call-Api -Method "GET" -Path "/products" -Headers $AH
        if ($r.Status -eq 503) {
            $detail = [string]$r.Raw
            if ($r.Data -and ($r.Data.PSObject.Properties.Name -contains "detail")) {
                $detail = [string]$r.Data.detail
            }
            throw "Catalog tables are missing. Run backend/sql/003_catalog.sql then 004_money_to_rupees.sql. $detail"
        }
        Assert-Status $r 200 "catalog probe"
    } | Out-Null

    if ($PreflightOnly) {
        Write-Host ""
        Write-Host "Preflight passed (no data created)." -ForegroundColor Green
    }
    else {
        # ------------------------------------------------------------------- #
        # Users & auth
        # ------------------------------------------------------------------- #
        Write-Section "Users & auth"

        $customer = Invoke-Step "register customer" {
            $r = Call-Api -Method "POST" -Path "/users/register" -Body @{
                email    = $CustomerEmail
                password = $Password
                name     = "Smoke Customer $Suffix"
            }
            Assert-Status $r 201 "register customer"
            Assert-Equal $r.Data.email $CustomerEmail "email normalisation"
            Assert-True (-not ($r.Data.PSObject.Properties.Name -contains "password_hash")) "password_hash leaked in register response"
            return $r.Data
        }
        $custLogin = Invoke-Step "customer login" { Login $CustomerEmail $Password }
        $CH = New-AuthHeader $custLogin.access_token

        Invoke-Step "duplicate email rejected" {
            $r = Call-Api -Method "POST" -Path "/users/register" -Body @{
                email    = $CustomerEmail
                password = $Password
                name     = "Duplicate"
            }
            Assert-Status $r 409 "duplicate email"
        } | Out-Null

        $staff = Invoke-Step "register staff candidate" {
            $r = Call-Api -Method "POST" -Path "/users/register" -Body @{
                email    = $StaffEmail
                password = $Password
                name     = "Smoke Staff $Suffix"
            }
            Assert-Status $r 201 "register staff candidate"
            return $r.Data
        }
        $staffLoginBefore = Invoke-Step "staff candidate login" { Login $StaffEmail $Password }
        $SHBefore = New-AuthHeader $staffLoginBefore.access_token

        Invoke-Step "promote to staff" {
            $r = Call-Api -Method "PATCH" -Path "/users/$($staff.id)/role" -Headers $AH -Body @{ role = "staff" }
            Assert-Status $r 200 "promote staff"
            Assert-Equal $r.Data.role "staff" "role after promotion"
        } | Out-Null

        Invoke-Step "role change is immediate" {
            $r = Call-Api -Method "GET" -Path "/users/me" -Headers $SHBefore
            Assert-Status $r 200 "staff /users/me"
            Assert-Equal $r.Data.role "staff" "role re-read from DB"
        } | Out-Null

        Invoke-Step "staff can read but not write" {
            $read = Call-Api -Method "GET" -Path "/products" -Headers $SHBefore
            Assert-Status $read 200 "staff catalog read"
            $write = Call-Api -Method "POST" -Path "/products" -Headers $SHBefore -Body @{
                sku = "$Run-DENY"; name = "Nope"
            }
            Assert-Status $write 403 "staff catalog write"
        } | Out-Null

        Invoke-Step "deactivate staff" {
            $r = Call-Api -Method "POST" -Path "/users/$($staff.id)/deactivate" -Headers $AH
            Assert-Status $r 200 "deactivate staff"
            Assert-Equal $r.Data.is_active $false "is_active after deactivate"
        } | Out-Null

        Invoke-Step "deactivated token rejected" {
            $r = Call-Api -Method "GET" -Path "/users/me" -Headers $SHBefore
            Assert-Status $r 401 "deactivated token"
        } | Out-Null

        Invoke-Step "deactivated login blocked" {
            $r = Call-Api -Method "POST" -Path "/auth/login" -Body @{ email = $StaffEmail; password = $Password }
            Assert-Status $r 403 "deactivated login"
        } | Out-Null

        Invoke-Step "reactivate staff" {
            $r = Call-Api -Method "POST" -Path "/users/$($staff.id)/activate" -Headers $AH
            Assert-Status $r 200 "reactivate staff"
            Assert-Equal $r.Data.is_active $true "is_active after activate"
        } | Out-Null

        $staffLogin = Invoke-Step "staff login after reactivation" { Login $StaffEmail $Password }
        $SH = New-AuthHeader $staffLogin.access_token

        $passwordUser = Invoke-Step "register password user" {
            $r = Call-Api -Method "POST" -Path "/users/register" -Body @{
                email    = $PasswordEmail
                password = $Password
                name     = "Smoke Password $Suffix"
            }
            Assert-Status $r 201 "register password user"
            return $r.Data
        }
        $pwLogin = Invoke-Step "password user login" { Login $PasswordEmail $Password }
        $PWH = New-AuthHeader $pwLogin.access_token

        Invoke-Step "wrong current password rejected" {
            $r = Call-Api -Method "POST" -Path "/users/me/change-password" -Headers $PWH -Body @{
                current_password = "Wrong@2026"
                new_password     = $NewPassword
            }
            Assert-Status $r 400 "wrong current password"
        } | Out-Null

        Invoke-Step "change password" {
            $r = Call-Api -Method "POST" -Path "/users/me/change-password" -Headers $PWH -Body @{
                current_password = $Password
                new_password     = $NewPassword
            }
            Assert-Status $r 200 "change password"
            Assert-True ($r.Data.PSObject.Properties.Name -contains "access_token") "change password returned no token"
            return $r.Data
        } | Out-Null

        Invoke-Step "old token revoked" {
            $r = Call-Api -Method "GET" -Path "/users/me" -Headers $PWH
            Assert-Status $r 401 "old token after password change"
        } | Out-Null

        Invoke-Step "old password rejected, new accepted" {
            $old = Call-Api -Method "POST" -Path "/auth/login" -Body @{ email = $PasswordEmail; password = $Password }
            Assert-Status $old 401 "old password login"
            $new = Login $PasswordEmail $NewPassword
            Assert-True ($new.access_token) "new password login token missing"
        } | Out-Null

        Invoke-Step "admin user directory" {
            $r = Call-Api -Method "GET" -Path "/users?q=$Suffix&limit=100" -Headers $AH
            Assert-Status $r 200 "user directory"
            Assert-True ($r.Data.total -ge 3) "expected at least 3 smoke users, got $($r.Data.total)"
            $items = @($r.Data.items)
            $emails = @($items | ForEach-Object { $_.email })
            Assert-True ($emails -contains $StaffEmail) "staff missing from user directory"
            Assert-True ($items.Count -gt 0) "user directory returned no items"
            Assert-True (-not ($items[0].PSObject.Properties.Name -contains "password_hash")) "password_hash leaked in user list"
        } | Out-Null

        Invoke-Step "customer cannot list users" {
            $r = Call-Api -Method "GET" -Path "/users" -Headers $CH
            Assert-Status $r 403 "customer user directory"
        } | Out-Null

        Invoke-Step "customer cannot write catalog" {
            $r = Call-Api -Method "POST" -Path "/products" -Headers $CH -Body @{ sku = "$Run-DENY2"; name = "Nope" }
            Assert-Status $r 403 "customer product write"
        } | Out-Null

        # ------------------------------------------------------------------- #
        # Catalog & pricing
        # ------------------------------------------------------------------- #
        Write-Section "Catalog & pricing"

        $catalog = Invoke-Step "create products and variants" {
            $pA = Call-Api -Method "POST" -Path "/products" -Headers $AH -Body @{
                sku         = "  $($Run.ToLower())-a  "
                name        = "  Smoke $Suffix   Product A  "
                description = "  smoke  "
            }
            Assert-Status $pA 201 "create product A"
            Assert-Equal $pA.Data.sku "$Run-A" "product SKU normalisation"
            Assert-Equal $pA.Data.name "Smoke $Suffix Product A" "product name normalisation"

            $pB = Call-Api -Method "POST" -Path "/products" -Headers $AH -Body @{
                sku = "$Run-B"; name = "Smoke $Suffix Product B"
            }
            Assert-Status $pB 201 "create product B"

            $vStd = Call-Api -Method "POST" -Path "/variants" -Headers $AH -Body @{
                product_id = $pA.Data.id; sku = "$Run-A-STD"; name = "Standard"
            }
            Assert-Status $vStd 201 "create variant A-STD"

            $vPro = Call-Api -Method "POST" -Path "/variants" -Headers $AH -Body @{
                product_id = $pA.Data.id; sku = "$Run-A-PRO"; name = "Pro"
            }
            Assert-Status $vPro 201 "create variant A-PRO"

            $vB = Call-Api -Method "POST" -Path "/variants" -Headers $AH -Body @{
                product_id = $pB.Data.id; sku = "$Run-B-STD"; name = "Standard"
            }
            Assert-Status $vB 201 "create variant B-STD"

            return [pscustomobject]@{
                ProductA = $pA.Data
                ProductB = $pB.Data
                AStd     = $vStd.Data
                APro     = $vPro.Data
                BStd     = $vB.Data
            }
        }

        Invoke-Step "duplicate product SKU rejected" {
            $r = Call-Api -Method "POST" -Path "/products" -Headers $AH -Body @{
                sku = "$Run-A"; name = "Duplicate"
            }
            Assert-Status $r 409 "duplicate product SKU"
        } | Out-Null

        Invoke-Step "duplicate variant SKU rejected" {
            $r = Call-Api -Method "POST" -Path "/variants" -Headers $AH -Body @{
                product_id = $catalog.ProductA.id; sku = "$Run-A-STD"; name = "Other"
            }
            Assert-Status $r 409 "duplicate variant SKU"
        } | Out-Null

        $plans = Invoke-Step "create plans in whole rupees" {
            $monthly = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body @{
                variant_id = $catalog.AStd.id; name = "$Run Monthly"
                billing_interval = "month"; interval_count = 1; price_inr = 999
            }
            Assert-Status $monthly 201 "create monthly plan"
            Assert-Equal $monthly.Data.price_inr 999 "monthly price_inr"
            Assert-Equal $monthly.Data.currency "INR" "plan currency"

            $quarterly = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body @{
                variant_id = $catalog.AStd.id; name = "$Run Quarterly"
                billing_interval = "month"; interval_count = 3; price_inr = 2699; trial_days = 14
            }
            Assert-Status $quarterly 201 "create quarterly plan"

            $annual = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body @{
                variant_id = $catalog.AStd.id; name = "$Run Annual"
                billing_interval = "year"; interval_count = 1; price_inr = 9999
            }
            Assert-Status $annual 201 "create annual plan"

            $pro = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body @{
                variant_id = $catalog.APro.id; name = "$Run Pro Monthly"
                billing_interval = "month"; interval_count = 1; price_inr = 1999
            }
            Assert-Status $pro 201 "create pro plan"

            return [pscustomobject]@{
                Monthly   = $monthly.Data
                Quarterly = $quarterly.Data
                Annual    = $annual.Data
                Pro       = $pro.Data
            }
        }

        Invoke-Step "duplicate plan name rejected" {
            $r = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body @{
                variant_id = $catalog.AStd.id; name = "$Run Monthly"; price_inr = 500
            }
            Assert-Status $r 409 "duplicate plan name"
        } | Out-Null

        Invoke-Step "float price rejected" {
            $raw = '{"variant_id":"' + $catalog.AStd.id + '","name":"' + $Run + ' Float","price_inr":999.5}'
            $r = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body $raw
            Assert-Status $r 422 "float price"
        } | Out-Null

        Invoke-Step "negative price rejected" {
            $r = Call-Api -Method "POST" -Path "/plans" -Headers $AH -Body @{
                variant_id = $catalog.AStd.id; name = "$Run Negative"; price_inr = -1
            }
            Assert-Status $r 422 "negative price"
        } | Out-Null

        Invoke-Step "plan list is sorted and integer" {
            $r = Call-Api -Method "GET" -Path "/plans?variant_id=$($catalog.AStd.id)" -Headers $AH
            Assert-Status $r 200 "plan list"
            Assert-Equal $r.Data.total 3 "plan total"
            $prices = @($r.Data.items | ForEach-Object { $_.price_inr })
            Assert-Equal ($prices -join ",") "999,2699,9999" "plan price ordering"
            $bad = @($r.Data.items | Where-Object { -not ($_.price_inr -is [int] -or $_.price_inr -is [long]) })
            Assert-Equal $bad.Count 0 "non-integer price returned"
        } | Out-Null

        Invoke-Step "customer sees active catalog" {
            $products = Call-Api -Method "GET" -Path "/products" -Headers $CH
            Assert-Status $products 200 "customer products"
            $ids = @($products.Data.items | ForEach-Object { $_.id })
            Assert-True ($ids -contains $catalog.ProductA.id) "product A missing for customer"

            $pl = Call-Api -Method "GET" -Path "/plans?variant_id=$($catalog.AStd.id)" -Headers $CH
            Assert-Status $pl 200 "customer plans"
            Assert-Equal $pl.Data.total 3 "customer plan total"
        } | Out-Null

        # ------------------------------------------------------------------- #
        # Soft delete, cascade, reactivation
        # ------------------------------------------------------------------- #
        Write-Section "Soft delete & cascade"

        Invoke-Step "variant soft delete cascades to its plans" {
            $del = Call-Api -Method "DELETE" -Path "/variants/$($catalog.APro.id)" -Headers $AH
            Assert-Status $del 204 "delete variant A-PRO"

            $adminV = Call-Api -Method "GET" -Path "/variants/$($catalog.APro.id)" -Headers $AH
            Assert-Status $adminV 200 "admin reads inactive variant"
            Assert-Equal $adminV.Data.is_active $false "variant A-PRO is_active"

            $custV = Call-Api -Method "GET" -Path "/variants/$($catalog.APro.id)" -Headers $CH
            Assert-Status $custV 404 "customer inactive variant"

            $adminP = Call-Api -Method "GET" -Path "/plans/$($plans.Pro.id)" -Headers $AH
            Assert-Status $adminP 200 "admin reads cascaded plan"
            Assert-Equal $adminP.Data.is_active $false "cascaded plan is_active"

            $custP = Call-Api -Method "GET" -Path "/plans/$($plans.Pro.id)" -Headers $CH
            Assert-Status $custP 404 "customer cascaded plan"
        } | Out-Null

        Invoke-Step "delete standard variant and enforce reactivation order" {
            $del = Call-Api -Method "DELETE" -Path "/variants/$($catalog.AStd.id)" -Headers $AH
            Assert-Status $del 204 "delete variant A-STD"

            $plan = Call-Api -Method "GET" -Path "/plans/$($plans.Monthly.id)" -Headers $AH
            Assert-Status $plan 200 "admin reads inactive plan"
            Assert-Equal $plan.Data.is_active $false "monthly plan is_active"

            $bad = Call-Api -Method "PATCH" -Path "/plans/$($plans.Monthly.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $bad 409 "activate plan under inactive variant"

            $v = Call-Api -Method "PATCH" -Path "/variants/$($catalog.AStd.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $v 200 "reactivate variant"

            $p = Call-Api -Method "PATCH" -Path "/plans/$($plans.Monthly.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $p 200 "reactivate plan"

            $c = Call-Api -Method "GET" -Path "/plans/$($plans.Monthly.id)" -Headers $CH
            Assert-Status $c 200 "customer sees reactivated plan"
        } | Out-Null

        Invoke-Step "product soft delete cascades and hides" {
            $del = Call-Api -Method "DELETE" -Path "/products/$($catalog.ProductA.id)" -Headers $AH
            Assert-Status $del 204 "delete product A"

            $custP = Call-Api -Method "GET" -Path "/products/$($catalog.ProductA.id)" -Headers $CH
            Assert-Status $custP 404 "customer inactive product"

            $adminP = Call-Api -Method "GET" -Path "/products/$($catalog.ProductA.id)" -Headers $AH
            Assert-Status $adminP 200 "admin reads inactive product"
            Assert-Equal $adminP.Data.is_active $false "product A is_active"

            $adminV = Call-Api -Method "GET" -Path "/variants/$($catalog.AStd.id)" -Headers $AH
            Assert-Status $adminV 200 "admin reads cascaded variant"
            Assert-Equal $adminV.Data.is_active $false "cascaded variant is_active"

            $custList = Call-Api -Method "GET" -Path "/products" -Headers $CH
            Assert-Status $custList 200 "customer product list"
            $ids = @($custList.Data.items | ForEach-Object { $_.id })
            Assert-True (-not ($ids -contains $catalog.ProductA.id)) "inactive product leaked to customer list"

            $custInactive = Call-Api -Method "GET" -Path "/products?is_active=false" -Headers $CH
            Assert-Status $custInactive 200 "customer inactive filter"
            Assert-Equal $custInactive.Data.total 0 "customer inactive filter total"

            $staffInactive = Call-Api -Method "GET" -Path "/products?is_active=false" -Headers $SH
            Assert-Status $staffInactive 200 "staff inactive filter"
            $staffIds = @($staffInactive.Data.items | ForEach-Object { $_.id })
            Assert-True ($staffIds -contains $catalog.ProductA.id) "staff cannot see inactive product"

            $bad = Call-Api -Method "PATCH" -Path "/variants/$($catalog.AStd.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $bad 409 "activate variant under inactive product"
        } | Out-Null

        Invoke-Step "reactivate product tree bottom-up" {
            $p = Call-Api -Method "PATCH" -Path "/products/$($catalog.ProductA.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $p 200 "reactivate product"

            $v = Call-Api -Method "PATCH" -Path "/variants/$($catalog.AStd.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $v 200 "reactivate variant"

            $pl = Call-Api -Method "PATCH" -Path "/plans/$($plans.Monthly.id)" -Headers $AH -Body @{ is_active = $true }
            Assert-Status $pl 200 "reactivate plan"

            $c = Call-Api -Method "GET" -Path "/plans/$($plans.Monthly.id)" -Headers $CH
            Assert-Status $c 200 "customer sees reactivated plan"
        } | Out-Null

        Write-Host ""
        Write-Host "Test data suffix: $Suffix" -ForegroundColor DarkGray
    }
}
catch {
    $fatal = $_
}
finally {
    if (-not $PreflightOnly) {
        if ($KeepData) {
            Write-Host ""
            Write-Host "Keeping smoke data (suffix $Suffix). Clean up with:" -ForegroundColor Yellow
            Write-Host (Get-CleanupSql)
        }
        else {
            Write-Host ""
            try {
                Invoke-Cleanup
            }
            catch {
                Write-Warning "Automatic cleanup failed: $($_.Exception.Message)"
                Write-Host "Run this in the Supabase SQL Editor:"
                Write-Host (Get-CleanupSql)
            }
        }
    }
}

if ($fatal) {
    Write-Host ""
    Write-Host "SMOKE TEST FAILED ($($script:Failed) failed, $($script:Passed) passed)." -ForegroundColor Red
    Write-Host $fatal.Exception.Message -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "SMOKE TEST PASSED ($($script:Passed) checks)." -ForegroundColor Green
exit 0
