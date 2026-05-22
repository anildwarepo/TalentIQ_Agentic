<#
.SYNOPSIS
    Run the TalentIQ data pipeline against a pre-provisioned PostgreSQL
    Flexible Server (and optionally narrow the backend UAMI's PG grants).

.DESCRIPTION
    Step 4 of the talent_infra_modules per-component deploy chain.

    Reads:
      * ..\01-postgresql\.outputs.json  (required)  — PG FQDN, deployer UPN
      * ..\02-backend\.outputs.json     (optional)  — backend UAMI for grant narrowing

    Does:
      1. Verifies az sign-in and target subscription.
      2. Verifies psql and Python (talent_data_pipeline) are installed.
      3. Acquires an OSSRDBMS bearer token for the deployer.
      4. Installs PG extensions (age, vector, pg_trgm, pg_diskann) and runs
         create_graph(<graphName>) — idempotent. Skip with -SkipExtensions.
      5. Optional idempotency check (skip with -Force): aborts if the graph
         already has Employee nodes.
      6. Invokes `python -m talent_data_pipeline.main` (with --force when
         the -Force switch is set).
      7. Optional: invokes talent_infra_v2\scripts\provision_pg_entra_roles.py
         to swap the backend UAMI from broad PG admin to narrow schema-scoped
         grants. Opt-in via -NarrowBackendGrants (see History.md for the
         rationale on why this is NOT default).
      8. Optional: restarts the active backend Container App revision via
         -RestartBackend so the backend's psycopg2 pool drops cached
         connections that may still be authenticated as PG admin.
      9. Emits a per-AGE-label vertex count summary to stdout.

    Produces no .outputs.json (terminal step in the chain).

.PARAMETER SubscriptionId
    Target subscription. Falls back to AZURE_SUBSCRIPTION_ID env var.

.PARAMETER ResourceGroup
    PG's resource group. Required for backend restart / role provisioning
    only; falls back to AZURE_RESOURCE_GROUP env var.

.PARAMETER PgServerFqdn
    Public/private FQDN of the PG flex server. Overrides 01-postgresql
    outputs.

.PARAMETER PgPrivateIp
    Optional private endpoint IPv4. When supplied, the script sets PGHOSTADDR
    so psql / role provisioning bypass DNS while keeping the FQDN for TLS.
    NOTE: the data pipeline itself does NOT read PGHOSTADDR — if PG is
    private-link-only, you must have a hosts-file override mapping PG FQDN
    to this IP for the pipeline to connect.

.PARAMETER PgDatabase
    Database name. Default: postgres.

.PARAMETER GraphName
    AGE graph name. Defaults to the value in 01-postgresql/.outputs.json
    if present, otherwise "talent_graph".

.PARAMETER DeployerUpn
    Entra UPN to authenticate as PG admin. Defaults to deployerEntraUpn
    from 01-postgresql/.outputs.json, then the current signed-in az user.

.PARAMETER PythonExe
    Python interpreter to use. Default: python (on PATH).

.PARAMETER DataPipelinePath
    Path to the talent_data_pipeline package. Default: ..\..\talent_data_pipeline.

.PARAMETER SkipExtensions
    Skip step 4 (extensions + create_graph). Use when extensions are already
    installed and you only want to re-run the loader.

.PARAMETER NarrowBackendGrants
    OPT-IN. Invoke provision_pg_entra_roles.py to downgrade the backend UAMI
    from PG admin (broad) to schema-scoped grants (narrow). Requires
    ..\02-backend\.outputs.json. Defaulting to OFF preserves the working
    fallback path on networks that block direct PG (port 5432) access from
    the deployer — see history.md.

.PARAMETER RestartBackend
    When set with -NarrowBackendGrants, restart the active backend Container
    App revision so its pool reconnects with the new role.

.PARAMETER Force
    Bypass the idempotency check AND pass --force to the pipeline (full
    regenerate + reload).

.EXAMPLE
    # First-time load
    ./deploy.ps1

.EXAMPLE
    # Re-run after iterating on pipeline code
    ./deploy.ps1 -SkipExtensions

.EXAMPLE
    # Full regenerate (pipeline drops + reloads its own tables)
    ./deploy.ps1 -Force

.EXAMPLE
    # Production hand-off: narrow grants and restart backend
    ./deploy.ps1 -NarrowBackendGrants -RestartBackend
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$PgServerFqdn,
    [string]$PgPrivateIp,
    [string]$PgDatabase = "postgres",
    [string]$GraphName,
    [string]$DeployerUpn,
    [string]$PythonExe = "python",
    [string]$DataPipelinePath = "..\..\talent_data_pipeline",
    [switch]$SkipExtensions,
    [switch]$NarrowBackendGrants,
    [switch]$RestartBackend,
    [switch]$Force
)

