#!/bin/bash
#
# Post-provision hook to initialize PostgreSQL AGE, build containers, and deploy apps in sequence.
#

set -euo pipefail

# Guard against recursive execution: when deploy_all_container_apps calls
# 'azd provision --no-prompt', azd re-triggers hooks.  Skip the nested run.
if [ "${AZD_POSTPROVISION_PHASE:-}" = "1" ]; then
  echo "Skipping nested postprovision hook (provision phase in progress)."
  exit 0
fi

MCP_SERVER_PATH="${1:-../../mcp_server}"
FASTAPI_PATH="${2:-../../af_fastapi}"
WEBAPP_PATH="${3:-../../webapp}"

get_azd_env() {
  azd env get-value "$1" 2>/dev/null | tr -d '\r'
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

  for attempt in {1..60}; do
    state=$(az postgres flexible-server show --resource-group "$resource_group" --name "$server_name" --query "state" -o tsv 2>/dev/null || true)
    if [ "$state" = "Ready" ]; then
      return 0
    fi
    echo "Waiting for PostgreSQL server to be Ready (attempt $attempt/60, current state: $state)..."
    sleep 10
  done

  echo "ERROR: PostgreSQL server did not reach Ready state in time."
  exit 1
}

ensure_postgres_allow_all_ips() {
  local resource_group="$1"
  local server_name="$2"

  if [ -z "$resource_group" ] || [ -z "$server_name" ]; then
    return
  fi

  echo "Opening PostgreSQL firewall to all IPs for data loading..."
  az postgres flexible-server firewall-rule create \
    --resource-group "$resource_group" \
    --name "$server_name" \
    --rule-name "AllowAllIps" \
    --start-ip-address "0.0.0.0" \
    --end-ip-address "255.255.255.255" >/dev/null
}

