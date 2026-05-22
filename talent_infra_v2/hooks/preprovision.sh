#!/bin/bash
#
# Pre-provision hook for TalentIQ: get client IP, generate PG password,
# reset container app deploy flags for two-phase deployment.
#

echo "=========================================="
echo "Pre-provision hook starting..."
echo "=========================================="

# Get client public IP
clientIp=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null || echo "")

if [ -n "$clientIp" ]; then
    echo "Client IP: $clientIp"
    azd env set CLIENT_IP_ADDRESS "$clientIp"
    echo "CLIENT_IP_ADDRESS set to: $clientIp"
else
    echo "WARNING: Could not get client IP address."
    azd env set CLIENT_IP_ADDRESS ""
fi

# Ensure POSTGRESQL_ADMIN_PASSWORD is set
# Robust read: azd writes "ERROR: key '...' not found..." to stdout (not stderr),
# so 2>/dev/null does NOT suppress it. Filter explicitly.
read_azd_env() {
  local raw
  raw=$(azd env get-value "$1" 2>&1)
  printf '%s\n' "$raw" \
    | tr -d '\r' \
    | grep -vE '^(ERROR:|WARNING:|To update|winget upgrade)' \
    | grep -v '^$' \
    | head -n1
}
existing_password="$(read_azd_env POSTGRESQL_ADMIN_PASSWORD)"
if [ -z "$existing_password" ]; then
    # Try to read from app_config/.env
    script_dir="$(cd "$(dirname "$0")" && pwd)"
    local_env_file="$script_dir/../../app_config/.env"
    env_password=""
    if [ -f "$local_env_file" ]; then
        env_password="$(grep -m1 '^PGPASSWORD=' "$local_env_file" | cut -d= -f2- | tr -d '\r')"
    fi

    if [ -n "$env_password" ]; then
        echo "Using PGPASSWORD from app_config/.env"
        password="$env_password"
    else
        echo "Generating PostgreSQL admin password..."
        password="$(cat /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9._~-' | head -c 16)"
    fi
    azd env set POSTGRESQL_ADMIN_PASSWORD "$password"
    echo "POSTGRESQL_ADMIN_PASSWORD has been set."
else
    echo "POSTGRESQL_ADMIN_PASSWORD is already set."
fi

# Reset container app deployment flags for clean provision
echo "Resetting container app deployment flags for clean provision..."
azd env set deployMcpServerContainerApp false
azd env set deployBackendContainerApp false
azd env set deployWebappContainerApp false

# Capture deploying user's Entra identity → registered as the initial PostgreSQL
# Entra ID administrator by the Bicep `administrators` child resource. The
# postprovision hook then connects with this identity (via OSSRDBMS token) to
# provision additional Entra principals (container app UAMIs, app users).
echo "Capturing deploying Entra identity for PostgreSQL admin..."
signed_in_user_json="$(az ad signed-in-user show --query "{id:id, upn:userPrincipalName}" -o json 2>/dev/null || echo "")"
if [ -n "$signed_in_user_json" ]; then
    user_object_id="$(echo "$signed_in_user_json" | sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p')"
    user_upn="$(echo "$signed_in_user_json" | sed -n 's/.*"upn" *: *"\([^"]*\)".*/\1/p')"
    if [ -n "$user_object_id" ]; then
        azd env set POSTGRESQL_ENTRA_ADMIN_OBJECT_ID "$user_object_id"
        azd env set POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_NAME "$user_upn"
        azd env set POSTGRESQL_ENTRA_ADMIN_PRINCIPAL_TYPE "User"
        echo "  PG Entra admin: $user_upn ($user_object_id)"
    fi
else
    echo "  WARNING: az CLI not signed in or returned no user — run 'az login' first."
    echo "  Bicep will skip the initial Entra admin assignment; postprovision will retry."
fi

echo "=========================================="
echo "Pre-provision hook complete."
echo "=========================================="
