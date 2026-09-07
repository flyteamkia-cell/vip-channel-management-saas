<#
.SYNOPSIS
    Run the test suite on Windows, with or without Docker.

.DESCRIPTION
    The integration and e2e layers need a real PostgreSQL. This script finds one
    the way a Windows box usually has one -- a native install from the EDB
    installer or winget -- creates the test role and database if they are
    missing, and runs pytest with TEST_DATABASE_URL set.

    The admin account is needed exactly once, for that first provisioning run.
    Afterwards the script connects straight as the application role and never
    asks for the superuser password again.

    The suite deliberately connects as an ORDINARY role. PostgreSQL exempts
    superusers and BYPASSRLS roles from row policies, so a run as `postgres`
    would skip every row-level-security assertion instead of evaluating it.

    The application role's password is read from VIP_TEST_DB_PASSWORD when that
    variable is set, so it need not be typed on the command line or stored here.

.EXAMPLE
    .\scripts\run-tests.ps1
    Normal run. Prompts for the admin password only on first-time setup.

.EXAMPLE
    .\scripts\run-tests.ps1 -UnitOnly
    Unit layer only. No database required.

.EXAMPLE
    $env:VIP_TEST_DB_PASSWORD = "<new password>"
    .\scripts\run-tests.ps1
    Uses a changed password for the application role.

.EXAMPLE
    .\scripts\run-tests.ps1 -UseDocker
    Brings up docker-compose.test.yml on port 5433 and runs against it.
#>
[CmdletBinding()]
param(
    [string]$PgHost = "localhost",
    [int]$Port = 5432,
    [string]$User = "postgres",
    [string]$Password = $env:PGPASSWORD,
    [string]$Database = "vip_test",
    [string]$AppUser = "vip_app",
    [string]$AppPassword = $(if ($env:VIP_TEST_DB_PASSWORD) { $env:VIP_TEST_DB_PASSWORD } else { "vip" }),
    [switch]$UnitOnly,
    [switch]$UseDocker
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Find-Psql {
    $found = (Get-Command psql -ErrorAction SilentlyContinue).Source
    if ($found) { return $found }
    $candidates = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($candidates) { return $candidates[0].FullName }
    return $null
}

function Test-AppLogin {
    param([string]$Psql)
    $env:PGPASSWORD = $AppPassword
    & $Psql -h $PgHost -p $Port -U $AppUser -d $Database -tAc "SELECT 1" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Provisioning {
    param([string]$Psql, [string]$AdminPassword)

    $env:PGPASSWORD = $AdminPassword
    & $Psql -h $PgHost -p $Port -U $User -d postgres -tAc "SELECT 1" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Could not reach PostgreSQL at ${PgHost}:${Port} as '$User'." -ForegroundColor Red
        Write-Host "Check that the service is running and the password is correct." -ForegroundColor Red
        Write-Host "Locked out? See 'Resetting the PostgreSQL password' in README.md." -ForegroundColor Red
        exit 1
    }

    $roleExists = & $Psql -h $PgHost -p $Port -U $User -d postgres -tAc `
        "SELECT 1 FROM pg_roles WHERE rolname = '$AppUser'"
    if ($roleExists -ne "1") {
        Write-Host "Creating role '$AppUser' (NOSUPERUSER, NOBYPASSRLS)..." -ForegroundColor Cyan
        & $Psql -h $PgHost -p $Port -U $User -d postgres -c `
            "CREATE ROLE $AppUser WITH LOGIN PASSWORD '$AppPassword' NOSUPERUSER NOBYPASSRLS" | Out-Null
    }
    else {
        # The role exists but could not log in, so the stored password differs
        # from the one this run was given. Make them agree.
        Write-Host "Updating the password for existing role '$AppUser'..." -ForegroundColor Cyan
        & $Psql -h $PgHost -p $Port -U $User -d postgres -c `
            "ALTER ROLE $AppUser WITH PASSWORD '$AppPassword'" | Out-Null
    }

    # If the database exists but belongs to someone else, its TABLES do too, and
    # $AppUser could not run migrations on them. A test database is disposable,
    # so recreate it rather than reassigning ownership object by object.
    $owner = & $Psql -h $PgHost -p $Port -U $User -d postgres -tAc `
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$Database'"
    if ($owner -and $owner.Trim() -ne $AppUser) {
        Write-Host "Database '$Database' is owned by '$($owner.Trim())'; recreating it for '$AppUser'." -ForegroundColor Yellow
        & $Psql -h $PgHost -p $Port -U $User -d postgres -c "DROP DATABASE $Database WITH (FORCE)" | Out-Null
        $owner = $null
    }
    if (-not $owner) {
        Write-Host "Creating database '$Database' owned by '$AppUser'..." -ForegroundColor Cyan
        & $Psql -h $PgHost -p $Port -U $User -d postgres -c "CREATE DATABASE $Database OWNER $AppUser" | Out-Null
    }
}

Push-Location $projectRoot
try {
    if ($UnitOnly) {
        Write-Host "Running the unit layer only (no database)." -ForegroundColor Cyan
        python -m pytest -m "not postgres"
        exit $LASTEXITCODE
    }

    if ($UseDocker) {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Write-Host "Docker was not found on PATH. Drop -UseDocker to use a local PostgreSQL, or run with -UnitOnly." -ForegroundColor Red
            exit 1
        }
        docker compose -f docker-compose.test.yml up -d
        $PgHost = "localhost"; $Port = 5433
        $User = "vip_app"; $AppUser = "vip_app"; $AppPassword = "vip"
        Write-Host "Waiting for the container to accept connections..." -ForegroundColor Cyan
        Start-Sleep -Seconds 5
    }

    $psql = Find-Psql
    if (-not $psql) {
        Write-Host ""
        Write-Host "PostgreSQL client (psql) was not found." -ForegroundColor Yellow
        Write-Host "Install it once with:  winget install -e --id PostgreSQL.PostgreSQL.16"
        Write-Host "Or skip the database layers for now:  .\scripts\run-tests.ps1 -UnitOnly"
        exit 1
    }
    Write-Host "Using psql at $psql" -ForegroundColor DarkGray

    if (Test-AppLogin -Psql $psql) {
        Write-Host "Using existing '$AppUser' / '$Database'; no admin login needed." -ForegroundColor DarkGray
    }
    else {
        if (-not $Password) {
            Write-Host "Setting up '$AppUser' and '$Database'. This needs the admin account once." -ForegroundColor Cyan
            $secure = Read-Host "PostgreSQL password for user '$User'" -AsSecureString
            $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        }
        Invoke-Provisioning -Psql $psql -AdminPassword $Password
    }

    $escaped = [uri]::EscapeDataString($AppPassword)
    $env:TEST_DATABASE_URL = "postgresql+asyncpg://${AppUser}:${escaped}@${PgHost}:${Port}/${Database}"
    Write-Host "TEST_DATABASE_URL -> postgresql+asyncpg://${AppUser}:***@${PgHost}:${Port}/${Database}" -ForegroundColor DarkGray

    python -m pytest
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    Pop-Location
}