initialize_postgres_age_and_data() {
  local resource_group="$1"
  local server_name="$2"
  local admin_user="$3"
  local admin_password="$4"
  local server_fqdn="$5"
  local graph_name="$6"

  if [ -z "$server_name" ] || [ -z "$resource_group" ] || [ -z "$admin_password" ]; then
    echo "Skipping PostgreSQL AGE/data initialization (missing required values)."
    return
  fi

  if [ -z "$admin_user" ]; then
    admin_user="pgadmin"
  fi
  if [ -z "$graph_name" ]; then
    graph_name="customer_graph"
  fi

  echo "Configuring PostgreSQL server parameters for AGE..."
  az postgres flexible-server parameter set --resource-group "$resource_group" --server-name "$server_name" --name azure.extensions --value AGE >/dev/null
  az postgres flexible-server parameter set --resource-group "$resource_group" --server-name "$server_name" --name shared_preload_libraries --value age >/dev/null

  echo "Restarting PostgreSQL server..."
  az postgres flexible-server restart --resource-group "$resource_group" --name "$server_name" >/dev/null
  wait_postgres_ready "$resource_group" "$server_name"

  local script_dir
  script_dir="$(cd "$(dirname "$0")" && pwd)"
  local repo_root
  repo_root="$(cd "$script_dir/../.." && pwd)"

  local customer_graph_loader="$repo_root/postgresql_age/load_data/customer_graph/load_customer_graph.py"
  local meetings_graph_loader="$repo_root/postgresql_age/load_data/meetings_graph/load_meetings_graph.py"
  local cg_index_script="$repo_root/postgresql_age/load_data/customer_graph/build_graph_indexes.py"
  local mg_index_script="$repo_root/postgresql_age/load_data/meetings_graph/build_graph_indexes.py"
  local data_dir="$repo_root/postgresql_age/data"
  local python_exe="python"
  if [ -x "$repo_root/.venv/bin/python" ]; then
    python_exe="$repo_root/.venv/bin/python"
  elif [ -x "$repo_root/.venv/Scripts/python.exe" ]; then
    python_exe="$repo_root/.venv/Scripts/python.exe"
  fi

  echo "Enabling AGE extension in postgres database..."

  # Reset the PostgreSQL admin password via Azure CLI to ensure it matches
  # the stored POSTGRESQL_ADMIN_PASSWORD value.  On the first run, azd prompts
  # for the @secure() parameter before the preprovision hook generates the
  # password, so the server may have been created with a different value.
  echo "Resetting PostgreSQL admin password to match stored environment value..."
  az postgres flexible-server update \
    --resource-group "$resource_group" \
    --name "$server_name" \
    --admin-password "$admin_password" \
    --output none 2>&1 || true
  wait_postgres_ready "$resource_group" "$server_name"

  age_init_succeeded=false
  for attempt in $(seq 1 15); do
    if PGHOST="$server_fqdn" \
      PGPORT="5432" \
      PGDATABASE="postgres" \
      PGUSER="$admin_user" \
      PGPASSWORD="$admin_password" \
      PGSSLMODE="require" \
      "$python_exe" - <<'PY'
import os
import psycopg

conn = psycopg.connect(
    host=os.environ['PGHOST'],
    port=int(os.environ.get('PGPORT', '5432')),
    dbname=os.environ.get('PGDATABASE', 'postgres'),
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
    sslmode='require'
)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("CREATE EXTENSION IF NOT EXISTS AGE CASCADE;")
    cur.execute("ALTER DATABASE postgres SET search_path = ag_catalog, \"$user\", public;")
conn.close()
PY
    then
      age_init_succeeded=true
      break
    fi

    echo "AGE extension initialization failed (attempt $attempt/15). Retrying in 12 seconds..."
    sleep 12
  done

  if [ "$age_init_succeeded" != "true" ]; then
    echo "ERROR: AGE extension initialization failed after retries."
    exit 1
  fi

  if [ ! -f "$customer_graph_loader" ]; then
    echo "ERROR: Customer graph loader script not found: $customer_graph_loader"
    exit 1
  fi

  if [ ! -f "$meetings_graph_loader" ]; then
    echo "ERROR: Meetings graph loader script not found: $meetings_graph_loader"
    exit 1
  fi

  if [ ! -d "$data_dir" ]; then
    echo "ERROR: Data directory not found: $data_dir"
    exit 1
  fi

  echo "Loading customer graph data into PostgreSQL AGE..."
  local load_succeeded=false
  for attempt in $(seq 1 3); do
    if PGHOST="$server_fqdn" \
      PGPORT="5432" \
      PGDATABASE="postgres" \
      PGUSER="$admin_user" \
      PGPASSWORD="$admin_password" \
      PGSSLMODE="require" \
      GRAPH_NAME="$graph_name" \
      DATA_DIR="$data_dir" \
      "$python_exe" "$customer_graph_loader"
    then
      load_succeeded=true
      break
    fi

    echo "Customer graph data load failed (attempt $attempt/3). Retrying in 20 seconds..."
    sleep 20
  done

  if [ "$load_succeeded" != "true" ]; then
    echo "ERROR: Customer graph data load failed after retries."
    exit 1
  fi

  echo "Loading meetings graph data into PostgreSQL AGE..."
  local mg_load_succeeded=false
  for attempt in $(seq 1 3); do
    if PGHOST="$server_fqdn" \
      PGPORT="5432" \
      PGDATABASE="postgres" \
      PGUSER="$admin_user" \
      PGPASSWORD="$admin_password" \
      PGSSLMODE="require" \
      DATA_DIR="$data_dir" \
      "$python_exe" "$meetings_graph_loader"
    then
      mg_load_succeeded=true
      break
    fi

    echo "Meetings graph data load failed (attempt $attempt/3). Retrying in 20 seconds..."
    sleep 20
  done

  if [ "$mg_load_succeeded" != "true" ]; then
    echo "ERROR: Meetings graph data load failed after retries."
    exit 1
  fi

  if [ -f "$cg_index_script" ]; then
    echo "Building customer graph indexes..."
    local cg_index_succeeded=false
    for attempt in $(seq 1 3); do
      if PGHOST="$server_fqdn" \
        PGPORT="5432" \
        PGDATABASE="postgres" \
        PGUSER="$admin_user" \
        PGPASSWORD="$admin_password" \
        PGSSLMODE="require" \
        "$python_exe" "$cg_index_script"
      then
        cg_index_succeeded=true
        break
      fi

      echo "Customer graph index build failed (attempt $attempt/3). Retrying in 20 seconds..."
      sleep 20
    done

    if [ "$cg_index_succeeded" != "true" ]; then
      echo "ERROR: Customer graph index build failed after retries."
      exit 1
    fi
  else
    echo "Customer graph index script not found at $cg_index_script, skipping."
  fi

  if [ -f "$mg_index_script" ]; then
    echo "Building meetings graph indexes..."
    local mg_index_succeeded=false
    for attempt in $(seq 1 3); do
      if PGHOST="$server_fqdn" \
        PGPORT="5432" \
        PGDATABASE="postgres" \
        PGUSER="$admin_user" \
        PGPASSWORD="$admin_password" \
        PGSSLMODE="require" \
        "$python_exe" "$mg_index_script"
      then
        mg_index_succeeded=true
        break
      fi

      echo "Meetings graph index build failed (attempt $attempt/3). Retrying in 20 seconds..."
      sleep 20
    done

    if [ "$mg_index_succeeded" != "true" ]; then
      echo "ERROR: Meetings graph index build failed after retries."
      exit 1
    fi
  else
    echo "Meetings graph index script not found at $mg_index_script, skipping."
  fi
}

