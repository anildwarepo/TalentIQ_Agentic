#!/bin/bash
#
# Post-provision hook for TalentIQ: PostgreSQL AGE init + data loading,
# Docker builds for 3 images, container app deployment via ARM.
#

set -euo pipefail

# Guard against recursive execution
if [ "${AZD_POSTPROVISION_PHASE:-}" = "1" ]; then
  echo "Skipping nested postprovision hook (provision phase in progress)."
  exit 0
fi

MCP_SERVER_PATH="${1:-../../talent_backend}"
BACKEND_PATH="${2:-../../talent_backend}"
WEBAPP_PATH="${3:-../../talent_ui}"

get_azd_env() {
  # azd writes errors like "ERROR: key '<name>' not found..." to stdout
  # (not stderr), so 2>/dev/null does NOT suppress them. Filter explicitly.
  local raw
  raw=$(azd env get-value "$1" 2>&1)
  printf '%s\n' "$raw" \
    | tr -d '\r' \
    | grep -vE '^(ERROR:|WARNING:|To update|winget upgrade)' \
    | grep -v '^$' \
    | head -n1
}

# Resolves a vault://<vault-id>/<entry-id> reference from .azure/<env>/config.json
# against the local azd vault file at ~/.azd/vaults/<vault-id>.json.
# azd auto-migrates secret-like env values (e.g. *PASSWORD*) into the encrypted
# local vault. `azd env get-value KEY` does NOT resolve these references, so we
# must read the vault file directly. Entries are stored base64-encoded.
resolve_azd_vault_secret() {
  local param_name="$1"
  local env_name
  env_name=$(get_azd_env "AZURE_ENV_NAME")
  [ -z "$env_name" ] && return 0
  local script_dir
  script_dir="$(cd "$(dirname "$0")" && pwd)"
  local config_path="$script_dir/../.azure/$env_name/config.json"
  [ ! -f "$config_path" ] && return 0
  local vault_ref
  vault_ref=$(jq -r ".infra.parameters.${param_name} // empty" "$config_path" 2>/dev/null)
  case "$vault_ref" in
    vault://*) ;;
    *) return 0 ;;
  esac
  local stripped="${vault_ref#vault://}"
  local vault_id="${stripped%%/*}"
  local entry_id="${stripped#*/}"
  [ -z "$vault_id" ] || [ -z "$entry_id" ] && return 0
  local vault_path="$HOME/.azd/vaults/$vault_id.json"
  [ ! -f "$vault_path" ] && return 0
  local encoded
  encoded=$(jq -r ".[\"$entry_id\"] // empty" "$vault_path" 2>/dev/null)
  [ -z "$encoded" ] && return 0
  printf '%s' "$encoded" | base64 -d 2>/dev/null
}

# Multi-strategy resolver for the PostgreSQL admin password.
# Modern azd (1.23+) auto-migrates *PASSWORD* env values to the encrypted vault,
# so `azd env get-value` alone returns empty. Must check vault and the source-of-truth
# .env file as fallbacks. Echoes the resolved password, or empty if none found.
get_postgresql_admin_password() {
  # 1. azd-injected env var
  if [ -n "${POSTGRESQL_ADMIN_PASSWORD:-}" ]; then
    echo "  Password source: \$POSTGRESQL_ADMIN_PASSWORD (azd-injected)" >&2
    printf '%s' "$POSTGRESQL_ADMIN_PASSWORD"
    return 0
  fi
  # 2. azd env get-value (only works if NOT vault-migrated)
  local v
  v=$(get_azd_env "POSTGRESQL_ADMIN_PASSWORD")
  if [ -n "$v" ]; then
    echo "  Password source: azd env value POSTGRESQL_ADMIN_PASSWORD" >&2
    printf '%s' "$v"
    return 0
  fi
  # 3. Resolve vault reference from config.json
  v=$(resolve_azd_vault_secret "postgresqlAdminPassword")
  if [ -n "$v" ]; then
    echo "  Password source: azd local vault (resolved via config.json reference)" >&2
    printf '%s' "$v"
    return 0
  fi
  # 4. Read PGPASSWORD from app_config/.env (same source preprovision uses)
  local script_dir
  script_dir="$(cd "$(dirname "$0")" && pwd)"
  local app_env="$script_dir/../../app_config/.env"
  if [ -f "$app_env" ]; then
    v=$(grep -E '^PGPASSWORD=' "$app_env" | head -n1 | sed -E 's/^PGPASSWORD=(.+)$/\1/' | tr -d '\r')
    if [ -n "$v" ]; then
      echo "  Password source: app_config/.env PGPASSWORD" >&2
      printf '%s' "$v"
      return 0
    fi
  fi
  printf '%s' ""
}

