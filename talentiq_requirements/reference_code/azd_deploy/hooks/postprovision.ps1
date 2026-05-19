<#
.SYNOPSIS
    Post-provision hook to initialize PostgreSQL AGE, build containers, and deploy apps in sequence.
#>

param(
    [string]$McpServerPath = "../../mcp_server",
    [string]$FastApiPath = "../../af_fastapi",
    [string]$WebappPath = "../../webapp"
)

$ErrorActionPreference = "Stop"

# Guard against recursive execution: when Invoke-ContainerAppsDeploy calls
# 'azd provision --no-prompt', azd re-triggers hooks.  Skip the nested run.
if ($env:AZD_POSTPROVISION_PHASE -eq "1") {
    Write-Host "Skipping nested postprovision hook (provision phase in progress)."
    exit 0
}

Write-Host "=========================================="
Write-Host "Post-provision hook starting..."
Write-Host "=========================================="

function Get-AzdEnvValue {
    param([string]$Name)
    # Use cmd /c to avoid PS5.1 NativeCommandError on azd stderr warnings
    $result = (cmd /c "azd env get-value $Name 2>nul")
    if ($result) { $result.Trim() } else { "" }
}

function Set-AzdEnvValue {
    param(
        [string]$Name,
        [string]$Value
    )
    # Temporarily relax ErrorActionPreference so azd stderr warnings
    # (e.g., version-out-of-date) don't cause PS5.1 to throw.
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & azd env set $Name "$Value" 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $savedEAP
    }
}

# Helper: Run a native command without PS5.1 NativeCommandError on stderr.
# Temporarily lowers ErrorActionPreference so warnings/info on stderr don't
# become terminating errors.
function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command
    } finally {
        $ErrorActionPreference = $savedEAP
    }
}

function Get-FolderHash {
    param([string]$FolderPath)

    $files = Get-ChildItem -Path $FolderPath -Recurse -File |
        Where-Object { $_.FullName -notmatch '(__pycache__|node_modules|\.venv|\.git|\.(pyc|pyo|egg-info))' } |
        Sort-Object FullName

    $hashInput = ""
    foreach ($file in $files) {
        $relativePath = $file.FullName.Substring($FolderPath.Length)
        $fileHash = (Get-FileHash -Path $file.FullName -Algorithm MD5).Hash
        $hashInput += "$relativePath`:$fileHash`n"
    }

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($hashInput)
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $hashBytes = $md5.ComputeHash($bytes)
    [BitConverter]::ToString($hashBytes) -replace '-', ''
}

function Test-BuildNeeded {
    param(
        [string]$FolderPath,
        [string]$HashEnvVarName
    )

    $currentHash = Get-FolderHash -FolderPath $FolderPath
    $storedHash = Get-AzdEnvValue $HashEnvVarName

    if ($currentHash -eq $storedHash) {
        return @{ Needed = $false; Hash = $currentHash }
    }

    return @{ Needed = $true; Hash = $currentHash }
}

function Save-FolderHash {
    param(
        [string]$HashEnvVarName,
        [string]$Hash
    )
    Set-AzdEnvValue -Name $HashEnvVarName -Value $Hash
}

function Test-DockerAvailable {
    <#
    .SYNOPSIS
        Returns $true if Docker Desktop (or any local Docker daemon) is reachable.
    #>
    try {
        $verOutput = & docker version --format '{{.Server.Version}}' 2>&1
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($verOutput)) {
            Write-Host "Docker Desktop detected (server version: $verOutput)"
            return $true
        }
    } catch { }
    return $false
}