# ──────────────────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"
$ScriptRoot = $PSScriptRoot

. (Join-Path $ScriptRoot "..\shared\common.ps1")

# Pin script-relative paths (caller's CWD shouldn't matter).
$PgOutputsPath      = (Join-Path $ScriptRoot "..\01-postgresql\.outputs.json")
$BackendOutputsPath = (Join-Path $ScriptRoot "..\02-backend\.outputs.json")
$PipelineFullPath   = (Resolve-Path -LiteralPath (Join-Path $ScriptRoot $DataPipelinePath) -ErrorAction SilentlyContinue)
if (-not $PipelineFullPath) {
    Write-Fail "Could not resolve -DataPipelinePath '$DataPipelinePath' relative to script."
    exit 1
}
$ProvisionRolesScript = (Join-Path $ScriptRoot "..\..\talent_infra_v2\scripts\provision_pg_entra_roles.py")

# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — Az sign-in
# ──────────────────────────────────────────────────────────────────────────────
$acct = Test-AzLoggedIn

# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Read upstream outputs
# ──────────────────────────────────────────────────────────────────────────────
Write-Step "Reading upstream module outputs"

if (-not (Test-Path -LiteralPath $PgOutputsPath)) {
    Write-Fail "Required file not found: $PgOutputsPath"
    Write-Info "Run 01-postgresql\deploy.ps1 first, or synthesize the file manually"
    Write-Info "(schema in DEPLOYMENT-ORDER.md > 'Pre-step' section)."
    exit 1
}
try {
    $pgOutputs = Get-Content -Raw -LiteralPath $PgOutputsPath | ConvertFrom-Json
} catch {
    Write-Fail "Could not parse $PgOutputsPath as JSON: $_"
    exit 1
}
Write-Success "01-postgresql outputs loaded"

$backendOutputs = $null
if (Test-Path -LiteralPath $BackendOutputsPath) {
    try {
        $backendOutputs = Get-Content -Raw -LiteralPath $BackendOutputsPath | ConvertFrom-Json
        Write-Success "02-backend outputs loaded (optional)"
    } catch {
        Write-Warn "Could not parse $BackendOutputsPath as JSON: $_ — backend-dependent steps will be skipped"
    }
} else {
    Write-Info "02-backend\.outputs.json not present — backend grant-narrowing + restart will be skipped"
}

if ($NarrowBackendGrants -and -not $backendOutputs) {
    Write-Fail "-NarrowBackendGrants requires $BackendOutputsPath to exist."
    exit 1
}
if ($RestartBackend -and -not $NarrowBackendGrants) {
    Write-Warn "-RestartBackend is only meaningful with -NarrowBackendGrants; will still attempt the restart"
}
if ($RestartBackend -and -not $backendOutputs) {
    Write-Fail "-RestartBackend requires $BackendOutputsPath to exist."
    exit 1
}

# ──────────────────────────────────────────────────────────────────────────────
# Phase 3 — Resolve parameters
# ──────────────────────────────────────────────────────────────────────────────
Write-Step "Resolving parameters"

$SubscriptionId = Get-ParameterValue `
    -Name    "Subscription ID" `
    -Value   $SubscriptionId `
    -EnvVar  "AZURE_SUBSCRIPTION_ID" `
    -Default $acct.id