set_azd_env() {
  azd env set "$1" "$2" >/dev/null
}

get_folder_hash() {
  local folder_path="$1"
  find "$folder_path" -type f \
    ! -path "*/__pycache__/*" \
    ! -path "*/node_modules/*" \
    ! -path "*/.git/*" \
    ! -name "*.pyc" \
    ! -name "*.pyo" \
    ! -path "*.egg-info/*" \
    -exec md5sum {} \; 2>/dev/null | sort | md5sum | cut -d' ' -f1
}

build_needed() {
  local folder_path="$1"
  local hash_env_var="$2"
  local current_hash
  current_hash=$(get_folder_hash "$folder_path")
  local stored_hash
  stored_hash=$(get_azd_env "$hash_env_var")
  if [ "$current_hash" = "$stored_hash" ]; then
    echo "false;$current_hash"
  else
    echo "true;$current_hash"
  fi
}

wait_postgres_ready() {
  local resource_group="$1"
  local server_name="$2"
  for attempt in $(seq 1 60); do
    state=$(az postgres flexible-server show --resource-group "$resource_group" --name "$server_name" --query "state" -o tsv 2>/dev/null || true)
    if [ "$state" = "Ready" ]; then return 0; fi
    echo "Waiting for PostgreSQL server to be Ready (attempt $attempt/60, current state: $state)..."
    sleep 10
  done
  echo "ERROR: PostgreSQL server did not reach Ready state in time."
  exit 1
}

ensure_postgres_allow_all_ips() {
  local resource_group="$1"
  local server_name="$2"
  if [ -z "$resource_group" ] || [ -z "$server_name" ]; then return; fi
  echo "Opening PostgreSQL firewall to all IPs for data loading..."
  az postgres flexible-server firewall-rule create \
    --resource-group "$resource_group" \
    --name "$server_name" \
    --rule-name "AllowAllIps" \
    --start-ip-address "0.0.0.0" \
    --end-ip-address "255.255.255.255" >/dev/null
}

# Sets the global PE_PRIVATE_IP and PE_PRIVATELINK_FQDN if a PE exists; otherwise leaves them empty.
get_postgres_private_endpoint_info() {
  PE_PRIVATE_IP=""
  PE_PRIVATELINK_FQDN=""
  PE_PUBLIC_FQDN=""
  local resource_group="$1"
  local server_name="$2"
  if [ -z "$resource_group" ] || [ -z "$server_name" ]; then return; fi

  local pe_name="${server_name}-pe"
  echo "Looking up private endpoint '$pe_name' in resource group '$resource_group'..."

  local nic_id
  nic_id=$(az network private-endpoint show \
    --name "$pe_name" --resource-group "$resource_group" \
    --query "networkInterfaces[0].id" -o tsv 2>/dev/null || true)
  if [ -z "$nic_id" ]; then
    echo "  Private endpoint '$pe_name' not found. PE-based connectivity disabled."
    return
  fi

  local private_ip
  private_ip=$(az network nic show --ids "$nic_id" \
    --query "ipConfigurations[0].privateIPAddress" -o tsv 2>/dev/null || true)
  if [ -z "$private_ip" ]; then
    echo "  Could not retrieve private IP from NIC '$nic_id'."
    return
  fi

  PE_PRIVATE_IP="$private_ip"
  PE_PRIVATELINK_FQDN="${server_name}.privatelink.postgres.database.azure.com"
  PE_PUBLIC_FQDN="${server_name}.postgres.database.azure.com"
}

