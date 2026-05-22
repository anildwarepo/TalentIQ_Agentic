<#
.SYNOPSIS
    Post-provision hook for TalentIQ: PostgreSQL AGE init + data loading,
    Docker builds for 3 images, container app deployment via ARM.
#>

param(
    [string]$McpServerPath = "../../talent_backend",
    [string]$BackendPath = "../../talent_backend",
    [string]$WebappPath = "../../talent_ui"
)

$ErrorActionPreference = "Stop"

# Guard against recursive execution
if ($env:AZD_POSTPROVISION_PHASE -eq "1") {
    Write-Host "Skipping nested postprovision hook (provision phase in progress)."
    exit 0
}

Write-Host "=========================================="
Write-Host "Post-provision hook starting..."
Write-Host "=========================================="

function Get-AzdEnvValue {
    param([string]$Name)
    # azd writes errors like "ERROR: key '<name>' not found in the environment values" to stdout,
    # not stderr, so `2>nul` does not suppress them. Capture all output and filter.
    $raw = & cmd /c "azd env get-value $Name 2>&1"
    if ($null -eq $raw) { return "" }
    # Force array semantics — PowerShell unwraps single-element collections to scalars,
    # which would cause $lines[0] to return a character rather than a line.
    $lines = @(@($raw) | Where-Object { $_ -ne $null -and $_ -ne "" } | Where-Object {
        $line = $_.ToString().Trim()
        -not ($line.StartsWith("ERROR:") -or
              $line.StartsWith("WARNING:") -or
              $line.StartsWith("To update") -or
              $line -eq "" -or
              $line.StartsWith("winget upgrade"))
    })
    if ($lines.Count -eq 0) { return "" }
    return $lines[0].ToString().Trim()
}

function Resolve-AzdVaultSecret {
    <#
    .SYNOPSIS
        Resolves a vault://<vault-id>/<entry-id> reference from .azure/<env>/config.json
        against the local azd vault file at ~/.azd/vaults/<vault-id>.json.

        azd auto-migrates secret-like env values (e.g. *PASSWORD*) into the encrypted
        local vault. `azd env get-value KEY` does NOT resolve these references, so we
        must read the vault file directly. Entries are stored base64-encoded.
    .PARAMETER ParameterName
        The Bicep parameter name as it appears under .infra.parameters in config.json
        (e.g. "postgresqlAdminPassword").
    #>
    param([string]$ParameterName)
    try {
        $envName = (cmd /c "azd env get-value AZURE_ENV_NAME 2>nul").Trim()
        if ([string]::IsNullOrEmpty($envName)) { return "" }
        $scriptDir = $PSScriptRoot
        $configPath = Resolve-Path (Join-Path $scriptDir "../.azure/$envName/config.json") -ErrorAction SilentlyContinue
        if (-not $configPath -or -not (Test-Path $configPath)) { return "" }
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        $vaultRef = $cfg.infra.parameters.$ParameterName
        if ([string]::IsNullOrEmpty($vaultRef) -or -not $vaultRef.StartsWith("vault://")) { return "" }
        # Parse vault://<vault-id>/<entry-id>
        $parts = $vaultRef.Substring("vault://".Length).Split('/')
        if ($parts.Length -ne 2) { return "" }
        $vaultId = $parts[0]
        $entryId = $parts[1]
        $vaultPath = Join-Path $env:USERPROFILE ".azd/vaults/$vaultId.json"
        if (-not (Test-Path $vaultPath)) { return "" }
        $vault = Get-Content $vaultPath -Raw | ConvertFrom-Json
        $encoded = $vault.$entryId
        if ([string]::IsNullOrEmpty($encoded)) { return "" }
        return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded))
    } catch {
        return ""
    }
}

function Get-PostgresqlAdminPassword {
    <#
    .SYNOPSIS
        Resolve the PostgreSQL admin password using a multi-strategy fallback chain.
        Modern azd (1.23+) auto-migrates *PASSWORD* env values to the encrypted vault,
        so `azd env get-value` alone returns empty. Must check vault and source-of-truth
        .env file as fallbacks. Returns "" if all strategies fail.
    #>
    # 1. azd-injected env var (some azd versions inject vault-resolved values at hook runtime)
    if (-not [string]::IsNullOrEmpty($env:POSTGRESQL_ADMIN_PASSWORD)) {
        Write-Host "  Password source: `$env:POSTGRESQL_ADMIN_PASSWORD (azd-injected)"
        return $env:POSTGRESQL_ADMIN_PASSWORD
    }
    # 2. azd env get-value (only works if NOT vault-migrated)
    $v = Get-AzdEnvValue "POSTGRESQL_ADMIN_PASSWORD"
    if (-not [string]::IsNullOrEmpty($v)) {
        Write-Host "  Password source: azd env value POSTGRESQL_ADMIN_PASSWORD"
        return $v
    }
    # 3. Resolve vault reference from config.json (handles vault-migrated secrets)
    $v = Resolve-AzdVaultSecret -ParameterName "postgresqlAdminPassword"
    if (-not [string]::IsNullOrEmpty($v)) {
        Write-Host "  Password source: azd local vault (resolved via config.json reference)"
        return $v
    }
    # 4. Read PGPASSWORD from app_config/.env (same source preprovision uses)
    try {
        $scriptDir = $PSScriptRoot
        $appEnv = Resolve-Path (Join-Path $scriptDir "../../app_config/.env") -ErrorAction SilentlyContinue
        if ($appEnv -and (Test-Path $appEnv)) {
            $m = Select-String -Path $appEnv -Pattern '^PGPASSWORD=(.+)$' | Select-Object -First 1
            if ($m) {
                Write-Host "  Password source: app_config/.env PGPASSWORD"
                return $m.Matches[0].Groups[1].Value.Trim()
            }
        }
    } catch { }
    return ""
}

function Set-AzdEnvValue {
    param([string]$Name, [string]$Value)
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & azd env set $Name "$Value" 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $savedEAP
    }
}

function Invoke-NativeCommand {
    param([Parameter(Mandatory)][scriptblock]$Command)
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command }
    finally { $ErrorActionPreference = $savedEAP }
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
    param([string]$FolderPath, [string]$HashEnvVarName)
    $currentHash = Get-FolderHash -FolderPath $FolderPath
    $storedHash = Get-AzdEnvValue $HashEnvVarName
    if ($currentHash -eq $storedHash) {
        return @{ Needed = $false; Hash = $currentHash }
    }
    return @{ Needed = $true; Hash = $currentHash }
}

function Save-FolderHash {
    param([string]$HashEnvVarName, [string]$Hash)
    Set-AzdEnvValue -Name $HashEnvVarName -Value $Hash
}

function Test-DockerAvailable {
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
    param(
        [string]$RegistryName, [string]$LoginServer, [string]$SourcePath,
        [string]$ImageName, [string]$ImageTag, [string]$Label,
        [string]$DockerfileName = "Dockerfile",
        [string[]]$BuildArgs = @()
    )
    Push-Location $SourcePath
    try {
        Write-Host "  Building $Label container locally with Docker Desktop..."
        Write-Host "  Logging into ACR $RegistryName..."
        Invoke-NativeCommand { az acr login --name $RegistryName 2>&1 | Out-Null }

        $fullTagged = "${LoginServer}/${ImageName}:${ImageTag}"
        $fullLatest = "${LoginServer}/${ImageName}:latest"

        $dockerArgs = @("build", "-t", $fullTagged, "-t", $fullLatest, "-f", $DockerfileName,
                        "--provenance=false", "--sbom=false")
        foreach ($arg in $BuildArgs) {
            $dockerArgs += "--build-arg"
            $dockerArgs += $arg
        }
        $dockerArgs += "."

        & docker @dockerArgs
        if ($LASTEXITCODE -ne 0) { throw "Docker build failed for $Label (exit code $LASTEXITCODE)" }

        Write-Host "  Pushing $Label image to $LoginServer..."
        & docker push $fullTagged
        if ($LASTEXITCODE -ne 0) { throw "Docker push failed for ${fullTagged}" }
        & docker push $fullLatest
        if ($LASTEXITCODE -ne 0) { throw "Docker push failed for ${fullLatest}" }

        Write-Host "  $Label image pushed successfully."
    } finally { Pop-Location }
}