# Deploy all container apps using az deployment group create directly.
# This bypasses azd entirely, avoiding env file locking and TUI output issues.
deploy_all_container_apps() {
  local resource_group="$1"
  local pg_admin_password="$2"

  echo ""
  echo "=========================================="
  echo "DEPLOY PHASE: Deploying all container apps"
  echo "=========================================="

  local infra_dir
  infra_dir="$(cd "$(dirname "$0")/../infra" && pwd)"
  local template_file="$infra_dir/main.bicep"
  local parameters_file="$infra_dir/main.parameters.json"

  if [ ! -f "$template_file" ]; then
    echo "ERROR: Bicep template not found: $template_file" >&2
    return 1
  fi
  if [ ! -f "$parameters_file" ]; then
    echo "ERROR: Parameters file not found: $parameters_file" >&2
    return 1
  fi

  local client_ip
  client_ip="$(get_azd_env CLIENT_IP_ADDRESS)"
  [ -z "$client_ip" ] && client_ip="0.0.0.0"

  echo "  Resource Group:   $resource_group"
  echo "  Template:         $template_file"
  echo "  Deploy flags:     MCP=true, FastAPI=true, Webapp=true"
  echo ""

  # Create a resolved parameters file replacing azd ${...} tokens
  local resolved_params="/tmp/azd-deploy-params-resolved.json"
  python3 -c "
import json, sys
with open('$parameters_file') as f:
    params = json.load(f)
params['parameters']['postgresqlAdminPassword']['value'] = sys.argv[1]
params['parameters']['clientIpAddress']['value'] = sys.argv[2]
params['parameters']['deployContainerApp']['value'] = False
params['parameters']['deployContainerAppsEnv']['value'] = True
params['parameters']['deployMcpServerContainerApp']['value'] = True
params['parameters']['deployFastApiContainerApp']['value'] = True
params['parameters']['deployWebappContainerApp']['value'] = True
json.dump(params, open('$resolved_params', 'w'), indent=2)
" "$pg_admin_password" "$client_ip"

  echo "  Resolved parameters written to: $resolved_params"
  echo "  Starting ARM deployment (this may take several minutes)..."
  echo ""

  az deployment group create \
    --resource-group "$resource_group" \
    --template-file "$template_file" \
    --parameters "@$resolved_params" \
    --name "postprovision-containers" \
    --no-prompt

  local deploy_exit=$?
  rm -f "$resolved_params"

  if [ $deploy_exit -ne 0 ]; then
    echo ""
    echo "ERROR: Container app deployment failed (exit code $deploy_exit)." >&2
    return $deploy_exit
  fi

  echo ""
  echo "  Container app deployment completed successfully."
}

# ============================================================
# MAIN EXECUTION
# ============================================================

acr_name="$(get_azd_env acrName)"
acr_login_server="$(get_azd_env acrLoginServer)"
mcp_image_name="$(get_azd_env mcpServerImageName)"
mcp_image_tag="$(get_azd_env mcpServerImageTag)"
build_mcp="$(get_azd_env buildMcpServerContainer)"
fastapi_image_name="$(get_azd_env fastApiImageName)"
fastapi_image_tag="$(get_azd_env fastApiImageTag)"
build_fastapi="$(get_azd_env buildFastApiContainer)"
webapp_image_name="$(get_azd_env webappImageName)"
webapp_image_tag="$(get_azd_env webappImageTag)"
build_webapp="$(get_azd_env buildWebappContainer)"
resource_group="$(get_azd_env AZURE_RESOURCE_GROUP)"
postgres_server_name="$(get_azd_env postgresqlServerName)"
postgres_server_fqdn="$(get_azd_env postgresqlServerFqdn)"
postgres_admin_user="$(get_azd_env postgresqlAdminLogin)"
postgres_admin_password="$(get_azd_env POSTGRESQL_ADMIN_PASSWORD)"
graph_name="$(get_azd_env graphName)"
initialize_pg_age="$(get_azd_env initializePostgresqlAge)"

if [ -z "$acr_name" ]; then
  echo "ACR not deployed, skipping container builds"
  exit 0
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"