function Invoke-DockerBuild {
    <#
    .SYNOPSIS
        Build a container image locally with Docker Desktop and push it to ACR.
    #>
    param(
        [string]$RegistryName,
        [string]$LoginServer,
        [string]$SourcePath,
        [string]$ImageName,
        [string]$ImageTag,
        [string]$Label,
        [string[]]$BuildArgs = @()
    )

    Push-Location $SourcePath
    try {
        Write-Host "  Building $Label container locally with Docker Desktop..."

        # Log in to ACR so we can push
        Write-Host "  Logging into ACR $RegistryName..."
        Invoke-NativeCommand { az acr login --name $RegistryName 2>&1 | Out-Null }

        $fullTagged = "${LoginServer}/${ImageName}:${ImageTag}"
        $fullLatest = "${LoginServer}/${ImageName}:latest"

        $dockerArgs = @("build", "-t", $fullTagged, "-t", $fullLatest, "-f", "Dockerfile",
                        "--provenance=false", "--sbom=false")
        foreach ($arg in $BuildArgs) {
            $dockerArgs += "--build-arg"
            $dockerArgs += $arg
        }
        $dockerArgs += "."

        & docker @dockerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Docker build failed for $Label (exit code $LASTEXITCODE)"
        }

        Write-Host "  Pushing $Label image to $LoginServer..."
        & docker push $fullTagged
        if ($LASTEXITCODE -ne 0) {
            throw "Docker push failed for ${fullTagged} (exit code $LASTEXITCODE)"
        }
        & docker push $fullLatest
        if ($LASTEXITCODE -ne 0) {
            throw "Docker push failed for ${fullLatest} (exit code $LASTEXITCODE)"
        }

        Write-Host "  $Label image pushed successfully."
    } finally {
        Pop-Location
    }
}

function Invoke-AcrBuild {
    param(
        [string]$RegistryName,
        [string]$SourcePath,
        [string]$ImageName,
        [string]$ImageTag,
        [string]$Label,
        [string[]]$BuildArgs = @()
    )

    Push-Location $SourcePath
    try {
        Write-Host "  Building $Label container in ACR $RegistryName (this may take several minutes)..."

        # Start ACR build without streaming logs (streaming can crash in PS5/cp1252).
        # We'll poll run status and then print full build logs from log artifact URL.
        $azArgs = @("acr", "build", "--registry", $RegistryName,
                    "--image", "${ImageName}:${ImageTag}",
                    "--image", "${ImageName}:latest",
                    "--file", "Dockerfile", ".",
                    "--no-logs", "--only-show-errors", "--output", "json")
        foreach ($arg in $BuildArgs) {
            $azArgs += "--build-arg"
            $azArgs += $arg
        }

        $savedEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $buildResponse = (& az @azArgs 2>&1 | Out-String).Trim()
            $buildExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedEAP
        }

        if ($buildExitCode -ne 0) {
            throw "ACR build failed for $Label (exit code $buildExitCode)"
        }

        $buildObj = $null
        try {
            $buildObj = $buildResponse | ConvertFrom-Json
        } catch {
            throw "Unable to parse ACR build response for $Label. Raw response: $buildResponse"
        }

        $runId = $null
        if ($buildObj.PSObject.Properties.Name -contains "runId") {
            $runId = $buildObj.runId
        }
        if ([string]::IsNullOrEmpty($runId) -and ($buildObj.PSObject.Properties.Name -contains "id")) {
            if ($buildObj.id -match '/runs/([^/\s]+)$') {
                $runId = $Matches[1]
            }
        }
        if ([string]::IsNullOrEmpty($runId)) {
            throw "Could not determine ACR run ID for $Label build. Response: $buildResponse"
        }

        Write-Host "  ACR build queued. Run ID: $runId"

        $finalRun = $null
        $lastStatus = ""
        $pollCount = 0
        $maxPollCount = 180
        while ($true) {
            $pollCount++
            if ($pollCount -gt $maxPollCount) {
                throw "Timed out waiting for ACR build run status for $Label (runId: $runId)."
            }
            $savedEAP = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $runJson = (& az acr task show-run --registry $RegistryName --run-id $runId --only-show-errors --output json 2>&1 | Out-String).Trim()
                $showRunExitCode = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $savedEAP
            }

            if ($showRunExitCode -ne 0) {
                if (($pollCount % 3) -eq 0) {
                    Write-Host "  Waiting for run status... (runId: $runId)"
                }
                Start-Sleep -Seconds 5
                continue
            }

            try {
                $runObj = $runJson | ConvertFrom-Json
            } catch {
                if (($pollCount % 3) -eq 0) {
                    Write-Host "  Waiting for run status... (runId: $runId)"
                }
                Start-Sleep -Seconds 5
                continue
            }

            $status = [string]$runObj.status
            if ($status -ne $lastStatus) {
                $timeStamp = Get-Date -Format "HH:mm:ss"
                Write-Host "  [$timeStamp] ACR build status: $status"
                $lastStatus = $status
            }

            if ($status -in @("Succeeded", "Failed", "Canceled", "Error")) {
                $finalRun = $runObj
                break
            }

            Start-Sleep -Seconds 8
        }

        if ($null -ne $finalRun -and -not [string]::IsNullOrEmpty($finalRun.logArtifactLink)) {
            Write-Host ""
            Write-Host "  Fetching ACR build logs for $Label..."
            try {
                $logResponse = Invoke-WebRequest -Uri $finalRun.logArtifactLink -UseBasicParsing -TimeoutSec 180
                $logContent = [string]$logResponse.Content
                if (-not [string]::IsNullOrEmpty($logContent)) {
                    Write-Host "  ----- BEGIN ACR BUILD LOG ($Label) -----"
                    foreach ($line in ($logContent -split "`r?`n")) {
                        Write-Host $line
                    }
                    Write-Host "  ----- END ACR BUILD LOG ($Label) -----"
                }
            } catch {
                Write-Host "  WARNING: Could not fetch ACR log artifact for ${Label}: $($_.Exception.Message)"
            }
            Write-Host ""
        }

        if ($null -eq $finalRun -or $finalRun.status -ne "Succeeded") {
            $finalStatus = if ($null -ne $finalRun) { [string]$finalRun.status } else { "Unknown" }
            throw "ACR build failed for $Label (status: $finalStatus)"
        }
    } finally {
        Pop-Location
    }
}