function Invoke-AcrBuild {
    param(
        [string]$RegistryName, [string]$SourcePath,
        [string]$ImageName, [string]$ImageTag, [string]$Label,
        [string]$DockerfileName = "Dockerfile",
        [string[]]$BuildArgs = @()
    )
    Push-Location $SourcePath
    try {
        Write-Host "  Building $Label container in ACR $RegistryName (this may take several minutes)..."
        $azArgs = @("acr", "build", "--registry", $RegistryName,
                    "--image", "${ImageName}:${ImageTag}",
                    "--image", "${ImageName}:latest",
                    "--file", $DockerfileName, ".",
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
        } finally { $ErrorActionPreference = $savedEAP }

        if ($buildExitCode -ne 0) { throw "ACR build failed for $Label (exit code $buildExitCode)" }

        $buildObj = $buildResponse | ConvertFrom-Json
        $runId = $null
        if ($buildObj.PSObject.Properties.Name -contains "runId") { $runId = $buildObj.runId }
        if ([string]::IsNullOrEmpty($runId) -and ($buildObj.PSObject.Properties.Name -contains "id")) {
            if ($buildObj.id -match '/runs/([^/\s]+)$') { $runId = $Matches[1] }
        }
        if ([string]::IsNullOrEmpty($runId)) { throw "Could not determine ACR run ID for $Label." }

        Write-Host "  ACR build queued. Run ID: $runId"

        # Poll for completion
        $lastStatus = ""
        $pollCount = 0
        while ($true) {
            $pollCount++
            if ($pollCount -gt 180) { throw "Timed out waiting for ACR build for $Label." }
            $savedEAP = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $runJson = (& az acr task show-run --registry $RegistryName --run-id $runId --only-show-errors --output json 2>&1 | Out-String).Trim()
                $showRunExitCode = $LASTEXITCODE
            } finally { $ErrorActionPreference = $savedEAP }

            if ($showRunExitCode -ne 0) { Start-Sleep -Seconds 5; continue }

            try { $runObj = $runJson | ConvertFrom-Json } catch { Start-Sleep -Seconds 5; continue }
            $status = [string]$runObj.status
            if ($status -ne $lastStatus) {
                Write-Host "  [$(Get-Date -Format 'HH:mm:ss')] ACR build status: $status"
                $lastStatus = $status
            }
            if ($status -in @("Succeeded", "Failed", "Canceled", "Error")) {
                if ($status -ne "Succeeded") { throw "ACR build failed for $Label (status: $status)" }
                break
            }
            Start-Sleep -Seconds 8
        }
    } finally { Pop-Location }
}

function Wait-PostgresqlReady {
    param([string]$ResourceGroup, [string]$ServerName, [int]$MaxAttempts = 60, [int]$DelaySeconds = 10)
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $state = Invoke-NativeCommand { az postgres flexible-server show --resource-group $ResourceGroup --name $ServerName --query "state" -o tsv 2>&1 | Where-Object { $_ -notmatch '^WARNING' } }
        if ($LASTEXITCODE -eq 0 -and $state -eq "Ready") { return }
        Write-Host "Waiting for PostgreSQL server to be Ready (attempt $attempt/$MaxAttempts, current state: $state)..."
        Start-Sleep -Seconds $DelaySeconds
    }
    throw "PostgreSQL server did not reach Ready state in time."
}

function Ensure-PostgresqlAllowAllIps {
    param([string]$ResourceGroup, [string]$ServerName)
    if ([string]::IsNullOrEmpty($ResourceGroup) -or [string]::IsNullOrEmpty($ServerName)) { return }
    Write-Host "Opening PostgreSQL firewall to all IPs for data loading..."
    Invoke-NativeCommand { az postgres flexible-server firewall-rule create --resource-group $ResourceGroup --name $ServerName --rule-name "AllowAllIps" --start-ip-address "0.0.0.0" --end-ip-address "255.255.255.255" 2>&1 | Out-Null }
}

