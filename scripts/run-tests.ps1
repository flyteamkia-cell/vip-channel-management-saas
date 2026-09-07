<#
.SYNOPSIS
    Run the test suite on Windows, with or without Docker.

.DESCRIPTION
    The integration and e2e layers need a real PostgreSQL. This script finds one
    the way a Windows box usually has one -- a native install from the EDB
    installer or winget -- creates the test database if it is missing, and runs
    pytest with TEST_DATABASE_URL set.

    Docker is optional. Use -UseDocker only if Docker Desktop is running.

.EXAMPLE
    .\scripts\run-tests.ps1 -UnitOnly
    Unit layer only. No database required.

.EXAMPLE
    .\scripts\run-tests.ps1 -Password mysecret
    Uses the local PostgreSQL on localhost:5432 as user "postgres".

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
    [switch]$UnitOnly,
    [switch]$UseDocker
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    if ($UnitOnly) {
        Write-Host "Running the unit layer only (no database)." -ForegroundColor Cyan
        python -m pytest -m "not postgres"
        exit $LASTEXITCODE
    }

    if ($UseDocker) {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw "Docker was not found on PATH. Drop -UseDocker to use a local PostgreSQL, or run with -UnitOnly."
        }
        docker compose -f docker-compose.test.yml up -d
        $PgHost = "localhost"; $Port = 5433; $User = "vip"; $Password = "vip"
        Write-Host "Waiting for the container to accept connections..." -ForegroundColor Cyan
        Start-Sleep -Seconds 5
    }

    # ---- locate psql -------------------------------------------------------
    $psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
    if (-not $psql) {
        $candidates = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        if ($candidates) { $psql = $candidates[0].FullName }
    }
    if (-not $psql) {
        Write-Host ""
        Write-Host "PostgreSQL client (psql) was not found." -ForegroundColor Yellow
        Write-Host "Install it once with:  winget install -e --id PostgreSQL.PostgreSQL.16"
        Write-Host "Or skip the database layers for now:  .\scripts\run-tests.ps1 -UnitOnly"
        exit 1
    }
    Write-Host "Using psql at $psql" -ForegroundColor DarkGray

    if (-not $Password) {
        $secure = Read-Host "PostgreSQL password for user '$User'" -AsSecureString
        $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
    $env:PGPASSWORD = $Password

    # ---- create the test database if it is missing -------------------------
    $exists = & $psql -h $PgHost -p $Port -U $User -d postgres -tAc `
        "SELECT 1 FROM pg_database WHERE datname = '$Database'"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not reach PostgreSQL at ${PgHost}:${Port} as '$User'. Check that the service is running and the password is correct."
    }
    if ($exists -ne "1") {
        Write-Host "Creating database '$Database'..." -ForegroundColor Cyan
        & $psql -h $PgHost -p $Port -U $User -d postgres -c "CREATE DATABASE $Database" | Out-Null
    }

    # ---- run ---------------------------------------------------------------
    $escaped = [uri]::EscapeDataString($Password)
    $env:TEST_DATABASE_URL = "postgresql+asyncpg://${User}:${escaped}@${PgHost}:${Port}/${Database}"
    Write-Host "TEST_DATABASE_URL -> postgresql+asyncpg://${User}:***@${PgHost}:${Port}/${Database}" -ForegroundColor DarkGray

    python -m pytest
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    Pop-Location
}