show_hosts_file_instructions() {
  local private_ip="$1"
  local privatelink_fqdn="$2"
  local public_fqdn="$3"
  local timeout_seconds="${4:-600}"
  local poll_seconds="${5:-5}"

  # Result is communicated via the global WAIT_RESULT_FQDN (bash 3.x compatible — no nameref).
  WAIT_RESULT_FQDN=""

  echo ""
  echo "============================================================"
  echo "  PostgreSQL private endpoint — hosts file entry required"
  echo "============================================================"
  echo ""
  echo "  PostgreSQL is reachable only via private endpoint."
  echo "  Add ONE of the following lines to your hosts file so the data"
  echo "  pipeline can connect to it from this machine. Either form works."
  echo ""
  echo "  Hosts file location:"
  echo "    /etc/hosts"
  echo ""
  echo "  Option A (recommended — matches TLS cert CN):"
  echo "    ${private_ip}  ${public_fqdn}"
  echo ""
  echo "  Option B (privatelink FQDN):"
  echo "    ${private_ip}  ${privatelink_fqdn}"
  echo ""
  echo "  Option C (both on one line):"
  echo "    ${private_ip}  ${public_fqdn}  ${privatelink_fqdn}"
  echo ""
  echo "  This script will poll every ${poll_seconds} seconds and continue"
  echo "  automatically once the entry resolves correctly. Timeout: ${timeout_seconds}s."
  echo ""
  echo "============================================================"
  echo ""

  local candidates=("$public_fqdn" "$privatelink_fqdn")
  local deadline=$(( $(date +%s) + timeout_seconds ))
  local attempt=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    attempt=$(( attempt + 1 ))
    local status_line=""
    for fqdn in "${candidates[@]}"; do
      local resolved_ip=""
      if command -v getent >/dev/null 2>&1; then
        resolved_ip=$(getent hosts "$fqdn" 2>/dev/null | awk '{print $1; exit}')
      elif command -v dscacheutil >/dev/null 2>&1; then
        resolved_ip=$(dscacheutil -q host -a name "$fqdn" 2>/dev/null | awk '/ip_address:/ {print $2; exit}')
      elif command -v host >/dev/null 2>&1; then
        resolved_ip=$(host "$fqdn" 2>/dev/null | awk '/has address/ {print $4; exit}')
      fi

      if [ "$resolved_ip" = "$private_ip" ]; then
        local port_open=false
        if command -v nc >/dev/null 2>&1; then
          if nc -z -w 3 "$fqdn" 5432 >/dev/null 2>&1; then port_open=true; fi
        else
          if (echo >/dev/tcp/"$fqdn"/5432) >/dev/null 2>&1; then port_open=true; fi
        fi
        if [ "$port_open" = "true" ]; then
          echo "  [OK] $fqdn resolves to $resolved_ip and port 5432 is open. Using this FQDN to connect."
          WAIT_RESULT_FQDN="$fqdn"
          return 0
        fi
        status_line+="$fqdn → port not reachable; "
      elif [ -z "$resolved_ip" ]; then
        status_line+="$fqdn → not resolving; "
      else
        status_line+="$fqdn → resolves to $resolved_ip (expected $private_ip); "
      fi
    done
    echo "  [poll $attempt] ${status_line%; }. Retrying in ${poll_seconds}s..."
    sleep "$poll_seconds"
  done

  echo "ERROR: Timed out after ${timeout_seconds}s. Neither $public_fqdn nor $privatelink_fqdn resolved to $private_ip with port 5432 open. Verify your hosts file entry." >&2
  return 1
}

