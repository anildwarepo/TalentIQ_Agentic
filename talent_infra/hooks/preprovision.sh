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

echo "=========================================="
echo "Pre-provision hook complete."
echo "=========================================="