function Register-PgUamiAsEntraAdmin {
    <#
    .SYNOPSIS
        Registers a user-assigned managed identity as a PostgreSQL Entra
        ServicePrincipal administrator via the Azure control plane. This is the
        fallback path for Phase 0.5 when `pgaadauth_create_principal_with_oid`
        (the SQL approach) is unreachable from the deployer — e.g. ISP-level
        port 5432 blocks (Comcast and many residential ISPs do this), or a
        private endpoint that isn't exposed locally.

        Idempotent — re-running for the same display-name+object-id is a no-op.
        The UAMI receives **PG admin** privileges, which is broader than the
        SQL path (which grants narrow per-schema privileges). This is
        acceptable for unblocking container apps; deployers with full network
        connectivity should still prefer the SQL path.
    .PARAMETER ResourceGroup
        Resource group containing the PG flexible server.
    .PARAMETER ServerName
        PG flexible server name (without FQDN suffix).
    .PARAMETER UamiName
        Display name to register. MUST equal the UAMI's name — that's the PG
        username the container will present when authenticating.
    .PARAMETER ObjectId
        principalId of the UAMI.
    .OUTPUTS
        [bool] $true on success, $false on failure (logged but non-throwing
        so the caller can continue with the remaining UAMIs).
    #>
    param(
        [string]$ResourceGroup,
        [string]$ServerName,
        [string]$UamiName,
        [string]$ObjectId
    )
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & az postgres flexible-server microsoft-entra-admin create `
            --resource-group $ResourceGroup `
            --server-name $ServerName `
            --display-name $UamiName `
            --object-id $ObjectId `
            --type ServicePrincipal `
            --only-show-errors `
            --output none 2>&1
        $exit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedEAP
    }
    if ($exit -ne 0) {
        Write-Host "    FAIL ($UamiName): control-plane admin create failed (exit $exit)" -ForegroundColor Red
        if ($out) { Write-Host "      $out" -ForegroundColor DarkRed }
        return $false
    }
    Write-Host "    OK ($UamiName): registered as PG Entra ServicePrincipal admin (control plane)" -ForegroundColor Green
    return $true
}

function Ensure-PostgresqlConfigApplied {
    <#
    .SYNOPSIS
        Restarts the PG flexible server if ANY server parameter is still
        flagged ``isConfigPendingRestart=true``. AGE in particular requires
        ``shared_preload_libraries=age`` to be applied via a restart — the
        Bicep template sets it, but if a later step (re-deploy, parameter
        update, manual ``az postgres ... parameter set``) re-touches it the
        change is stuck in pending state and every ``cypher()`` call fails
        with ``unhandled cypher(cstring) function call``.

        This helper is the belt-and-braces final check: if anything is
        pending, restart once and wait for Ready.
    .PARAMETER ResourceGroup
        Resource group containing the PG server.
    .PARAMETER ServerName
        PG flexible server name.
    #>
    param([string]$ResourceGroup, [string]$ServerName)
    if ([string]::IsNullOrEmpty($ResourceGroup) -or [string]::IsNullOrEmpty($ServerName)) { return }
    Write-Host "Checking for PostgreSQL parameters pending restart on '$ServerName'..."
    $pendingJson = & az postgres flexible-server parameter list `
        --resource-group $ResourceGroup `
        --server-name $ServerName `
        --query "[?isConfigPendingRestart].{name:name,value:value}" `
        --output json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($pendingJson)) {
        Write-Host "  (could not query pending-restart params — skipping)" -ForegroundColor DarkYellow
        return
    }
    try { $pending = $pendingJson | ConvertFrom-Json } catch { $pending = @() }
    if (-not $pending -or $pending.Count -eq 0) {
        Write-Host "  No PG parameters pending restart." -ForegroundColor DarkGray
        return
    }
    Write-Host "  Pending-restart parameters detected:" -ForegroundColor Yellow
    foreach ($p in $pending) { Write-Host "    - $($p.name) = $($p.value)" -ForegroundColor Yellow }
    Write-Host "  Restarting PostgreSQL to apply..." -ForegroundColor Yellow
    Invoke-NativeCommand { az postgres flexible-server restart --resource-group $ResourceGroup --name $ServerName --output none 2>&1 | Out-Null }
    Wait-PostgresqlReady -ResourceGroup $ResourceGroup -ServerName $ServerName
    Write-Host "  PG restarted. NOTE: container apps with cached pools may need a revision restart:" -ForegroundColor Green
    Write-Host "    az containerapp revision restart -n <app> -g $ResourceGroup --revision <active-revision>" -ForegroundColor DarkGray
}

function Get-PostgresqlPrivateEndpointInfo {
    <#
    .SYNOPSIS
        Returns the private IP, privatelink FQDN, and public FQDN of the PostgreSQL private endpoint.
    .OUTPUTS
        PSCustomObject with: PrivateIp, PrivatelinkFqdn, PublicFqdn, NicName
        Returns $null if no PE is found.
    #>
    param([string]$ResourceGroup, [string]$ServerName)
    if ([string]::IsNullOrEmpty($ResourceGroup) -or [string]::IsNullOrEmpty($ServerName)) { return $null }

    $peName = "${ServerName}-pe"
    Write-Host "Looking up private endpoint '$peName' in resource group '$ResourceGroup'..."

    $nicId = Invoke-NativeCommand {
        az network private-endpoint show `
            --name $peName --resource-group $ResourceGroup `
            --query "networkInterfaces[0].id" -o tsv 2>&1 | Where-Object { $_ -notmatch '^WARNING' }
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($nicId)) {
        Write-Host "  Private endpoint '$peName' not found. PE-based connectivity disabled."
        return $null
    }

    $privateIp = Invoke-NativeCommand {
        az network nic show --ids $nicId `
            --query "ipConfigurations[0].privateIPAddress" -o tsv 2>&1 | Where-Object { $_ -notmatch '^WARNING' }
    }
    if ([string]::IsNullOrEmpty($privateIp)) {
        Write-Host "  Could not retrieve private IP from NIC '$nicId'."
        return $null
    }

    return [PSCustomObject]@{
        PrivateIp         = $privateIp.Trim()
        PrivatelinkFqdn   = "${ServerName}.privatelink.postgres.database.azure.com"
        PublicFqdn        = "${ServerName}.postgres.database.azure.com"
        NicId             = $nicId.Trim()
    }
}