# ResourceGroup is only strictly needed when restarting the backend container
# app. Skip the prompt otherwise so a vanilla -SkipExtensions run does not
# require it.
if ($NarrowBackendGrants -or $RestartBackend) {
    $ResourceGroup = Get-ParameterValue `
        -Name    "Resource group (backend / PG)" `
        -Value   $ResourceGroup `
        -EnvVar  "AZURE_RESOURCE_GROUP"
}

# PG FQDN — prefer override → outputs.postgresqlServerFqdn → outputs.postgresqlPrivateFqdn
if (-not $PgServerFqdn) {
    if ($pgOutputs.postgresqlServerFqdn) {
        $PgServerFqdn = [string]$pgOutputs.postgresqlServerFqdn
    } elseif ($pgOutputs.postgresqlPrivateFqdn) {
        $PgServerFqdn = [string]$pgOutputs.postgresqlPrivateFqdn
    }
}
if (-not $PgServerFqdn) {
    Write-Fail "Could not determine PG FQDN — pass -PgServerFqdn or add postgresqlServerFqdn to 01 outputs."
    exit 1
}

# PG private IP — optional override → outputs.postgresqlPrivateIp
if (-not $PgPrivateIp -and $pgOutputs.postgresqlPrivateIp) {
    $PgPrivateIp = [string]$pgOutputs.postgresqlPrivateIp
}

# Graph name — explicit → outputs.graphName → default
if (-not $GraphName) {
    if ($pgOutputs.graphName) {
        $GraphName = [string]$pgOutputs.graphName
    } else {
        $GraphName = "talent_graph"
    }
}

# Deployer UPN — explicit → outputs.deployerEntraUpn → signed-in user
if (-not $DeployerUpn) {
    if ($pgOutputs.deployerEntraUpn) {
        $DeployerUpn = [string]$pgOutputs.deployerEntraUpn
    } else {
        $DeployerUpn = [string]$acct.user.name
    }
}

Write-Info "Subscription:      $SubscriptionId"
if ($ResourceGroup) { Write-Info "Resource group:    $ResourceGroup" }
Write-Info "PG FQDN:           $PgServerFqdn"
if ($PgPrivateIp)   { Write-Info "PG private IP:     $PgPrivateIp (psql will use hostaddr bypass)" }
Write-Info "PG database:       $PgDatabase"
Write-Info "Graph name:        $GraphName"
Write-Info "Deployer UPN:      $DeployerUpn"
Write-Info "Data pipeline:     $PipelineFullPath"

Test-AzSubscription -SubscriptionId $SubscriptionId

# ──────────────────────────────────────────────────────────────────────────────
# Phase 4 — Prerequisite checks (psql, python, pipeline package)
# ──────────────────────────────────────────────────────────────────────────────
Write-Step "Checking psql is on PATH"
$psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psqlCmd) {
    Write-Fail "psql not found on PATH."
    Write-Info "Install via:"
    Write-Info "  choco install postgresql --params '/Password:notused' --no-progress"
    Write-Info "OR:"
    Write-Info "  winget install PostgreSQL.PostgreSQL.16"
    Write-Info "Then ensure 'C:\Program Files\PostgreSQL\16\bin' is on PATH and restart your shell."
    exit 2
}
Write-Success "psql found at $($psqlCmd.Source)"

Write-Step "Checking Python interpreter '$PythonExe'"
$pyVersion = Invoke-Native { & $PythonExe --version 2>&1 }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Could not run '$PythonExe --version'. Install Python 3.11+ or pass -PythonExe <path>."
    exit 2
}
Write-Success "Python: $pyVersion"

Write-Step "Checking talent_data_pipeline is importable"
$importCheck = Invoke-Native {
    Push-Location -LiteralPath $PipelineFullPath
    try {
        & $PythonExe -c "import talent_data_pipeline.main" 2>&1
    } finally {
        Pop-Location
    }
}
if ($LASTEXITCODE -ne 0) {
    Write-Fail "talent_data_pipeline is not installed in this Python environment."
    Write-Info "Last error: $importCheck"
    Write-Info ""
    Write-Info "Install with:"
    Write-Info "  cd talent_data_pipeline"
    Write-Info "  python -m venv .venv"
    Write-Info "  .\.venv\Scripts\Activate.ps1"
    Write-Info "  pip install -e ."
    Write-Info ""
    Write-Info "Then re-run this script with -PythonExe pointing at the venv's python.exe,"
    Write-Info "or with the venv already activated in this shell."
    exit 2
}
Write-Success "talent_data_pipeline.main is importable"

# ──────────────────────────────────────────────────────────────────────────────
# Phase 5 — Acquire PG access token (OSSRDBMS scope)
# ──────────────────────────────────────────────────────────────────────────────
Write-Step "Acquiring PostgreSQL Entra access token (oss-rdbms scope)"
$pgToken = (Invoke-Native {
    az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv 2>$null `
        | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
}) -join ""
$pgToken = $pgToken.Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($pgToken)) {
    Write-Fail "Could not acquire PG access token. Re-run 'az login' and confirm you can run:"
    Write-Info "  az account get-access-token --resource-type oss-rdbms"
    exit 1
}
Write-Success "Token acquired ($($pgToken.Length) chars)"