# ---- PHASE 0: PostgreSQL AGE initialization (flag-gated) ----
if [ -n "$postgres_server_name" ] && [ "$initialize_pg_age" != "false" ]; then
  wait_postgres_ready "$resource_group" "$postgres_server_name"
  # Open PostgreSQL firewall so the deployer's machine can connect.
  # The private endpoint blocks public access when no firewall rules exist.
  ensure_postgres_allow_all_ips "$resource_group" "$postgres_server_name"
  initialize_postgres_age_and_data "$resource_group" "$postgres_server_name" "$postgres_admin_user" "$postgres_admin_password" "$postgres_server_fqdn" "$graph_name"
  # Remove the broad firewall rule now that initialization is complete.
  echo "Removing temporary firewall rule..."
  az postgres flexible-server firewall-rule delete \
    --resource-group "$resource_group" \
    --name "$postgres_server_name" \
    --rule-name "AllowAllIps" \
    --yes >/dev/null 2>&1 || true
  set_azd_env "initializePostgresqlAge" "false"
  echo "PostgreSQL AGE initialization complete. Set initializePostgresqlAge=false to skip on next run."
else
  if [ "$initialize_pg_age" = "false" ]; then
    echo "Skipping PostgreSQL AGE initialization (initializePostgresqlAge=false)."
  elif [ -z "$postgres_server_name" ]; then
    echo "Skipping PostgreSQL AGE initialization (no server name)."
  fi
fi

# ---- BUILD PHASE: Build all container images ----
echo "=========================================="
echo "Building container images..."
echo "=========================================="

if [ "$build_mcp" != "false" ]; then
  mcp_full_path="$(cd "$script_dir/$MCP_SERVER_PATH" && pwd)"
  IFS=';' read -r mcp_needed mcp_hash <<< "$(build_needed "$mcp_full_path" "mcpServerFolderHash")"
  if [ "$mcp_needed" = "true" ]; then
    az acr build --registry "$acr_name" --image "${mcp_image_name}:${mcp_image_tag}" --image "${mcp_image_name}:latest" --file "$mcp_full_path/Dockerfile" "$mcp_full_path"
    set_azd_env "mcpServerFolderHash" "$mcp_hash"
    echo "MCP Server container built: $acr_login_server/${mcp_image_name}:${mcp_image_tag}"
  else
    echo "MCP Server container is up-to-date, skipping build."
  fi
fi

if [ "$build_fastapi" != "false" ]; then
  fastapi_full_path="$(cd "$script_dir/$FASTAPI_PATH" && pwd)"
  IFS=';' read -r fastapi_needed fastapi_hash <<< "$(build_needed "$fastapi_full_path" "fastApiFolderHash")"
  if [ "$fastapi_needed" = "true" ]; then
    az acr build --registry "$acr_name" --image "${fastapi_image_name}:${fastapi_image_tag}" --image "${fastapi_image_name}:latest" --file "$fastapi_full_path/Dockerfile" "$fastapi_full_path"
    set_azd_env "fastApiFolderHash" "$fastapi_hash"
    echo "FastAPI container built: $acr_login_server/${fastapi_image_name}:${fastapi_image_tag}"
  else
    echo "FastAPI container is up-to-date, skipping build."
  fi
fi

if [ "$build_webapp" != "false" ]; then
  webapp_full_path="$(cd "$script_dir/$WEBAPP_PATH" && pwd)"
  IFS=';' read -r webapp_needed webapp_hash <<< "$(build_needed "$webapp_full_path" "webappFolderHash")"
  if [ "$webapp_needed" = "true" ]; then
    fastapi_fqdn="$(get_azd_env fastApiContainerAppFqdn)"
    if [ -n "$fastapi_fqdn" ]; then
      az acr build --registry "$acr_name" --image "${webapp_image_name}:${webapp_image_tag}" --image "${webapp_image_name}:latest" --build-arg "VITE_API_BASE_URL=https://${fastapi_fqdn}" --file "$webapp_full_path/Dockerfile" "$webapp_full_path"
    else
      az acr build --registry "$acr_name" --image "${webapp_image_name}:${webapp_image_tag}" --image "${webapp_image_name}:latest" --file "$webapp_full_path/Dockerfile" "$webapp_full_path"
    fi
    set_azd_env "webappFolderHash" "$webapp_hash"
    echo "Webapp container built: $acr_login_server/${webapp_image_name}:${webapp_image_tag}"
  else
    echo "Webapp container is up-to-date, skipping build."
  fi
fi

# ---- DEPLOY PHASE: Single ARM deployment to deploy all container apps ----
deploy_all_container_apps "$resource_group" "$postgres_admin_password"

echo "=========================================="
echo "Post-provision completed successfully."
echo "=========================================="