function Wait-ForPrivateEndpointReachable {
    <#
    .SYNOPSIS
        Polls until EITHER the privatelink FQDN OR the public FQDN resolves to the expected
        private IP and port 5432 is reachable. Returns the FQDN that works (or throws on timeout).
        Designed to be non-interactive: shows hosts file instructions, then waits for the user to
        edit the hosts file out-of-band. Detects success automatically.
    .PARAMETER PeInfo
        The PE info object from Get-PostgresqlPrivateEndpointInfo.
    .PARAMETER TimeoutSeconds
        Total time to wait before failing. Default 600 seconds (10 minutes).
    .PARAMETER PollSeconds
        Seconds between polls. Default 5 seconds.
    .OUTPUTS
        [string] The FQDN that resolved correctly (either privatelink or public).
    #>
    param(
        [PSCustomObject]$PeInfo,
        [int]$TimeoutSeconds = 600,
        [int]$PollSeconds = 5
    )

    $hostsPath = if ($IsWindows -or $env:OS -match 'Windows') {
        "$env:SystemRoot\System32\drivers\etc\hosts"
    } else {
        "/etc/hosts"
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  PostgreSQL private endpoint — hosts file entry required" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  PostgreSQL is reachable only via private endpoint."
    Write-Host "  Add ONE of the following lines to your hosts file so the data"
    Write-Host "  pipeline can connect to it from this machine. Either form works."
    Write-Host ""
    Write-Host "  Hosts file location:" -ForegroundColor Yellow
    Write-Host "    $hostsPath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Option A (recommended — matches TLS cert CN):" -ForegroundColor Yellow
    Write-Host "    $($PeInfo.PrivateIp)  $($PeInfo.PublicFqdn)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Option B (privatelink FQDN):" -ForegroundColor Yellow
    Write-Host "    $($PeInfo.PrivateIp)  $($PeInfo.PrivatelinkFqdn)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Option C (both on one line):" -ForegroundColor Yellow
    Write-Host "    $($PeInfo.PrivateIp)  $($PeInfo.PublicFqdn)  $($PeInfo.PrivatelinkFqdn)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  This script will poll every $PollSeconds seconds and continue automatically" -ForegroundColor Yellow
    Write-Host "  once the entry resolves correctly. Timeout: $TimeoutSeconds seconds." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To open the hosts file with admin rights on Windows, run from an" -ForegroundColor DarkGray
    Write-Host "  elevated PowerShell window:" -ForegroundColor DarkGray
    Write-Host "    notepad `$env:SystemRoot\System32\drivers\etc\hosts" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $attempt = 0
    $expectedIp = $PeInfo.PrivateIp
    $candidates = @($PeInfo.PublicFqdn, $PeInfo.PrivatelinkFqdn)

    while ((Get-Date) -lt $deadline) {
        $attempt++
        $statuses = @()
        foreach ($fqdn in $candidates) {
            $resolvedIp = $null
            $portOpen = $false
            try {
                # Bypass DNS cache by querying without using cached entries where possible.
                $resolved = [System.Net.Dns]::GetHostAddresses($fqdn) | Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1
                if ($null -ne $resolved) { $resolvedIp = $resolved.IPAddressToString }
            } catch {
                $resolvedIp = $null
            }

            if ($resolvedIp -eq $expectedIp) {
                try {
                    $tcp = New-Object System.Net.Sockets.TcpClient
                    $connectTask = $tcp.ConnectAsync($fqdn, 5432)
                    if ($connectTask.Wait(3000) -and $tcp.Connected) {
                        $portOpen = $true
                    }
                    $tcp.Close()
                } catch {
                    $portOpen = $false
                }
            }

            if ($resolvedIp -eq $expectedIp -and $portOpen) {
                Write-Host "  [OK] $fqdn resolves to $resolvedIp and port 5432 is open. Using this FQDN to connect." -ForegroundColor Green
                return $fqdn
            }

            $status = if ([string]::IsNullOrEmpty($resolvedIp)) {
                "not resolving"
            } elseif ($resolvedIp -ne $expectedIp) {
                "resolves to $resolvedIp (expected $expectedIp)"
            } else {
                "resolves correctly but port 5432 not reachable"
            }
            $statuses += "$fqdn → $status"
        }
        Write-Host "  [poll $attempt] $($statuses -join '; '). Retrying in ${PollSeconds}s..." -ForegroundColor DarkGray
        Start-Sleep -Seconds $PollSeconds
    }

    throw "Timed out after $TimeoutSeconds seconds. Neither $($PeInfo.PublicFqdn) nor $($PeInfo.PrivatelinkFqdn) resolved to $expectedIp with port 5432 open. Verify your hosts file entry."
}

function Show-HostsFileInstructions {
    param([PSCustomObject]$PeInfo)
    return (Wait-ForPrivateEndpointReachable -PeInfo $PeInfo)
}

function Invoke-WithRetry {
    param([scriptblock]$Action, [string]$Operation, [int]$MaxAttempts = 12, [int]$DelaySeconds = 10)
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try { & $Action; return }
        catch {
            if ($attempt -eq $MaxAttempts) { throw "${Operation} failed after ${MaxAttempts} attempts. Last error: $($_.Exception.Message)" }
            Write-Host "${Operation} failed (attempt $attempt/$MaxAttempts). Retrying in $DelaySeconds seconds..."
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Initialize-PostgresqlAgeAndData {
    param(
        [string]$ResourceGroup, [string]$ServerName, [string]$AdminUser,
        [string]$EntraAdminUpn, [string]$EntraAdminObjectId,
        [string]$ServerFqdn, [string]$GraphName,
        [string]$ConnectFqdn = ''
    )
    if ([string]::IsNullOrEmpty($ServerName) -or [string]::IsNullOrEmpty($ResourceGroup)) {
        Write-Host "Skipping PostgreSQL AGE/data initialization (no server provisioned)."
        return
    }

    $effectiveGraphName = if (-not [string]::IsNullOrEmpty($GraphName)) { $GraphName } else { "talent_graph" }
    $effectiveConnectFqdn = if (-not [string]::IsNullOrEmpty($ConnectFqdn)) { $ConnectFqdn } else { $ServerFqdn }

    Write-Host "Configuring PostgreSQL server parameters for AGE..."
    Invoke-NativeCommand { az postgres flexible-server parameter set --resource-group $ResourceGroup --server-name $ServerName --name azure.extensions --value 'AGE,VECTOR,PG_TRGM,PG_DISKANN' 2>&1 | Out-Null }
    Invoke-NativeCommand { az postgres flexible-server parameter set --resource-group $ResourceGroup --server-name $ServerName --name shared_preload_libraries --value age 2>&1 | Out-Null }

    Write-Host "Restarting PostgreSQL server..."
    Invoke-NativeCommand { az postgres flexible-server restart --resource-group $ResourceGroup --name $ServerName 2>&1 | Out-Null }
    Wait-PostgresqlReady -ResourceGroup $ResourceGroup -ServerName $ServerName

    # ── Entra ID authentication (idempotent) ─────────────────────────────
    # Ensure Entra auth is enabled on the server (Bicep already sets this,
    # but the hook is safe to re-run against an existing server that may
    # have been provisioned before the Entra changes landed).
    Write-Host "Ensuring Microsoft Entra ID authentication is enabled..."
    Invoke-NativeCommand {
        az postgres flexible-server update `
            --resource-group $ResourceGroup `
            --name $ServerName `
            --microsoft-entra-auth Enabled `
            --output none 2>&1 | Out-Null
    }
    Wait-PostgresqlReady -ResourceGroup $ResourceGroup -ServerName $ServerName

    # Ensure the deploying user is registered as an Entra administrator.
    # Bicep already creates this when `postgresqlEntraAdminObjectId` is set,
    # but we replay it here so manual `azd provision` invocations that bypass
    # `preprovision` still get a working admin.
    if (-not [string]::IsNullOrEmpty($EntraAdminObjectId) -and -not [string]::IsNullOrEmpty($EntraAdminUpn)) {
        Write-Host "Ensuring '$EntraAdminUpn' is a PostgreSQL Entra administrator..."
        Invoke-NativeCommand {
            az postgres flexible-server microsoft-entra-admin create `
                --resource-group $ResourceGroup `
                --server-name $ServerName `
                --display-name $EntraAdminUpn `
                --object-id $EntraAdminObjectId `
                --type User `
                --output none 2>&1 | Out-Null
        }
    } else {
        Write-Host "  WARNING: POSTGRESQL_ENTRA_ADMIN_OBJECT_ID / _PRINCIPAL_NAME not set — data load may fail." -ForegroundColor Yellow
        Write-Host "  Run 'az login' and re-run 'azd up', or invoke Enable-PostgresEntraAuth.ps1 manually." -ForegroundColor Yellow
    }

    # ── Data pipeline (uses Entra token at connect time) ─────────────────
    $scriptDir = $PSScriptRoot
    $repoRoot = Resolve-Path (Join-Path $scriptDir "../..")
    $dataPipelineScript = Join-Path $repoRoot "talent_data_pipeline/main.py"
    $venvPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
    $pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

    Write-Host "Preparing PostgreSQL connection for data loading..."
    Write-Host "  Connecting via: $effectiveConnectFqdn"
    Write-Host "  PGUSER (Entra): $EntraAdminUpn"
    $env:PGHOST = $effectiveConnectFqdn
    $env:PGPORT = "5432"
    $env:PGDATABASE = "postgres"
    # PGUSER must be the Entra principal name (UPN for users). The data
    # pipeline acquires an OSSRDBMS bearer token via DefaultAzureCredential
    # (which uses the az CLI session locally, or the container UAMI in cloud)
    # and attaches it as the libpq password — see talent_data_pipeline/pg_entra.py.
    $env:PGUSER = $EntraAdminUpn
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $env:PGSSLMODE = "require"
    $env:GRAPH_NAME = $effectiveGraphName

    if (-not (Test-Path $dataPipelineScript)) {
        Write-Host "WARNING: Data pipeline script not found at $dataPipelineScript. Skipping data load."
        return
    }

    Write-Host "Running TalentIQ data pipeline (Entra-authenticated)..."
    Invoke-WithRetry -Operation "TalentIQ data pipeline" -Action {
        & $pythonExe $dataPipelineScript
        if ($LASTEXITCODE -ne 0) {
            throw "Data pipeline exited with code $LASTEXITCODE"
        }
    } -MaxAttempts 3 -DelaySeconds 20

    Write-Host "TalentIQ data pipeline complete."
}

function Get-EntraSpaClientId {
    <#
    .SYNOPSIS
        Resolve the Entra SPA app registration client ID for the webapp.
        Source priority:
          1. azd env value `entraSpaClientId` (set via `azd env set entraSpaClientId <guid>`)
          2. Hardcoded value in talent_ui/src/authConfig.js (parsed via regex)
        Returns empty string if neither source yields a GUID.
    #>
    param([string]$WebappSourcePath)

    $fromEnv = Get-AzdEnvValue "entraSpaClientId"
    if (-not [string]::IsNullOrEmpty($fromEnv)) { return $fromEnv.Trim() }

    $authConfigPath = Join-Path $WebappSourcePath "src\authConfig.js"
    if (Test-Path $authConfigPath) {
        $content = Get-Content $authConfigPath -Raw
        # match: clientId: "<guid>"  (or single quotes)
        $m = [regex]::Match($content, 'clientId\s*:\s*["'']([0-9a-fA-F-]{36})["'']')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return ""
}

function Register-WebappRedirectUri {
    <#
    .SYNOPSIS
        Adds the deployed webapp FQDN as a SPA redirect URI on the Entra app registration
        if it isn't already present. Idempotent. Failures are non-fatal — they are logged
        but do not abort the post-provision flow (the deployment can still complete and
        the URI can be added manually).
    #>
    param(
        [string]$AppClientId,
        [string]$WebappFqdn
    )

    if ([string]::IsNullOrEmpty($AppClientId)) {
        Write-Host "  ⚠ Skipping redirect URI registration — no SPA client ID resolved." -ForegroundColor Yellow
        Write-Host "    To enable automatic registration on future runs:"
        Write-Host "      azd env set entraSpaClientId <your-spa-app-client-id>"
        return
    }
    if ([string]::IsNullOrEmpty($WebappFqdn)) {
        Write-Host "  ⚠ Skipping redirect URI registration — no webapp FQDN available." -ForegroundColor Yellow
        return
    }

    $newUri = "https://$WebappFqdn"
    Write-Host ""
    Write-Host "Registering webapp redirect URI with Entra app $AppClientId..."
    Write-Host "  URI: $newUri"

    try {
        # Get the app's object ID (Graph requires it, not the appId)
        $objectId = & az ad app show --id $AppClientId --query id -o tsv 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($objectId)) {
            Write-Host "  ⚠ App registration $AppClientId not found, or insufficient permissions to read it." -ForegroundColor Yellow
            Write-Host "    Add the URI manually in the Entra portal (Single-page application platform)."
            return
        }

        # Read existing SPA redirect URIs (returns 'null' string if not configured)
        $existingJson = & az ad app show --id $AppClientId --query "spa.redirectUris" -o json 2>$null
        $existing = @()
        if (-not [string]::IsNullOrEmpty($existingJson) -and $existingJson -ne "null") {
            $existing = $existingJson | ConvertFrom-Json
            if ($null -eq $existing) { $existing = @() }
        }

        if ($existing -contains $newUri) {
            Write-Host "  ✓ Redirect URI already registered. No action needed." -ForegroundColor Green
            return
        }

        $merged = @($existing) + $newUri
        $body = @{ spa = @{ redirectUris = $merged } } | ConvertTo-Json -Depth 5 -Compress

        # az rest on Windows needs the body either via @file or escaped. Use a temp file
        # to avoid double-quoting headaches across PowerShell/cmd.
        $bodyFile = Join-Path $env:TEMP "azd-spa-redirect-patch.json"
        $body | Set-Content -Path $bodyFile -Encoding UTF8 -NoNewline

        & az rest --method PATCH `
            --uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
            --headers "Content-Type=application/json" `
            --body "@$bodyFile" 2>&1 | Out-Null

        Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue

        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ⚠ Failed to update app registration (az rest exit $LASTEXITCODE)." -ForegroundColor Yellow
            Write-Host "    You likely need Application Administrator or owner rights on the app."
            Write-Host "    Add the URI manually: $newUri (Single-page application platform)"
            return
        }

        Write-Host "  ✓ Added $newUri to SPA redirect URIs." -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Exception while updating app registration: $_" -ForegroundColor Yellow
        Write-Host "    Add the URI manually: $newUri (Single-page application platform)"
    }
}

function Invoke-ContainerAppsDeploy {
    param([string]$ResourceGroup, [string]$PostgresqlAdminPassword)

    Write-Host ""
    Write-Host "=========================================="
    Write-Host "DEPLOY PHASE: Deploying all container apps"
    Write-Host "=========================================="

    $infraDir = Resolve-Path (Join-Path $PSScriptRoot "..\infra")
    $templateFile = Join-Path $infraDir "main.bicep"
    $parametersFile = Join-Path $infraDir "main.parameters.json"

    if (-not (Test-Path $templateFile)) { throw "Bicep template not found: $templateFile" }
    if (-not (Test-Path $parametersFile)) { throw "Parameters file not found: $parametersFile" }

    $clientIp = Get-AzdEnvValue "CLIENT_IP_ADDRESS"
    if ([string]::IsNullOrEmpty($clientIp)) { $clientIp = "0.0.0.0" }

    Write-Host "  Resource Group:   $ResourceGroup"
    Write-Host "  Template:         $templateFile"

    # Determine MCP topology: sidecar (default) vs. standalone Container App.
    # When sidecarMode=true the bicep skips the standalone MCP module (its
    # condition includes `!mcpServerSidecar`), so we set deployMcpServerContainerApp
    # to false here to make the intent explicit. Flip via `azd env set
    # mcpServerSidecar false` to fall back to the legacy two-app topology.
    $mcpServerSidecarRaw = Get-AzdEnvValue "mcpServerSidecar"
    $sidecarMode = -not ($mcpServerSidecarRaw -eq "false" -or $mcpServerSidecarRaw -eq "False" -or $mcpServerSidecarRaw -eq "FALSE")
    $mcpTopology = if ($sidecarMode) { "sidecar (inside backend Container App)" } else { "standalone Container App" }
    $deployMcpAppFlag = -not $sidecarMode
    Write-Host "  Deploy flags:     MCP=$deployMcpAppFlag, Backend=true, Webapp=true"
    Write-Host "  MCP topology:     $mcpTopology"
    Write-Host ""

    # Create resolved parameters with deploy flags set to true
    $paramsJson = Get-Content $parametersFile -Raw | ConvertFrom-Json

    # Generic resolver for azd-style placeholders (${VAR} and ${VAR=default}).
    # azd expands these before handing params to ARM, but this hook calls
    # `az deployment` directly which does NOT expand them — so any param
    # left as a literal `${...}` string would be sent verbatim and rejected
    # (e.g. `InvalidResourceName: ${ACA_SUBNET_NAME=...}` for the ACA subnet).
    # The lookup pulls from process env (which azd populates from .env and
    # `azd env set` values), so anything the deployer set via `azd env set`
    # is honoured here.
    $envLookup = @{}
    Get-ChildItem env: | ForEach-Object { $envLookup[$_.Name] = $_.Value }

    function Resolve-AzdPlaceholder {
        param([string]$Text, [hashtable]$Env)
        if ([string]::IsNullOrEmpty($Text)) { return $Text }
        if ($Text -notmatch '\$\{') { return $Text }
        $prev = ''
        $current = $Text
        $iter = 0
        # Iterate to allow nested defaults like ${A=${B}}.
        while ($current -ne $prev -and $iter -lt 10) {
            $prev = $current
            $current = [regex]::Replace($current, '\$\{([A-Za-z_][A-Za-z0-9_]*)(?:=([^${}]*))?\}', {
                param($m)
                $name = $m.Groups[1].Value
                $hasDefault = $m.Groups[2].Success
                $default = if ($hasDefault) { $m.Groups[2].Value } else { '' }
                if ($Env.ContainsKey($name) -and -not [string]::IsNullOrEmpty($Env[$name])) {
                    return $Env[$name]
                }
                return $default
            })
            $iter++
        }
        return $current
    }

    foreach ($prop in $paramsJson.parameters.PSObject.Properties) {
        $paramObj = $prop.Value
        if ($null -ne $paramObj -and $paramObj.PSObject.Properties.Name -contains 'value') {
            $val = $paramObj.value
            if ($val -is [string] -and $val -match '\$\{') {
                $paramObj.value = Resolve-AzdPlaceholder -Text $val -Env $envLookup
            }
        }
    }

    $paramsJson.parameters.postgresqlAdminPassword.value = $PostgresqlAdminPassword
    $paramsJson.parameters.clientIpAddress.value = $clientIp
    $paramsJson.parameters.deployContainerAppsEnv.value = $true
    $paramsJson.parameters.deployMcpServerContainerApp.value = $deployMcpAppFlag
    $paramsJson.parameters.deployBackendContainerApp.value = $true
    $paramsJson.parameters.deployWebappContainerApp.value = $true
    if ($paramsJson.parameters.PSObject.Properties.Name -contains "mcpServerSidecar") {
        $paramsJson.parameters.mcpServerSidecar.value = $sidecarMode
    }

    # Resolve azd-substituted Entra admin params. The on-disk parameter file
    # has placeholders like `${POSTGRESQL_ENTRA_ADMIN_OBJECT_ID=}` that only
    # azd knows how to expand — `az deployment` would treat them as literals.
    #
    # IMPORTANT: We intentionally pass EMPTY values for the Entra admin params
    # during this postprovision redeploy. The bicep declares the PG admin child
    # resource as conditional on `!empty(entraAdminObjectId)`, so empty values
    # cause it to be skipped entirely — which is what we want, because:
    #   1. Phase 1 (`azd provision`) already created the Entra admin via the
    #      same bicep with real values.
    #   2. Re-evaluating the admin in a second deployment can race with the
    #      PG server's restart/state transitions and fail with
    #      `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible`.
    #   3. `Initialize-PostgresqlAgeAndData` re-asserts the admin via `az`
    #      after the deploy if needed.
    # We still need to clear the placeholder so `az deployment` doesn't try to
    # use the literal `${POSTGRESQL_ENTRA_ADMIN_OBJECT_ID=}` as an objectId.
    if ($paramsJson.parameters.PSObject.Properties.Name -contains "postgresqlEntraAdminObjectId") {
        $paramsJson.parameters.postgresqlEntraAdminObjectId.value = ""
    }
    if ($paramsJson.parameters.PSObject.Properties.Name -contains "postgresqlEntraAdminPrincipalName") {
        $paramsJson.parameters.postgresqlEntraAdminPrincipalName.value = ""
    }
    if ($paramsJson.parameters.PSObject.Properties.Name -contains "postgresqlEntraAdminPrincipalType") {
        $paramsJson.parameters.postgresqlEntraAdminPrincipalType.value = "User"
    }
    if ($paramsJson.parameters.PSObject.Properties.Name -contains "postgresqlDisablePasswordAuth") {
        $disablePw = Get-AzdEnvValue "POSTGRESQL_DISABLE_PASSWORD_AUTH"
        $paramsJson.parameters.postgresqlDisablePasswordAuth.value = ($disablePw -eq "true")
    }

    $resolvedParamsFile = Join-Path $env:TEMP "azd-deploy-params-resolved.json"
    $paramsJson | ConvertTo-Json -Depth 10 | Set-Content -Path $resolvedParamsFile -Encoding UTF8
    Write-Host "  Resolved parameters written to: $resolvedParamsFile"

    Write-Host "  Starting ARM deployment (this may take several minutes)..."
    Write-Host ""

    $azArgs = @("deployment", "group", "create",
                "--resource-group", $ResourceGroup,
                "--template-file", $templateFile,
                "--parameters", "@$resolvedParamsFile",
                "--name", "postprovision-containers",
                "--no-prompt", "--only-show-errors", "--output", "none")

    $deployJob = Start-Job -ScriptBlock {
        param($azArgs)
        & az @azArgs 2>&1
        $LASTEXITCODE
    } -ArgumentList (,$azArgs)

    while ($deployJob.State -eq 'Running') {
        Start-Sleep -Seconds 10
        Write-Host -NoNewline "."
    }
    Write-Host ""

    $jobOutput = Receive-Job -Job $deployJob -ErrorAction SilentlyContinue
    Remove-Job -Job $deployJob -Force -ErrorAction SilentlyContinue

    $deployExitCode = 0
    if ($null -ne $jobOutput -and $jobOutput.Count -gt 0) {
        $lastLine = $jobOutput[-1]
        if ($lastLine -match '^\d+$') {
            $deployExitCode = [int]$lastLine
            $jobOutput = $jobOutput[0..($jobOutput.Count - 2)]
        }
    }
    foreach ($line in $jobOutput) {
        if (-not [string]::IsNullOrEmpty("$line")) { Write-Host "  $line" }
    }

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

    # Capture deployment outputs and write back to azd env so downstream phases
    # (Phase 0.5 UAMI role provisioning, webapp URL display, etc.) can read
    # the container app names and FQDNs. The initial `azd provision` runs
    # main.bicep with `deploy*ContainerApp=false`, so its outputs for those
    # names are empty — only this postprovision deployment knows them.
    Write-Host "  Capturing container app outputs from deployment..."
    $outputsJson = & az deployment group show `
        --resource-group $ResourceGroup `
        --name "postprovision-containers" `
        --query "properties.outputs" `
        --output json 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($outputsJson)) {
        try {
            $outputs = $outputsJson | ConvertFrom-Json
            $envKeys = @(
                "mcpServerContainerAppName", "mcpServerContainerAppFqdn",
                "backendContainerAppName", "backendContainerAppFqdn",
                "webappContainerAppName", "webappContainerAppFqdn",
                "mcpServerSidecar"
            )
            foreach ($key in $envKeys) {
                if ($outputs.PSObject.Properties.Name -contains $key) {
                    $val = $outputs.$key.value
                    if (-not [string]::IsNullOrEmpty($val)) {
                        Set-AzdEnvValue -Name $key -Value $val
                        Write-Host "    $key = $val"
                    }
                }
            }
        } catch {
            Write-Host "    WARNING: failed to parse deployment outputs: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "    WARNING: could not read deployment outputs." -ForegroundColor Yellow
    }
}

# ============================================================
# MAIN EXECUTION
# ============================================================

$acrName = Get-AzdEnvValue "acrName"
$acrLoginServer = Get-AzdEnvValue "acrLoginServer"
$mcpServerImageName = Get-AzdEnvValue "mcpServerImageName"
$mcpServerImageTag = Get-AzdEnvValue "mcpServerImageTag"
$buildMcpServerContainer = Get-AzdEnvValue "buildMcpServerContainer"
$backendImageName = Get-AzdEnvValue "backendImageName"
$backendImageTag = Get-AzdEnvValue "backendImageTag"
$buildBackendContainer = Get-AzdEnvValue "buildBackendContainer"
$webappImageName = Get-AzdEnvValue "webappImageName"
$webappImageTag = Get-AzdEnvValue "webappImageTag"
$buildWebappContainer = Get-AzdEnvValue "buildWebappContainer"
$resourceGroup = Get-AzdEnvValue "AZURE_RESOURCE_GROUP"
$postgresqlServerName = Get-AzdEnvValue "postgresqlServerName"
$postgresqlServerFqdn = Get-AzdEnvValue "postgresqlServerFqdn"
$postgresqlAdminLogin = Get-AzdEnvValue "postgresqlAdminLogin"
# Entra ID administrator captured by preprovision (signed-in user). Used as
# PGUSER for the data pipeline and as the identity that bootstraps UAMI roles.
$entraAdminObjectId = Get-AzdEnvValue "POSTGRESQL_ENTRA_ADMIN_OBJECT_ID"
$entraAdminUpn = Get-AzdEnvValue "POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_NAME"
$entraAdminType = Get-AzdEnvValue "POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_TYPE"
if ([string]::IsNullOrEmpty($entraAdminType)) { $entraAdminType = "User" }
if ([string]::IsNullOrEmpty($entraAdminUpn)) {
    Write-Host "WARNING: POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_NAME is empty — Entra PG bootstrap may fail." -ForegroundColor Yellow
    Write-Host "  Run preprovision.ps1 (or 'az login' then 'azd up') to capture the signed-in user." -ForegroundColor Yellow
}
# PostgreSQL admin password is still required because the Azure ARM API insists
# on an `administratorLoginPassword` value even when password auth is disabled
# at the server level. The password is generated/preserved by preprovision —
# it is NEVER injected into running apps or used by the data pipeline.
Write-Host "Resolving PostgreSQL admin password (Bicep API requirement only)..."
$postgresqlAdminPassword = Get-PostgresqlAdminPassword
if ([string]::IsNullOrEmpty($postgresqlAdminPassword)) {
    Write-Host "ERROR: Could not resolve PostgreSQL admin password from any source." -ForegroundColor Red
    Write-Host "  Tried: `$env:POSTGRESQL_ADMIN_PASSWORD, azd env value, azd local vault, app_config/.env PGPASSWORD"
    Write-Host "  Set the password explicitly with: azd env set POSTGRESQL_ADMIN_PASSWORD `"<password>`"" -ForegroundColor Yellow
    exit 1
}
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

    # Prefer private endpoint when one was provisioned
    $peInfo = Get-PostgresqlPrivateEndpointInfo -ResourceGroup $resourceGroup -ServerName $postgresqlServerName
    $connectFqdn = $postgresqlServerFqdn
    $usingPrivateEndpoint = $false
    if ($null -ne $peInfo) {
        $usingPrivateEndpoint = $true
        # Wait-ForPrivateEndpointReachable returns whichever FQDN (public or privatelink) the user mapped in hosts.
        $connectFqdn = Show-HostsFileInstructions -PeInfo $peInfo
    } else {
        # No PE — fall back to public access + broad firewall
        Ensure-PostgresqlAllowAllIps -ResourceGroup $resourceGroup -ServerName $postgresqlServerName
    }

    Initialize-PostgresqlAgeAndData -ResourceGroup $resourceGroup -ServerName $postgresqlServerName -AdminUser $postgresqlAdminLogin -EntraAdminUpn $entraAdminUpn -EntraAdminObjectId $entraAdminObjectId -ServerFqdn $postgresqlServerFqdn -GraphName $graphName -ConnectFqdn $connectFqdn

    if (-not $usingPrivateEndpoint) {
        # Remove the broad firewall rule
        Write-Host "Removing temporary firewall rule..."
        Invoke-NativeCommand { az postgres flexible-server firewall-rule delete --resource-group $resourceGroup --name $postgresqlServerName --rule-name "AllowAllIps" --yes 2>&1 | Out-Null }
    }
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

$useDockerDesktop = $false
if (Test-DockerAvailable) {
    $useDockerDesktop = $true
    Write-Host "Build strategy: Docker Desktop (local build + push to ACR)"
} else {
    # Always fall back to ACR remote build — no interactive prompt
    # (azd hook stdin is unreliable; user opted into this default).
    Write-Host "Docker Desktop is not available. Build strategy: ACR remote build"
}

# Build MCP Server (uses Dockerfile.mcp from talent_backend)
if ($buildMcpServerContainer -ne "false") {
    $mcpServerFullPath = Resolve-Path (Join-Path $scriptDir $McpServerPath)
    Write-Host "Checking if MCP Server container needs building..."
    $mcpBuildCheck = Test-BuildNeeded -FolderPath $mcpServerFullPath -HashEnvVarName "mcpServerFolderHash"
    if ($mcpBuildCheck.Needed) {
        if ($useDockerDesktop) {
            Invoke-DockerBuild -RegistryName $acrName -LoginServer $acrLoginServer -SourcePath $mcpServerFullPath -ImageName $mcpServerImageName -ImageTag $mcpServerImageTag -Label "mcp-server" -DockerfileName "Dockerfile.mcp"
        } else {
            Invoke-AcrBuild -RegistryName $acrName -SourcePath $mcpServerFullPath -ImageName $mcpServerImageName -ImageTag $mcpServerImageTag -Label "mcp-server" -DockerfileName "Dockerfile.mcp"
        }
        Save-FolderHash -HashEnvVarName "mcpServerFolderHash" -Hash $mcpBuildCheck.Hash
        Write-Host "MCP Server container built: $acrLoginServer/${mcpServerImageName}:${mcpServerImageTag}"
    } else {
        Write-Host "MCP Server container is up-to-date, skipping build."
    }
}

# Build Backend (uses Dockerfile from talent_backend)
if ($buildBackendContainer -ne "false") {
    $backendFullPath = Resolve-Path (Join-Path $scriptDir $BackendPath)
    Write-Host "Checking if Backend container needs building..."
    $backendBuildCheck = Test-BuildNeeded -FolderPath $backendFullPath -HashEnvVarName "backendFolderHash"
    if ($backendBuildCheck.Needed) {
        if ($useDockerDesktop) {
            Invoke-DockerBuild -RegistryName $acrName -LoginServer $acrLoginServer -SourcePath $backendFullPath -ImageName $backendImageName -ImageTag $backendImageTag -Label "backend"
        } else {
            Invoke-AcrBuild -RegistryName $acrName -SourcePath $backendFullPath -ImageName $backendImageName -ImageTag $backendImageTag -Label "backend"
        }
        Save-FolderHash -HashEnvVarName "backendFolderHash" -Hash $backendBuildCheck.Hash
        Write-Host "Backend container built: $acrLoginServer/${backendImageName}:${backendImageTag}"
    } else {
        Write-Host "Backend container is up-to-date, skipping build."
    }
}

# Build Webapp (uses Dockerfile from talent_ui)
if ($buildWebappContainer -ne "false") {
    $webappFullPath = Resolve-Path (Join-Path $scriptDir $WebappPath)
    Write-Host "Checking if Webapp container needs building..."
    $webappBuildCheck = Test-BuildNeeded -FolderPath $webappFullPath -HashEnvVarName "webappFolderHash"
    if ($webappBuildCheck.Needed) {
        $backendFqdn = Get-AzdEnvValue "backendContainerAppFqdn"
        $buildArgs = @()
        if (-not [string]::IsNullOrEmpty($backendFqdn)) {
            $buildArgs += "VITE_API_BASE_URL=https://${backendFqdn}"
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

# ---- DEPLOY PHASE: Single ARM deployment for all container apps ----
Invoke-ContainerAppsDeploy -ResourceGroup $resourceGroup -PostgresqlAdminPassword $postgresqlAdminPassword

# ---- PHASE 0.5: Register container app UAMIs as PostgreSQL Entra roles ----
# The Bicep deployment above creates a user-assigned managed identity per
# container app (named `<containerAppName>-identity`). For each app to be able
# to authenticate to PostgreSQL with its token, the server must have a
# matching role created via `pgaadauth_create_principal_with_oid`. This is the
# Entra-equivalent of `CREATE USER ... WITH PASSWORD ...` and must be done by
# an existing Entra administrator.
if (-not [string]::IsNullOrEmpty($postgresqlServerName)) {
    Write-Host "=========================================="
    Write-Host "PHASE 0.5: Registering container app UAMIs as PG Entra roles"
    Write-Host "=========================================="

    # Always discover UAMIs first — they're needed for both SQL and control-plane paths.
    # In MCP sidecar mode (default), `mcpServerContainerAppName` is empty because the
    # standalone MCP module is gated off in bicep. The loop below naturally skips empty
    # app names, so only the backend UAMI is registered — which the MCP sidecar reuses
    # via the shared pod identity (AZURE_CLIENT_ID is injected into both containers).
    $mcpServerSidecarRaw = Get-AzdEnvValue "mcpServerSidecar"
    $sidecarMode = -not ($mcpServerSidecarRaw -eq "false" -or $mcpServerSidecarRaw -eq "False" -or $mcpServerSidecarRaw -eq "FALSE")
    if ($sidecarMode) {
        Write-Host "  MCP sidecar mode: only registering backend UAMI (MCP shares it via sidecar pattern)." -ForegroundColor Cyan
    }
    $mcpAppName = Get-AzdEnvValue "mcpServerContainerAppName"
    $backendAppName = Get-AzdEnvValue "backendContainerAppName"

    $principals = @()
    foreach ($app in @($mcpAppName, $backendAppName)) {
        if ([string]::IsNullOrEmpty($app)) { continue }
        $uamiName = "$app-identity"
        Write-Host "  Looking up UAMI '$uamiName'..."
        $oid = (& az identity show --resource-group $resourceGroup --name $uamiName --query principalId -o tsv 2>$null)
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($oid)) {
            Write-Host "    WARNING: could not resolve principalId for '$uamiName'. Skipping." -ForegroundColor Yellow
            continue
        }
        Write-Host "    principalId: $oid"
        $principals += [ordered]@{ name = $uamiName; oid = $oid.Trim(); type = "service" }
    }

    if ($principals.Count -eq 0) {
        Write-Host "  No container app UAMIs found to register."
    } else {
        # Strategy:
        #   1. Preferred: pgaadauth_create_principal_with_oid via SQL (narrow grants).
        #      Requires the deployer to have outbound TCP/5432 to PG.
        #   2. Fallback: az postgres flexible-server microsoft-entra-admin create
        #      --type ServicePrincipal (Azure control plane, no PG SQL hop).
        #      Grants ADMIN — broader than SQL, but unblocks containers when
        #      port 5432 is filtered (Comcast and many residential ISPs do this).
        #
        # Set POSTGRESQL_USE_CONTROL_PLANE_UAMI=true to skip the SQL attempt
        # entirely (saves ~30s when you know your network blocks 5432).
        $forceControlPlane = (Get-AzdEnvValue "POSTGRESQL_USE_CONTROL_PLANE_UAMI") -eq "true"
        $sqlSucceeded = $false

        if (-not $forceControlPlane) {
            if ([string]::IsNullOrEmpty($entraAdminUpn)) {
                Write-Host "  Cannot attempt SQL path: POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_NAME is empty." -ForegroundColor Yellow
                Write-Host "  Skipping straight to control-plane fallback." -ForegroundColor Yellow
            } else {
                $principalsJson = $principals | ConvertTo-Json -Compress
                if ($principals.Count -eq 1) {
                    # ConvertTo-Json emits a single object instead of a 1-element array
                    $principalsJson = "[$principalsJson]"
                }

                $repoRoot = Resolve-Path (Join-Path $scriptDir "../..")
                $venvPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
                $pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }
                $provisionScript = Join-Path $scriptDir "../scripts/provision_pg_entra_roles.py"
                $provisionScript = Resolve-Path $provisionScript

                $connectHost = if (-not [string]::IsNullOrEmpty($connectFqdn)) { $connectFqdn } else { $postgresqlServerFqdn }

                Write-Host "  Attempting SQL path: provisioning $($principals.Count) Entra role(s) on $connectHost..."
                & $pythonExe $provisionScript `
                    --host $connectHost `
                    --database "postgres" `
                    --admin-upn $entraAdminUpn `
                    --graph-name $graphName `
                    --principals $principalsJson
                if ($LASTEXITCODE -eq 0) {
                    $sqlSucceeded = $true
                    Write-Host "  UAMI roles provisioned successfully via SQL." -ForegroundColor Green
                } else {
                    Write-Host "  SQL path failed (exit $LASTEXITCODE). Falling back to control-plane admin registration." -ForegroundColor Yellow
                    Write-Host "  Common cause: deployer network blocks outbound TCP/5432 to PG (Comcast and many ISPs do this)." -ForegroundColor Yellow
                }
            }
        } else {
            Write-Host "  POSTGRESQL_USE_CONTROL_PLANE_UAMI=true — skipping SQL path." -ForegroundColor Cyan
        }

        if (-not $sqlSucceeded) {
            Write-Host ""
            Write-Host "  Control-plane fallback: registering UAMIs as ServicePrincipal admins on $postgresqlServerName..."
            Write-Host "  NOTE: this grants PG ADMIN privileges (broader than the SQL path's narrow grants)." -ForegroundColor DarkYellow
            $allOk = $true
            foreach ($p in $principals) {
                $ok = Register-PgUamiAsEntraAdmin `
                    -ResourceGroup $resourceGroup `
                    -ServerName $postgresqlServerName `
                    -UamiName $p.name `
                    -ObjectId $p.oid
                if (-not $ok) { $allOk = $false }
            }
            if ($allOk) {
                Write-Host "  All UAMIs registered as PG Entra admins via control plane." -ForegroundColor Green
                Write-Host "  Restart container revisions to pick up the new PG roles:" -ForegroundColor DarkGray
                foreach ($p in $principals) {
                    $appName = $p.name -replace '-identity$', ''
                    Write-Host "    az containerapp revision restart -n $appName -g $resourceGroup --revision <active-revision>" -ForegroundColor DarkGray
                }
            } else {
                Write-Host "  ERROR: one or more UAMI control-plane registrations failed." -ForegroundColor Red
                Write-Host "  Container apps will fail to connect to PostgreSQL until you re-register them." -ForegroundColor Yellow
            }
        }
    }
}