# ──────────────────────────────────────────────────────────────────────────────
# Phase 6 — Env var setup with deterministic restoration
# ──────────────────────────────────────────────────────────────────────────────
# We snapshot every PG* var we touch up-front, then restore in a finally so the
# caller's shell is unchanged after the script returns (success OR failure).
$envVarsToManage = @(
    "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER",
    "PGPASSWORD", "PGSSLMODE", "PGSSLROOTCERT",
    "GRAPH_NAME",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_EMBEDDING_DIMENSIONS",
    "FORCE_REGENERATE",
    "EMPLOYEE_COUNT", "BATCH_SIZE", "RANDOM_SEED"
)
$envSnapshot = @{}
foreach ($n in $envVarsToManage) {
    $envSnapshot[$n] = [Environment]::GetEnvironmentVariable($n, "Process")
}

function Restore-EnvSnapshot {
    foreach ($n in $envSnapshot.Keys) {
        [Environment]::SetEnvironmentVariable($n, $envSnapshot[$n], "Process")
    }
}

# Wrap the rest of the script in a try/finally for env restoration.
try {

    $env:PGHOST     = $PgServerFqdn
    if ($PgPrivateIp) { $env:PGHOSTADDR = $PgPrivateIp } else { Remove-Item Env:PGHOSTADDR -ErrorAction SilentlyContinue }
    $env:PGPORT     = "5432"
    $env:PGDATABASE = $PgDatabase
    $env:PGUSER     = $DeployerUpn
    $env:PGPASSWORD = $pgToken
    $env:PGSSLMODE  = "require"

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 7 — Install extensions + create graph (skippable)
    # ──────────────────────────────────────────────────────────────────────────
    if ($SkipExtensions) {
        Write-Step "Skipping extension install (-SkipExtensions)"
    } else {
        Write-Step "Installing PG extensions + create_graph('$GraphName')"

        # SQL is piped via stdin so we avoid -c quoting issues entirely.
        # create_graph() raises 'graph "<name>" already exists' on re-run;
        # the DO block catches that one error code and lets everything else
        # propagate.
        $sql = @"
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pg_diskann;
LOAD 'age';
DO `$`$
BEGIN
    PERFORM ag_catalog.create_graph('$GraphName');
EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%already exists%' THEN
        RAISE NOTICE 'Graph "$GraphName" already exists, leaving in place';
    ELSE
        RAISE;
    END IF;
END
`$`$;
"@

        $psqlOutput = $sql | & psql `
            --no-psqlrc `
            --set ON_ERROR_STOP=1 `
            --quiet `
            2>&1
        $psqlExit = $LASTEXITCODE
        $psqlOutput | ForEach-Object { Write-Info $_ }
        if ($psqlExit -ne 0) {
            Write-Fail "psql failed installing extensions (exit $psqlExit)"
            exit 1
        }
        Write-Success "Extensions installed and graph ready"
    }

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 8 — Idempotency check
    # ──────────────────────────────────────────────────────────────────────────
    if ($Force) {
        Write-Step "Skipping idempotency check (-Force)"
    } else {
        Write-Step "Checking whether graph already has Employee nodes"
        # COALESCE handles the case where the label exists but the table is empty.
        $countSql = @"
SET search_path = ag_catalog, '`$user`', public;
SELECT COALESCE(SUM(cnt), 0)::bigint
FROM ag_catalog.cypher('$GraphName', `$cy`$ MATCH (n:Employee) RETURN count(n) `$cy`$)
AS (cnt agtype);
"@
        $countOut = $countSql | & psql `
            --no-psqlrc `
            --set ON_ERROR_STOP=0 `
            --tuples-only `
            --no-align `
            --quiet `
            2>&1
        $countExit = $LASTEXITCODE
        $employeeCount = 0
        if ($countExit -eq 0) {
            $countLine = ($countOut | Where-Object { $_ -match '^\s*\d+\s*$' } | Select-Object -First 1)
            if ($countLine) {
                $employeeCount = [int64]$countLine.Trim()
            }
        } else {
            # Label likely does not exist yet (empty graph). Treat as zero and continue.
            Write-Info "Employee label not queryable yet — assuming empty graph"
        }

        if ($employeeCount -gt 0) {
            Write-Warn "Graph already has $employeeCount Employee nodes."
            if (-not (Confirm-Action -Message "Re-load anyway?")) {
                Write-Info "User declined re-load. Exiting cleanly."
                exit 0
            }
        } else {
            Write-Success "Graph is empty — proceeding with full load"
        }
    }

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 9 — Run the data pipeline
    # ──────────────────────────────────────────────────────────────────────────
    Write-Step "Running talent_data_pipeline.main"

    # Pipeline env. The pipeline's pg_entra.pg_connect() fetches its OWN token
    # via DefaultAzureCredential at every connect, so PGPASSWORD is irrelevant
    # to it (we leave it set for psql usage in later phases).
    #
    # IMPORTANT: talent_data_pipeline.config reads PGHOST (not PGHOSTADDR). If
    # PG is private-link-only and DNS resolves PGHOST to a public IP the
    # deployer cannot reach, the pipeline will fail Phase 1 (connectivity).
    # The documented workaround is a hosts-file entry mapping PGHOST → private
    # IP. See talent_data_pipeline/DATA_LOADING.md and 04-data-loading/README.md.
    if ($PgPrivateIp) {
        Write-Warn "PG private IP supplied, but talent_data_pipeline does NOT honor PGHOSTADDR."
        Write-Info "If '$PgServerFqdn' does not resolve to a reachable IP for the pipeline,"
        Write-Info "add a hosts-file entry: $PgPrivateIp  $PgServerFqdn"
    }

    $env:GRAPH_NAME = $GraphName

    # Carry the embedding endpoint forward if it was set in the caller's env
    # (pipeline reads it from AZURE_OPENAI_ENDPOINT). We do NOT prompt — the
    # pipeline's connectivity test will fail clearly if it is missing.
    if ($Force) { $env:FORCE_REGENERATE = "true" }

    $pipelineArgs = @("-m", "talent_data_pipeline.main")
    if ($Force) { $pipelineArgs += "--force" }

    Push-Location -LiteralPath $PipelineFullPath
    try {
        & $PythonExe @pipelineArgs
        $pipelineExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($pipelineExit -ne 0) {
        Write-Fail "talent_data_pipeline failed (exit $pipelineExit)"
        exit 1
    }
    Write-Success "talent_data_pipeline completed"

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 10 — Optional grant narrowing
    # ──────────────────────────────────────────────────────────────────────────
    $grantsNarrowed = $false
    if ($NarrowBackendGrants) {
        Write-Step "Narrowing backend UAMI's PG grants (provision_pg_entra_roles.py)"

        if (-not (Test-Path -LiteralPath $ProvisionRolesScript)) {
            Write-Fail "Provisioning script not found at $ProvisionRolesScript"
            exit 1
        }

        $backendUamiName = [string]$backendOutputs.backendUamiName
        $backendUamiOid  = [string]$backendOutputs.backendUamiPrincipalId
        if ([string]::IsNullOrWhiteSpace($backendUamiName) -or [string]::IsNullOrWhiteSpace($backendUamiOid)) {
            Write-Fail "02-backend outputs missing backendUamiName or backendUamiPrincipalId."
            exit 1
        }

        $principals = @(@{
            name = $backendUamiName
            oid  = $backendUamiOid
            type = "service"
        })
        $principalsJson = ConvertTo-Json -InputObject $principals -Compress -Depth 4

        $provArgs = @(
            $ProvisionRolesScript,
            "--host",       $PgServerFqdn,
            "--database",   $PgDatabase,
            "--sslmode",    "require",
            "--admin-upn",  $DeployerUpn,
            "--graph-name", $GraphName,
            "--principals", $principalsJson
        )
        if ($PgPrivateIp) {
            $provArgs += @("--hostaddr", $PgPrivateIp)
        }

        & $PythonExe @provArgs
        $provExit = $LASTEXITCODE
        if ($provExit -ne 0) {
            Write-Fail "provision_pg_entra_roles.py failed (exit $provExit)"
            exit 1
        }
        Write-Success "Backend UAMI '$backendUamiName' narrowed to schema-scoped grants"
        $grantsNarrowed = $true

        if (-not $RestartBackend) {
            Write-Warn "Backend container app may still hold pool connections authenticated as"
            Write-Warn "PG admin (the broad fallback). Pass -RestartBackend, or run manually:"
            Write-Warn "  az containerapp revision restart -n $($backendOutputs.backendContainerAppName) -g <rg> --revision <active>"
        }
    }

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 11 — Optional backend restart
    # ──────────────────────────────────────────────────────────────────────────
    $backendRestarted = $false
    if ($RestartBackend -and $backendOutputs) {
        Write-Step "Restarting backend Container App's active revision"
        $backendAppName = [string]$backendOutputs.backendContainerAppName
        if ([string]::IsNullOrWhiteSpace($backendAppName)) {
            Write-Fail "backend outputs missing backendContainerAppName."
            exit 1
        }

        $activeRev = (Invoke-Native {
            az containerapp show `
                --name $backendAppName `
                --resource-group $ResourceGroup `
                --query properties.latestRevisionName `
                -o tsv 2>$null `
            | Where-Object { $_ -notmatch '^(WARNING|ERROR)' }
        }) -join ""
        $activeRev = $activeRev.Trim()
        if ([string]::IsNullOrEmpty($activeRev)) {
            Write-Fail "Could not discover active revision for $backendAppName in $ResourceGroup."
            exit 1
        }
        Write-Info "Active revision: $activeRev"

        Invoke-Native {
            az containerapp revision restart `
                --name $backendAppName `
                --resource-group $ResourceGroup `
                --revision $activeRev `
                --output none 2>&1 | Out-Null
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "az containerapp revision restart failed (exit $LASTEXITCODE)"
            exit 1
        }
        Write-Success "Restarted $backendAppName/$activeRev"
        $backendRestarted = $true
    }

    # ──────────────────────────────────────────────────────────────────────────
    # Phase 12 — Summary (vertex counts per AGE label)
    # ──────────────────────────────────────────────────────────────────────────
    Write-Step "Final vertex counts per AGE label"

    $labels = @(
        "Employee", "Skill", "SkillDomain", "Certification", "Language",
        "ServiceLine", "Offering", "Manager", "University",
        "Client", "Project", "Role", "Location", "Country", "Subregion"
    )
    $summary = [ordered]@{}

    foreach ($lbl in $labels) {
        $cntSql = @"
SET search_path = ag_catalog, '`$user`', public;
SELECT COALESCE(SUM(cnt), 0)::bigint
FROM ag_catalog.cypher('$GraphName', `$cy`$ MATCH (n:$lbl) RETURN count(n) `$cy`$)
AS (cnt agtype);
"@
        $out = $cntSql | & psql `
            --no-psqlrc `
            --set ON_ERROR_STOP=0 `
            --tuples-only `
            --no-align `
            --quiet `
            2>&1
        if ($LASTEXITCODE -eq 0) {
            $line = ($out | Where-Object { $_ -match '^\s*\d+\s*$' } | Select-Object -First 1)
            $summary[$lbl] = if ($line) { [int64]$line.Trim() } else { 0 }
        } else {
            # Label may not exist on a freshly created graph — record as null.
            $summary[$lbl] = $null
        }
    }

    Write-Host ""
    Write-Host "  Vertex counts (graph '$GraphName'):" -ForegroundColor Cyan
    foreach ($k in $summary.Keys) {
        $v = $summary[$k]
        $display = if ($null -eq $v) { "    (label not found)" } else { ("{0,12:N0}" -f $v) }
        Write-Host ("    {0,-16} {1}" -f $k, $display)
    }
    Write-Host ""
    Write-Host "  Grants narrowed:   $grantsNarrowed" -ForegroundColor Cyan
    Write-Host "  Backend restarted: $backendRestarted" -ForegroundColor Cyan
    Write-Host ""
    Write-Success "04-data-loading complete"

} finally {
    Restore-EnvSnapshot
}