initialize_postgres_age_and_data() {
  local resource_group="$1"
  local server_name="$2"
  local admin_user="$3"
  local admin_password="$4"
  local server_fqdn="$5"
  local graph_name="$6"
  local connect_fqdn="${7:-$server_fqdn}"

  if [ -z "$server_name" ] || [ -z "$resource_group" ]; then
    echo "Skipping PostgreSQL AGE/data initialization (no server provisioned)."
    return
  fi
  if [ -z "$admin_password" ]; then
    echo "ERROR: Cannot initialize PostgreSQL — admin password is empty." >&2
    echo "  Refusing to proceed; doing so would reset the server password to empty and lock it out." >&2
    exit 1
  fi

  local effective_admin_user="${admin_user:-tiqadmin}"
  local effective_graph_name="${graph_name:-talent_graph}"

  echo "Configuring PostgreSQL server parameters for AGE..."
  az postgres flexible-server parameter set --resource-group "$resource_group" --server-name "$server_name" --name azure.extensions --value 'AGE,VECTOR,PG_TRGM,PG_DISKANN' >/dev/null
  az postgres flexible-server parameter set --resource-group "$resource_group" --server-name "$server_name" --name shared_preload_libraries --value age >/dev/null

  echo "Restarting PostgreSQL server..."
  az postgres flexible-server restart --resource-group "$resource_group" --name "$server_name" >/dev/null
  wait_postgres_ready "$resource_group" "$server_name"

  echo "Resetting PostgreSQL admin password..."
  az postgres flexible-server update \
    --resource-group "$resource_group" \
    --name "$server_name" \
    --admin-password "$admin_password" \
    --output none >/dev/null
  wait_postgres_ready "$resource_group" "$server_name"

  local script_dir
  script_dir="$(cd "$(dirname "$0")" && pwd)"
  local repo_root
  repo_root="$(cd "$script_dir/../.." && pwd)"
  local data_pipeline_script="$repo_root/talent_data_pipeline/main.py"
  local python_exe
  if [ -f "$repo_root/.venv/bin/python" ]; then
    python_exe="$repo_root/.venv/bin/python"
  else
    python_exe="python3"
  fi

  export PGHOST="$connect_fqdn"
  export PGPORT="5432"
  export PGDATABASE="postgres"
  export PGUSER="$effective_admin_user"
  export PGPASSWORD="$admin_password"
  export PGSSLMODE="require"
  export GRAPH_NAME="$effective_graph_name"

  if [ ! -f "$data_pipeline_script" ]; then
    echo "WARNING: Data pipeline script not found at $data_pipeline_script. Skipping data load."
    return
  fi

  echo "Running TalentIQ data pipeline..."
  local max_attempts=3
  for attempt in $(seq 1 $max_attempts); do
    if "$python_exe" "$data_pipeline_script"; then
      echo "TalentIQ data pipeline complete."
      return
    fi
    if [ "$attempt" -lt "$max_attempts" ]; then
      echo "Data pipeline failed (attempt $attempt/$max_attempts). Retrying in 20 seconds..."
      sleep 20
    else
      echo "ERROR: Data pipeline failed after $max_attempts attempts."
      exit 1
    fi
  done
}

docker_build() {
  local registry_name="$1"
  local login_server="$2"
  local source_path="$3"
  local image_name="$4"
  local image_tag="$5"
  local label="$6"
  local dockerfile="${7:-Dockerfile}"
  shift 7 || true

  echo "  Building $label container locally with Docker..."
  echo "  Logging into ACR $registry_name..."
  az acr login --name "$registry_name" >/dev/null 2>&1

  local full_tagged="${login_server}/${image_name}:${image_tag}"
  local full_latest="${login_server}/${image_name}:latest"

  local build_args=()
  for arg in "$@"; do
    build_args+=(--build-arg "$arg")
  done

  (cd "$source_path" && docker build -t "$full_tagged" -t "$full_latest" -f "$dockerfile" "${build_args[@]}" --provenance=false --sbom=false .)
  docker push "$full_tagged"
  docker push "$full_latest"
  echo "  $label image pushed successfully."
}

acr_build() {
  local registry_name="$1"
  local source_path="$2"
  local image_name="$3"
  local image_tag="$4"
  local label="$5"
  local dockerfile="${6:-Dockerfile}"
  shift 6 || true

  echo "  Building $label container in ACR $registry_name..."
  local build_args=()
  for arg in "$@"; do
    build_args+=(--build-arg "$arg")
  done

  (cd "$source_path" && az acr build --registry "$registry_name" \
    --image "${image_name}:${image_tag}" \
    --image "${image_name}:latest" \
    --file "$dockerfile" . \
    "${build_args[@]}" --only-show-errors)
}

deploy_container_apps() {
  local resource_group="$1"
  local pg_password="$2"

  echo ""
  echo "=========================================="
  echo "DEPLOY PHASE: Deploying all container apps"
  echo "=========================================="

  local script_dir
  script_dir="$(cd "$(dirname "$0")" && pwd)"
  local infra_dir="$script_dir/../infra"
  local template_file="$infra_dir/main.bicep"
  local params_file="$infra_dir/main.parameters.json"

  if [ ! -f "$template_file" ]; then echo "ERROR: Bicep template not found: $template_file"; exit 1; fi
  if [ ! -f "$params_file" ]; then echo "ERROR: Parameters file not found: $params_file"; exit 1; fi

  local client_ip
  client_ip=$(get_azd_env "CLIENT_IP_ADDRESS")
  [ -z "$client_ip" ] && client_ip="0.0.0.0"

  echo "  Resource Group:   $resource_group"
  echo "  Deploy flags:     MCP=true, Backend=true, Webapp=true"

  local resolved_params
  resolved_params=$(mktemp)
  # Use jq to resolve params
  jq --arg pw "$pg_password" --arg ip "$client_ip" \
    '.parameters.postgresqlAdminPassword.value = $pw |
     .parameters.clientIpAddress.value = $ip |
     .parameters.deployContainerAppsEnv.value = true |
     .parameters.deployMcpServerContainerApp.value = true |
     .parameters.deployBackendContainerApp.value = true |
     .parameters.deployWebappContainerApp.value = true' \
    "$params_file" > "$resolved_params"

  echo "  Starting ARM deployment..."
  az deployment group create \
    --resource-group "$resource_group" \
    --template-file "$template_file" \
    --parameters "@$resolved_params" \
    --name "postprovision-containers" \
    --no-prompt --only-show-errors --output none

  rm -f "$resolved_params"
  echo "  Container app deployment completed successfully."
}