function Wait-PostgresqlReady {
    param(
        [string]$ResourceGroup,
        [string]$ServerName,
        [int]$MaxAttempts = 60,
        [int]$DelaySeconds = 10
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $state = Invoke-NativeCommand { az postgres flexible-server show --resource-group $ResourceGroup --name $ServerName --query "state" -o tsv 2>&1 | Where-Object { $_ -notmatch '^WARNING' } }
        if ($LASTEXITCODE -eq 0 -and $state -eq "Ready") {
            return
        }

        Write-Host "Waiting for PostgreSQL server to be Ready (attempt $attempt/$MaxAttempts, current state: $state)..."
        Start-Sleep -Seconds $DelaySeconds
    }

    throw "PostgreSQL server did not reach Ready state in time."
}

function Ensure-PostgresqlAllowAllIps {
    param(
        [string]$ResourceGroup,
        [string]$ServerName
    )

    if ([string]::IsNullOrEmpty($ResourceGroup) -or [string]::IsNullOrEmpty($ServerName)) {
        return
    }

    Write-Host "Opening PostgreSQL firewall to all IPs for data loading..."
    Invoke-NativeCommand { az postgres flexible-server firewall-rule create --resource-group $ResourceGroup --name $ServerName --rule-name "AllowAllIps" --start-ip-address "0.0.0.0" --end-ip-address "255.255.255.255" 2>&1 | Out-Null }
}