# Final defensive check: if any PG server parameter (e.g. shared_preload_libraries=age)
# is still flagged pending restart, restart now so AGE actually loads. Without this,
# every cypher() call fails with `unhandled cypher(cstring) function call`.
if (-not [string]::IsNullOrEmpty($postgresqlServerName)) {
    Ensure-PostgresqlConfigApplied -ResourceGroup $resourceGroup -ServerName $postgresqlServerName
}

Write-Host "=========================================="
Write-Host "Post-provision completed successfully."
Write-Host "=========================================="

# Display webapp URL
$webappFqdn = Get-AzdEnvValue "webappContainerAppFqdn"
if (-not [string]::IsNullOrEmpty($webappFqdn)) {
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "  Webapp URL: https://$webappFqdn" -ForegroundColor Green
    Write-Host "=========================================="
    Write-Host ""

    # Register the webapp URL as an Entra SPA redirect URI so MSAL sign-in works.
    # Resolves client ID from azd env (entraSpaClientId) or talent_ui/src/authConfig.js.
    $webappSourcePath = Resolve-Path (Join-Path $scriptDir $WebappPath) -ErrorAction SilentlyContinue
    if ($webappSourcePath) {
        $entraSpaClientId = Get-EntraSpaClientId -WebappSourcePath $webappSourcePath.Path
        Register-WebappRedirectUri -AppClientId $entraSpaClientId -WebappFqdn $webappFqdn
    }
}
