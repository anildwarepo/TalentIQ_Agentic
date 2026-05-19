#!/bin/bash
#
# Pre-provision hook to get the client IP address for PostgreSQL firewall rule.
#

echo "=========================================="
echo "Pre-provision hook: Getting client IP..."
echo "=========================================="

# Get client public IP
clientIp=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null || echo "")

if [ -n "$clientIp" ]; then
    echo "Client IP: $clientIp"
    
    # Set it as an azd environment variable
    azd env set CLIENT_IP_ADDRESS "$clientIp"
    echo "CLIENT_IP_ADDRESS set to: $clientIp"
else
    echo "WARNING: Could not get client IP address. PostgreSQL firewall rule will not be created."
    # Set empty value
    azd env set CLIENT_IP_ADDRESS ""
fi

# Ensure POSTGRESQL_ADMIN_PASSWORD is set as a regular env value so the
# postprovision hook can read it via 'azd env get-value'.
existing_password="$(azd env get-value POSTGRESQL_ADMIN_PASSWORD 2>/dev/null || echo "")"
if [ -z "$existing_password" ]; then
    # Try to read PGPASSWORD from the local postgresql_age/.env file first.
    script_dir="$(cd "$(dirname "$0")" && pwd)"
    local_env_file="$script_dir/../../postgresql_age/.env"
    env_password=""
    if [ -f "$local_env_file" ]; then
        env_password="$(grep -m1 '^PGPASSWORD=' "$local_env_file" | cut -d= -f2- | tr -d '\r')"
    fi

    if [ -n "$env_password" ]; then
        echo "Using PGPASSWORD from postgresql_age/.env"
        password="$env_password"
    else
        echo "Generating PostgreSQL admin password..."
        # Use shell-safe characters only (no ! @ # $ % ^ & * etc.)
        password="$(cat /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9._~-' | head -c 16)"
    fi
    azd env set POSTGRESQL_ADMIN_PASSWORD "$password"
    echo "POSTGRESQL_ADMIN_PASSWORD has been set."
else
    echo "POSTGRESQL_ADMIN_PASSWORD is already set."
fi

# Reset container app deployment flags to false so the initial azd provision
# (run by 'azd up') only creates infrastructure.  The postprovision hook will
# deploy container apps directly via az deployment group create.
echo "Resetting container app deployment flags for clean provision..."
azd env set deployMcpServerContainerApp false
azd env set deployFastApiContainerApp false
azd env set deployWebappContainerApp false

echo "=========================================="