# ============================================================
# MAIN EXECUTION
# ============================================================

acrName=$(get_azd_env "acrName")
acrLoginServer=$(get_azd_env "acrLoginServer")
mcpServerImageName=$(get_azd_env "mcpServerImageName")
mcpServerImageTag=$(get_azd_env "mcpServerImageTag")
buildMcpServerContainer=$(get_azd_env "buildMcpServerContainer")
backendImageName=$(get_azd_env "backendImageName")
backendImageTag=$(get_azd_env "backendImageTag")
buildBackendContainer=$(get_azd_env "buildBackendContainer")
webappImageName=$(get_azd_env "webappImageName")
webappImageTag=$(get_azd_env "webappImageTag")
buildWebappContainer=$(get_azd_env "buildWebappContainer")
resourceGroup=$(get_azd_env "AZURE_RESOURCE_GROUP")
postgresqlServerName=$(get_azd_env "postgresqlServerName")
postgresqlServerFqdn=$(get_azd_env "postgresqlServerFqdn")
postgresqlAdminLogin=$(get_azd_env "postgresqlAdminLogin")
echo "Resolving PostgreSQL admin password..."
postgresqlAdminPassword=$(get_postgresql_admin_password)
if [ -z "$postgresqlAdminPassword" ]; then
  echo "ERROR: Could not resolve PostgreSQL admin password from any source." >&2
  echo "  Tried: \$POSTGRESQL_ADMIN_PASSWORD, azd env value, azd local vault, app_config/.env PGPASSWORD" >&2
  echo "  Set the password explicitly with: azd env set POSTGRESQL_ADMIN_PASSWORD \"<password>\"" >&2
  exit 1
fi
graphName=$(get_azd_env "graphName")
initializePostgresqlAge=$(get_azd_env "initializePostgresqlAge")

if [ -z "$acrName" ]; then
  echo "ACR not deployed, skipping container builds"
  exit 0
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"

# ---- PHASE 0: PostgreSQL AGE initialization (flag-gated) ----
if [ -n "$postgresqlServerName" ] && [ "$initializePostgresqlAge" != "false" ]; then
  wait_postgres_ready "$resourceGroup" "$postgresqlServerName"

  # Prefer private endpoint when one was provisioned
  get_postgres_private_endpoint_info "$resourceGroup" "$postgresqlServerName"
  connect_fqdn="$postgresqlServerFqdn"
  using_private_endpoint=false
  if [ -n "$PE_PRIVATE_IP" ]; then
    using_private_endpoint=true
    show_hosts_file_instructions "$PE_PRIVATE_IP" "$PE_PRIVATELINK_FQDN" "$PE_PUBLIC_FQDN"
    # show_hosts_file_instructions writes the winning FQDN to WAIT_RESULT_FQDN.
    if [ -n "$WAIT_RESULT_FQDN" ]; then
      connect_fqdn="$WAIT_RESULT_FQDN"
    else
      connect_fqdn="$PE_PRIVATELINK_FQDN"
    fi
  else
    ensure_postgres_allow_all_ips "$resourceGroup" "$postgresqlServerName"
  fi

  initialize_postgres_age_and_data "$resourceGroup" "$postgresqlServerName" "$postgresqlAdminLogin" "$postgresqlAdminPassword" "$postgresqlServerFqdn" "$graphName" "$connect_fqdn"

  if [ "$using_private_endpoint" != "true" ]; then
    echo "Removing temporary firewall rule..."
    az postgres flexible-server firewall-rule delete --resource-group "$resourceGroup" --name "$postgresqlServerName" --rule-name "AllowAllIps" --yes >/dev/null
  fi
  set_azd_env "initializePostgresqlAge" "false"
  echo "PostgreSQL AGE initialization complete."