function Invoke-WithRetry {
    param(
        [scriptblock]$Action,
        [string]$Operation,
        [int]$MaxAttempts = 12,
        [int]$DelaySeconds = 10
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            & $Action
            return
        }
        catch {
            if ($attempt -eq $MaxAttempts) {
                throw "${Operation} failed after ${MaxAttempts} attempts. Last error: $($_.Exception.Message)"
            }

            Write-Host "${Operation} failed (attempt $attempt/$MaxAttempts). Retrying in $DelaySeconds seconds..."
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Initialize-PostgresqlAgeAndData {
    param(
        [string]$ResourceGroup,
        [string]$ServerName,
        [string]$AdminUser,
        [string]$AdminPassword,
        [string]$ServerFqdn,
        [string]$GraphName
    )

    if ([string]::IsNullOrEmpty($ServerName) -or [string]::IsNullOrEmpty($ResourceGroup) -or [string]::IsNullOrEmpty($AdminPassword)) {
        Write-Host "Skipping PostgreSQL AGE/data initialization (missing required values)."
        return
    }

    $effectiveAdminUser = if (-not [string]::IsNullOrEmpty($AdminUser)) { $AdminUser } else { "pgadmin" }
    $effectiveGraphName = if (-not [string]::IsNullOrEmpty($GraphName)) { $GraphName } else { "customer_graph" }

    Write-Host "Configuring PostgreSQL server parameters for AGE..."
    Invoke-NativeCommand { az postgres flexible-server parameter set --resource-group $ResourceGroup --server-name $ServerName --name azure.extensions --value AGE 2>&1 | Out-Null }
    Invoke-NativeCommand { az postgres flexible-server parameter set --resource-group $ResourceGroup --server-name $ServerName --name shared_preload_libraries --value age 2>&1 | Out-Null }

    Write-Host "Restarting PostgreSQL server..."
    Invoke-NativeCommand { az postgres flexible-server restart --resource-group $ResourceGroup --name $ServerName 2>&1 | Out-Null }
    Wait-PostgresqlReady -ResourceGroup $ResourceGroup -ServerName $ServerName

    Write-Host "Enabling AGE extension in postgres database..."
    $scriptDir = $PSScriptRoot
    $repoRoot = Resolve-Path (Join-Path $scriptDir "../..")
    $customerGraphLoaderScript = Join-Path $repoRoot "postgresql_age/load_data/customer_graph/load_customer_graph.py"
    $meetingsGraphLoaderScript = Join-Path $repoRoot "postgresql_age/load_data/meetings_graph/load_meetings_graph.py"
    $cgindexScript = Join-Path $repoRoot "postgresql_age/load_data/customer_graph/build_graph_indexes.py"
    $mgindexScript = Join-Path $repoRoot "postgresql_age/load_data/meetings_graph/build_graph_indexes.py"
    $dataDir = Join-Path $repoRoot "postgresql_age/data"
    $testConnectionScript = Join-Path $repoRoot "postgresql_age/load_data/test_pg_connection.py"
    $venvPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
    $pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }



    # Reset the PostgreSQL admin password via Azure CLI to ensure it matches
    # the stored POSTGRESQL_ADMIN_PASSWORD value.  This is necessary because
    # on the first run azd prompts for the @secure() parameter *before* the
    # preprovision hook generates the password, so the server may have been
    # created with the user-entered (vault) value while the env holds a
    # different generated value.
    Write-Host "Resetting PostgreSQL admin password to match stored environment value..."
    Invoke-NativeCommand {
        az postgres flexible-server update `
            --resource-group $ResourceGroup `
            --name $ServerName `
            --admin-password "$AdminPassword" `
            --output none 2>&1 | Out-Null
    }
    Wait-PostgresqlReady -ResourceGroup $ResourceGroup -ServerName $ServerName

    Write-Host "Preparing PostgreSQL connection for AGE initialization..."
    $env:PGHOST = $ServerFqdn
    $env:PGPORT = "5432"
    $env:PGDATABASE = "postgres"
    $env:PGUSER = $effectiveAdminUser
    $env:PGPASSWORD = $AdminPassword
    $env:PGSSLMODE = "require"
    Invoke-WithRetry -Operation "AGE extension initialization" -Action {
        & $pythonExe $testConnectionScript
        if ($LASTEXITCODE -ne 0) {
            throw "Init SQL script exited with code $LASTEXITCODE"
        }
    } -MaxAttempts 15 -DelaySeconds 12

    if (-not (Test-Path $customerGraphLoaderScript)) {
        throw "Data loader script not found: $customerGraphLoaderScript"
    }

    if (-not (Test-Path $meetingsGraphLoaderScript)) {
        throw "Data loader script not found: $meetingsGraphLoaderScript"
    }

    if (-not (Test-Path $dataDir)) {
        throw "Data directory not found: $dataDir"
    }

    Write-Host "Loading customer graph data into PostgreSQL AGE..."
    Invoke-WithRetry -Operation "Graph data load" -Action {
        $env:GRAPH_NAME = $effectiveGraphName
        $env:DATA_DIR = $dataDir
        & $pythonExe $customerGraphLoaderScript
        if ($LASTEXITCODE -ne 0) {
            throw "Graph data load exited with code $LASTEXITCODE"
        }
    } -MaxAttempts 3 -DelaySeconds 20


    Write-Host "Loading meetings graph data into PostgreSQL AGE..."
    Invoke-WithRetry -Operation "Graph data load" -Action {
        # Meetings loader must target its own graph (meetings_graph_v2),
        # NOT the customer_graph value used above.
        $env:GRAPH_NAME = "meetings_graph_v2"
        $env:DATA_DIR = $dataDir
        & $pythonExe $meetingsGraphLoaderScript
        if ($LASTEXITCODE -ne 0) {
            throw "Graph data load exited with code $LASTEXITCODE"
        }
    } -MaxAttempts 3 -DelaySeconds 20

    if (Test-Path $cgindexScript) {
        Write-Host "Building customer graph indexes..."
        Invoke-WithRetry -Operation "Graph index build" -Action {
            $env:GRAPH_NAME = $effectiveGraphName
            & $pythonExe $cgindexScript
            if ($LASTEXITCODE -ne 0) {
                throw "Graph index build exited with code $LASTEXITCODE"
            }
        } -MaxAttempts 3 -DelaySeconds 20
    } else {
        Write-Host "Index build script not found at $cgindexScript, skipping index creation."
    }

    if (Test-Path $mgindexScript) {
        Write-Host "Building meetings graph indexes..."
        Invoke-WithRetry -Operation "Graph index build" -Action {
            $env:GRAPH_NAME = "meetings_graph_v2"
            & $pythonExe $mgindexScript
            if ($LASTEXITCODE -ne 0) {
                throw "Graph index build exited with code $LASTEXITCODE"
            }
        } -MaxAttempts 3 -DelaySeconds 20
    } else {
        Write-Host "Index build script not found at $mgindexScript, skipping index creation."
    }
}

# Deploy all container apps using az deployment group create directly.
# This bypasses azd entirely, avoiding env file locking and TUI output issues.
# All images must be built BEFORE this runs.
function Invoke-ContainerAppsDeploy {
    param(
        [string]$ResourceGroup,
        [string]$PostgresqlAdminPassword
    )

    Write-Host ""
    Write-Host "=========================================="
    Write-Host "DEPLOY PHASE: Deploying all container apps"
    Write-Host "=========================================="

    $infraDir = Resolve-Path (Join-Path $PSScriptRoot "..\infra")
    $templateFile = Join-Path $infraDir "main.bicep"
    $parametersFile = Join-Path $infraDir "main.parameters.json"

    if (-not (Test-Path $templateFile)) {
        throw "Bicep template not found: $templateFile"
    }
    if (-not (Test-Path $parametersFile)) {
        throw "Parameters file not found: $parametersFile"
    }

    # Read the client IP from azd env (set by preprovision)
    $clientIp = Get-AzdEnvValue "CLIENT_IP_ADDRESS"
    if ([string]::IsNullOrEmpty($clientIp)) { $clientIp = "0.0.0.0" }

    Write-Host "  Resource Group:   $ResourceGroup"
    Write-Host "  Template:         $templateFile"
    Write-Host "  Deploy flags:     MCP=true, FastAPI=true, Webapp=true"
    Write-Host ""

    # Create a resolved parameters file that replaces ${...} azd-interpolation
    # tokens with actual values and sets all container deploy flags to true.
    # We read the original parameters JSON, fix the azd-specific tokens,
    # then write a temporary file for az deployment group create.
    $paramsJson = Get-Content $parametersFile -Raw | ConvertFrom-Json
    $paramsJson.parameters.postgresqlAdminPassword.value = $PostgresqlAdminPassword
    $paramsJson.parameters.clientIpAddress.value = $clientIp
    $paramsJson.parameters.deployContainerApp.value = $false
    $paramsJson.parameters.deployContainerAppsEnv.value = $true
    $paramsJson.parameters.deployMcpServerContainerApp.value = $true
    $paramsJson.parameters.deployFastApiContainerApp.value = $true
    $paramsJson.parameters.deployWebappContainerApp.value = $true

    $resolvedParamsFile = Join-Path $env:TEMP "azd-deploy-params-resolved.json"
    $paramsJson | ConvertTo-Json -Depth 10 | Set-Content -Path $resolvedParamsFile -Encoding UTF8
    Write-Host "  Resolved parameters written to: $resolvedParamsFile"

    # Run az deployment group create with the Bicep template and resolved parameters.
    # We use --only-show-errors to suppress verbose/info chatter that can buffer
    # indefinitely in PS5.1 under azd hook redirection, making the script look hung.
    # A background job prints a heartbeat so azd's output never goes silent.
    Write-Host "  Starting ARM deployment (this may take several minutes)..."
    Write-Host ""

    $azArgs = @("deployment", "group", "create",
                "--resource-group", $ResourceGroup,
                "--template-file", $templateFile,
                "--parameters", "@$resolvedParamsFile",
                "--name", "postprovision-containers",
                "--no-prompt", "--only-show-errors", "--output", "none")

    # Run az as a background job so the foreground can print heartbeat dots
    $deployJob = Start-Job -ScriptBlock {
        param($azArgs)
        & az @azArgs 2>&1
        $LASTEXITCODE
    } -ArgumentList (,$azArgs)

    # Print a dot every 10s while the deployment runs
    while ($deployJob.State -eq 'Running') {
        Start-Sleep -Seconds 10
        Write-Host -NoNewline "."
    }
    Write-Host ""  # newline after dots

    # Collect output and exit code from the job
    $jobOutput = Receive-Job -Job $deployJob -ErrorAction SilentlyContinue
    Remove-Job -Job $deployJob -Force -ErrorAction SilentlyContinue

    # The last line of output is $LASTEXITCODE from inside the job
    $deployExitCode = 0
    if ($null -ne $jobOutput -and $jobOutput.Count -gt 0) {
        $lastLine = $jobOutput[-1]
        if ($lastLine -match '^\d+$') {
            $deployExitCode = [int]$lastLine
            $jobOutput = $jobOutput[0..($jobOutput.Count - 2)]
        }
    }
    # Print any az output (errors, warnings)
    foreach ($line in $jobOutput) {
        if (-not [string]::IsNullOrEmpty("$line")) {
            Write-Host "  $line"
        }
    }

    # Clean up temp file
    if (Test-Path $resolvedParamsFile) {
        Remove-Item $resolvedParamsFile -Force -ErrorAction SilentlyContinue
    }

    if ($deployExitCode -ne 0) {
        Write-Host ""
        Write-Host "ERROR: Container app deployment failed (exit code $deployExitCode)." -ForegroundColor Red
        throw "Container app deployment failed (exit code $deployExitCode)."
    }

    Write-Host ""
    Write-Host "  Container app deployment completed successfully."
}

# ============================================================
# MAIN EXECUTION
# ============================================================

$acrName = Get-AzdEnvValue "acrName"
$acrLoginServer = Get-AzdEnvValue "acrLoginServer"
$mcpServerImageName = Get-AzdEnvValue "mcpServerImageName"
$mcpServerImageTag = Get-AzdEnvValue "mcpServerImageTag"
$buildMcpServerContainer = Get-AzdEnvValue "buildMcpServerContainer"
$fastApiImageName = Get-AzdEnvValue "fastApiImageName"
$fastApiImageTag = Get-AzdEnvValue "fastApiImageTag"
$buildFastApiContainer = Get-AzdEnvValue "buildFastApiContainer"
$webappImageName = Get-AzdEnvValue "webappImageName"
$webappImageTag = Get-AzdEnvValue "webappImageTag"
$buildWebappContainer = Get-AzdEnvValue "buildWebappContainer"
$resourceGroup = Get-AzdEnvValue "AZURE_RESOURCE_GROUP"
$postgresqlServerName = Get-AzdEnvValue "postgresqlServerName"
$postgresqlServerFqdn = Get-AzdEnvValue "postgresqlServerFqdn"
$postgresqlAdminLogin = Get-AzdEnvValue "postgresqlAdminLogin"
$postgresqlAdminPassword = Get-AzdEnvValue "POSTGRESQL_ADMIN_PASSWORD"
$graphName = Get-AzdEnvValue "graphName"
$initializePostgresqlAge = Get-AzdEnvValue "initializePostgresqlAge"

if ([string]::IsNullOrEmpty($acrName)) {
    Write-Host "ACR not deployed, skipping container builds"
    exit 0
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:AZURE_CORE_NO_COLOR = "1"
chcp 65001 | Out-Null

# ---- PHASE 0: PostgreSQL AGE initialization (flag-gated) ----
if (-not [string]::IsNullOrEmpty($postgresqlServerName) -and $initializePostgresqlAge -ne "false") {
    Wait-PostgresqlReady -ResourceGroup $resourceGroup -ServerName $postgresqlServerName
    # Open PostgreSQL firewall so the deployer's machine can connect.
    # The private endpoint blocks public access when no firewall rules exist.
    Ensure-PostgresqlAllowAllIps -ResourceGroup $resourceGroup -ServerName $postgresqlServerName
    Initialize-PostgresqlAgeAndData -ResourceGroup $resourceGroup -ServerName $postgresqlServerName -AdminUser $postgresqlAdminLogin -AdminPassword $postgresqlAdminPassword -ServerFqdn $postgresqlServerFqdn -GraphName $graphName
    # Remove the broad firewall rule now that initialization is complete.
    Write-Host "Removing temporary firewall rule..."
    Invoke-NativeCommand { az postgres flexible-server firewall-rule delete --resource-group $resourceGroup --name $postgresqlServerName --rule-name "AllowAllIps" --yes 2>&1 | Out-Null }
    Set-AzdEnvValue -Name "initializePostgresqlAge" -Value "false"
    Write-Host "PostgreSQL AGE initialization complete. Set initializePostgresqlAge=false to skip on next run."
} else {
    if ($initializePostgresqlAge -eq "false") {
        Write-Host "Skipping PostgreSQL AGE initialization (initializePostgresqlAge=false)."
    } elseif ([string]::IsNullOrEmpty($postgresqlServerName)) {
        Write-Host "Skipping PostgreSQL AGE initialization (no server name)."
    }
}

# ---- BUILD PHASE: Build all container images ----
Write-Host "=========================================="
Write-Host "Building container images..."
Write-Host "=========================================="

# Determine build strategy: Docker Desktop (local) vs ACR build (remote)
$useDockerDesktop = $false
if (Test-DockerAvailable) {
    $useDockerDesktop = $true
    Write-Host "Build strategy: Docker Desktop (local build + push to ACR)"
} else {
    Write-Host "Docker Desktop is not available."
    $userChoice = Read-Host "Use ACR remote build instead? (Y/n)"
    if ($userChoice -match '^[Nn]') {
        Write-Host "Container build aborted by user."
        exit 1
    }
    Write-Host "Build strategy: ACR remote build"
}

if ($buildMcpServerContainer -ne "false") {
    $mcpServerFullPath = Resolve-Path (Join-Path $scriptDir $McpServerPath)
    Write-Host "Checking if MCP Server container needs building..."
    $mcpBuildCheck = Test-BuildNeeded -FolderPath $mcpServerFullPath -HashEnvVarName "mcpServerFolderHash"
    if ($mcpBuildCheck.Needed) {
        if ($useDockerDesktop) {
            Invoke-DockerBuild -RegistryName $acrName -LoginServer $acrLoginServer -SourcePath $mcpServerFullPath -ImageName $mcpServerImageName -ImageTag $mcpServerImageTag -Label "mcp-server"
        } else {
            Invoke-AcrBuild -RegistryName $acrName -SourcePath $mcpServerFullPath -ImageName $mcpServerImageName -ImageTag $mcpServerImageTag -Label "mcp-server"
        }
        Save-FolderHash -HashEnvVarName "mcpServerFolderHash" -Hash $mcpBuildCheck.Hash
        Write-Host "MCP Server container built: $acrLoginServer/${mcpServerImageName}:${mcpServerImageTag}"
    } else {
        Write-Host "MCP Server container is up-to-date, skipping build."
    }
}

if ($buildFastApiContainer -ne "false") {
    $fastApiFullPath = Resolve-Path (Join-Path $scriptDir $FastApiPath)
    Write-Host "Checking if FastAPI container needs building..."
    $fastApiBuildCheck = Test-BuildNeeded -FolderPath $fastApiFullPath -HashEnvVarName "fastApiFolderHash"
    if ($fastApiBuildCheck.Needed) {
        if ($useDockerDesktop) {
            Invoke-DockerBuild -RegistryName $acrName -LoginServer $acrLoginServer -SourcePath $fastApiFullPath -ImageName $fastApiImageName -ImageTag $fastApiImageTag -Label "fastapi"
        } else {
            Invoke-AcrBuild -RegistryName $acrName -SourcePath $fastApiFullPath -ImageName $fastApiImageName -ImageTag $fastApiImageTag -Label "fastapi"
        }
        Save-FolderHash -HashEnvVarName "fastApiFolderHash" -Hash $fastApiBuildCheck.Hash
        Write-Host "FastAPI container built: $acrLoginServer/${fastApiImageName}:${fastApiImageTag}"
    } else {
        Write-Host "FastAPI container is up-to-date, skipping build."
    }
}

if ($buildWebappContainer -ne "false") {
    $webappFullPath = Resolve-Path (Join-Path $scriptDir $WebappPath)
    Write-Host "Checking if Webapp container needs building..."
    $webappBuildCheck = Test-BuildNeeded -FolderPath $webappFullPath -HashEnvVarName "webappFolderHash"
    if ($webappBuildCheck.Needed) {
        $fastApiFqdn = Get-AzdEnvValue "fastApiContainerAppFqdn"
        $buildArgs = @()
        if (-not [string]::IsNullOrEmpty($fastApiFqdn)) {
            $buildArgs += "VITE_API_BASE_URL=https://${fastApiFqdn}"
        }

        if ($useDockerDesktop) {
            Invoke-DockerBuild -RegistryName $acrName -LoginServer $acrLoginServer -SourcePath $webappFullPath -ImageName $webappImageName -ImageTag $webappImageTag -Label "webapp" -BuildArgs $buildArgs
        } else {
            Invoke-AcrBuild -RegistryName $acrName -SourcePath $webappFullPath -ImageName $webappImageName -ImageTag $webappImageTag -Label "webapp" -BuildArgs $buildArgs
        }
        Save-FolderHash -HashEnvVarName "webappFolderHash" -Hash $webappBuildCheck.Hash
        Write-Host "Webapp container built: $acrLoginServer/${webappImageName}:${webappImageTag}"
    } else {
        Write-Host "Webapp container is up-to-date, skipping build."
    }
}

# ---- DEPLOY PHASE: Single ARM deployment to deploy all container apps ----
Invoke-ContainerAppsDeploy -ResourceGroup $resourceGroup -PostgresqlAdminPassword $postgresqlAdminPassword

Write-Host "=========================================="
Write-Host "Post-provision completed successfully."
Write-Host "=========================================="

# ---- Display webapp URL if available ----
$webappFqdn = Get-AzdEnvValue "webappContainerAppFqdn"
if (-not [string]::IsNullOrEmpty($webappFqdn)) {
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "  Webapp URL: https://$webappFqdn" -ForegroundColor Green
    Write-Host "=========================================="
    Write-Host ""
}