else
  echo "Skipping PostgreSQL AGE initialization."
fi

# ---- BUILD PHASE ----
echo "=========================================="
echo "Building container images..."
echo "=========================================="

use_docker=false
if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
  use_docker=true
  echo "Build strategy: Docker Desktop (local build + push to ACR)"
else
  echo "Build strategy: ACR remote build"
fi

# Build MCP Server (Dockerfile.mcp from talent_backend)
if [ "$buildMcpServerContainer" != "false" ]; then
  mcp_path="$(cd "$script_dir/$MCP_SERVER_PATH" && pwd)"
  echo "Checking if MCP Server container needs building..."
  result=$(build_needed "$mcp_path" "mcpServerFolderHash")
  needed=$(echo "$result" | cut -d';' -f1)
  hash=$(echo "$result" | cut -d';' -f2)
  if [ "$needed" = "true" ]; then
    if [ "$use_docker" = "true" ]; then
      docker_build "$acrName" "$acrLoginServer" "$mcp_path" "$mcpServerImageName" "$mcpServerImageTag" "mcp-server" "Dockerfile.mcp"
    else
      acr_build "$acrName" "$mcp_path" "$mcpServerImageName" "$mcpServerImageTag" "mcp-server" "Dockerfile.mcp"
    fi
    set_azd_env "mcpServerFolderHash" "$hash"
    echo "MCP Server container built."
  else
    echo "MCP Server container is up-to-date, skipping build."
  fi
fi

# Build Backend (Dockerfile from talent_backend)
if [ "$buildBackendContainer" != "false" ]; then
  backend_path="$(cd "$script_dir/$BACKEND_PATH" && pwd)"
  echo "Checking if Backend container needs building..."
  result=$(build_needed "$backend_path" "backendFolderHash")
  needed=$(echo "$result" | cut -d';' -f1)
  hash=$(echo "$result" | cut -d';' -f2)
  if [ "$needed" = "true" ]; then
    if [ "$use_docker" = "true" ]; then
      docker_build "$acrName" "$acrLoginServer" "$backend_path" "$backendImageName" "$backendImageTag" "backend"
    else
      acr_build "$acrName" "$backend_path" "$backendImageName" "$backendImageTag" "backend"
    fi
    set_azd_env "backendFolderHash" "$hash"
    echo "Backend container built."
  else
    echo "Backend container is up-to-date, skipping build."
  fi
fi

# Build Webapp (Dockerfile from talent_ui)
if [ "$buildWebappContainer" != "false" ]; then
  webapp_path="$(cd "$script_dir/$WEBAPP_PATH" && pwd)"
  echo "Checking if Webapp container needs building..."
  result=$(build_needed "$webapp_path" "webappFolderHash")
  needed=$(echo "$result" | cut -d';' -f1)
  hash=$(echo "$result" | cut -d';' -f2)
  if [ "$needed" = "true" ]; then
    backend_fqdn=$(get_azd_env "backendContainerAppFqdn")
    build_args=()
    if [ -n "$backend_fqdn" ]; then
      build_args+=("VITE_API_BASE_URL=https://${backend_fqdn}")
    fi
    if [ "$use_docker" = "true" ]; then
      docker_build "$acrName" "$acrLoginServer" "$webapp_path" "$webappImageName" "$webappImageTag" "webapp" "Dockerfile" "${build_args[@]}"
    else
      acr_build "$acrName" "$webapp_path" "$webappImageName" "$webappImageTag" "webapp" "Dockerfile" "${build_args[@]}"
    fi
    set_azd_env "webappFolderHash" "$hash"
    echo "Webapp container built."
  else
    echo "Webapp container is up-to-date, skipping build."
  fi
fi

# ---- DEPLOY PHASE ----
deploy_container_apps "$resourceGroup" "$postgresqlAdminPassword"

echo "=========================================="
echo "Post-provision completed successfully."
echo "=========================================="

webapp_fqdn=$(get_azd_env "webappContainerAppFqdn")
if [ -n "$webapp_fqdn" ]; then
  echo ""
  echo "=========================================="
  echo "  Webapp URL: https://$webapp_fqdn"
  echo "=========================================="
  echo ""
fi
