# VNet Integration Specification

**Author:** Ripley (Lead Architect)
**Date:** 2026-05-10
**Status:** Draft
**Audience:** Engineering team, Cloud Infrastructure, Security reviewers

---

## 1. Current State

### 1.1 Network Topology (Development)

All services run on developer workstations or with public endpoints:

| Service | Current Access | Authentication |
|---------|---------------|----------------|
| PostgreSQL Flexible Server | Public endpoint (firewall rules per-IP) | Username/password via `app_config/.env` |
| Azure OpenAI | Public endpoint | `DefaultAzureCredential` (managed identity or CLI) |
| Cosmos DB | Public endpoint | `DefaultAzureCredential` |
| FastAPI Backend | `localhost:8000` | Entra ID JWT |
| MCP Server | `localhost:3002` | None (same host) |
| React SPA | `localhost:5173` | MSAL (client-side) |

### 1.2 Current Risks

- PostgreSQL accepts connections from allowed public IPs — attack surface
- Azure OpenAI and Cosmos DB accessible from any authenticated client
- No network segmentation between services
- Database credentials in `.env` file (no Key Vault)
- No egress control — backend can reach any external endpoint

---

## 2. Target State — VNet Architecture

### 2.1 Network Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  VNet: talentiq-vnet (10.0.0.0/16)                                         │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────┐            │
│  │ Subnet: snet-app (10.0.1.0/24)                               │            │
│  │ ┌─────────────────────┐  ┌──────────────────────────────┐    │            │
│  │ │ App Service          │  │ App Service (MCP Server)     │    │            │
│  │ │ (Backend API)        │  │ or co-hosted in same plan    │    │            │
│  │ │ VNet Integration     │  │ VNet Integration             │    │            │
│  │ └─────────┬───────────┘  └──────────────┬───────────────┘    │            │
│  │           │                              │                    │            │
│  └───────────┼──────────────────────────────┼────────────────────┘            │
│              │                              │                                │
│  ┌───────────▼──────────────────────────────▼────────────────────┐            │
│  │ Subnet: snet-pe (10.0.2.0/24) — Private Endpoints             │            │
│  │ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐    │            │
│  │ │ PE: PostgreSQL│ │ PE: Cosmos DB│ │ PE: Azure OpenAI     │    │            │
│  │ │ .postgres     │ │ .documents   │ │ .openai              │    │            │
│  │ └──────────────┘ └──────────────┘ └──────────────────────┘    │            │
│  │ ┌──────────────┐ ┌──────────────┐                             │            │
│  │ │ PE: Key Vault│ │ PE: App Ins. │                             │            │
│  │ │ .vault       │ │ .monitor     │                             │            │
│  │ └──────────────┘ └──────────────┘                             │            │
│  └───────────────────────────────────────────────────────────────┘            │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────┐            │
│  │ Subnet: snet-db (10.0.3.0/24) — PostgreSQL Delegated          │            │
│  │ ┌───────────────────────────────────────────────────┐          │            │
│  │ │ PostgreSQL Flexible Server (VNet-integrated)       │          │            │
│  │ │ Private access only — no public endpoint           │          │            │
│  │ └───────────────────────────────────────────────────┘          │            │
│  └───────────────────────────────────────────────────────────────┘            │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────┐            │
│  │ Subnet: snet-egress (10.0.4.0/24) — NAT Gateway              │            │
│  │ ┌──────────────────────────────────────────────┐               │            │
│  │ │ NAT Gateway (static public IP for egress)     │               │            │
│  │ └──────────────────────────────────────────────┘               │            │
│  └───────────────────────────────────────────────────────────────┘            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

External (public Internet):
  ┌────────────────────────────────────────┐
  │ Azure Static Web App (React SPA)        │
  │ CDN-backed, custom domain + TLS         │
  │ API calls → App Service via public FQDN │
  └────────────────────────────────────────┘
```

### 2.2 Subnet Plan

| Subnet | CIDR | Purpose | Delegation |
|--------|------|---------|------------|
| `snet-app` | 10.0.1.0/24 | App Service VNet integration | `Microsoft.Web/serverFarms` |
| `snet-pe` | 10.0.2.0/24 | Private endpoints for PaaS services | None |
| `snet-db` | 10.0.3.0/24 | PostgreSQL Flexible Server | `Microsoft.DBforPostgreSQL/flexibleServers` |
| `snet-egress` | 10.0.4.0/24 | NAT Gateway for controlled egress | None |

---

## 3. Private Endpoints

### 3.1 Required Private Endpoints

| Resource | Subresource | Private DNS Zone | IP (example) |
|----------|-------------|-----------------|--------------|
| PostgreSQL Flexible Server | `postgresqlServer` | `privatelink.postgres.database.azure.com` | 10.0.2.10 |
| Cosmos DB | `Sql` | `privatelink.documents.azure.com` | 10.0.2.11 |
| Azure OpenAI | `account` | `privatelink.openai.azure.com` | 10.0.2.12 |
| Key Vault | `vault` | `privatelink.vaultcore.azure.net` | 10.0.2.13 |
| Application Insights | `azuremonitor` | `privatelink.monitor.azure.com` | 10.0.2.14 |

### 3.2 PostgreSQL Flexible Server — VNet Integration

PostgreSQL Flexible Server supports **delegated subnet** deployment (preferred) or private endpoint. With delegated subnet:

- Server is deployed directly into `snet-db`
- No public endpoint exposed
- DNS: `talentiq-pg.postgres.database.azure.com` resolves to private IP via Private DNS Zone
- No separate private endpoint resource needed

**Recommendation:** Use delegated subnet for PostgreSQL (simpler, lower latency). Reserve private endpoints for PaaS services that don't support delegated subnets.

### 3.3 Configuration Changes

Update `app_config/.env` (or Key Vault references) to use private FQDNs:

```env
# Before (public)
PGHOST=talentiq-pg.postgres.database.azure.com

# After (same FQDN, resolves to private IP via Private DNS Zone)
PGHOST=talentiq-pg.postgres.database.azure.com

# Cosmos DB — same pattern
COSMOS_CHAT_ENDPOINT=https://talentiq-cosmos.documents.azure.com:443/

# Azure OpenAI — same pattern
AZURE_OPENAI_ENDPOINT=https://talentiq-openai.openai.azure.com/
```

FQDNs don't change — DNS resolution changes from public to private IP.

---

## 4. NSG Rules

### 4.1 snet-app (App Service)

| Priority | Direction | Source | Destination | Port | Protocol | Action |
|----------|-----------|--------|-------------|------|----------|--------|
| 100 | Outbound | VirtualNetwork | snet-pe | 5432 | TCP | Allow (PostgreSQL) |
| 110 | Outbound | VirtualNetwork | snet-pe | 443 | TCP | Allow (Cosmos, OpenAI, KV) |
| 120 | Outbound | VirtualNetwork | snet-db | 5432 | TCP | Allow (PG delegated) |
| 200 | Outbound | VirtualNetwork | `AzureMonitor` | 443 | TCP | Allow (telemetry) |
| 210 | Outbound | VirtualNetwork | `AzureActiveDirectory` | 443 | TCP | Allow (Entra ID / JWKS) |
| 300 | Outbound | VirtualNetwork | Internet | 443 | TCP | Allow (via NAT GW) |
| 4096 | Outbound | * | * | * | * | Deny |

### 4.2 snet-pe (Private Endpoints)

| Priority | Direction | Source | Destination | Port | Protocol | Action |
|----------|-----------|--------|-------------|------|----------|--------|
| 100 | Inbound | snet-app | VirtualNetwork | 5432, 443 | TCP | Allow |
| 4096 | Inbound | * | * | * | * | Deny |

### 4.3 snet-db (PostgreSQL Delegated)

| Priority | Direction | Source | Destination | Port | Protocol | Action |
|----------|-----------|--------|-------------|------|----------|--------|
| 100 | Inbound | snet-app | VirtualNetwork | 5432 | TCP | Allow |
| 4096 | Inbound | * | * | * | * | Deny |

---

## 5. DNS Resolution

### 5.1 Private DNS Zones

Each zone is linked to the VNet so that in-VNet DNS queries resolve private endpoints:

| Zone | Linked VNet | Records |
|------|-------------|---------|
| `privatelink.postgres.database.azure.com` | `talentiq-vnet` | `talentiq-pg` → 10.0.2.10 |
| `privatelink.documents.azure.com` | `talentiq-vnet` | `talentiq-cosmos` → 10.0.2.11 |
| `privatelink.openai.azure.com` | `talentiq-vnet` | `talentiq-openai` → 10.0.2.12 |
| `privatelink.vaultcore.azure.net` | `talentiq-vnet` | `talentiq-kv` → 10.0.2.13 |
| `privatelink.monitor.azure.com` | `talentiq-vnet` | `talentiq-appinsights` → 10.0.2.14 |

### 5.2 App Service DNS Configuration

App Service with VNet integration uses Azure-provided DNS (168.63.129.16) by default, which resolves Private DNS Zones automatically. No custom DNS server needed.

---

## 6. App Service VNet Integration

### 6.1 Regional VNet Integration

- App Service Plan: **B2** or higher (VNet integration requires Basic+)
- Subnet: `snet-app` (delegated to `Microsoft.Web/serverFarms`)
- All outbound traffic from the App Service routes through the VNet
- Configuration: App Service → Networking → VNet Integration → `snet-app`

### 6.2 App Settings

```
WEBSITE_VNET_ROUTE_ALL=1              # Route ALL outbound through VNet
WEBSITE_DNS_SERVER=168.63.129.16      # Azure DNS (resolves private zones)
```

### 6.3 Inbound Access

The App Service retains a **public FQDN** for the React SPA to call. Secure with:
- Access Restrictions: allow only Static Web App egress IPs or Front Door
- Or add Azure Front Door with WAF for DDoS + rate limiting

---

## 7. MCP Server Communication

### 7.1 Co-hosted (Recommended)

When Backend API and MCP Server run on the **same App Service**:

```
Backend API (port 8000) → localhost:3002 (MCP Server)
```

- No network hop, no auth needed
- MCP_ENDPOINT stays `http://localhost:3002/mcp`
- Both processes share the same VNet integration — outbound to PostgreSQL uses private endpoint

### 7.2 Separated (Scale-out)

If MCP Server is deployed as a separate App Service or Container App:

- Deploy in the same VNet (`snet-app`)
- Use internal FQDN: `mcp-server.internal.azurewebsites.net` or Container App internal ingress
- Add mTLS or API key authentication between services
- Update `MCP_ENDPOINT` to internal URL

**Recommendation:** Start co-hosted. Only separate when MCP becomes a scaling bottleneck.

---

## 8. Managed Identity Flow

### 8.1 Identity Architecture

```
App Service (System-Assigned Managed Identity)
  │
  ├── Azure OpenAI → Cognitive Services OpenAI User role
  ├── Cosmos DB → Cosmos DB Built-in Data Contributor role
  ├── Key Vault → Key Vault Secrets User role
  ├── PostgreSQL → Entra AD authentication (pg_azure_ad_authenticate)
  └── App Insights → Monitoring Metrics Publisher role
```

### 8.2 DefaultAzureCredential Chain

`DefaultAzureCredential` in the backend resolves (in order):
1. **Environment variables** (if set — avoid in production)
2. **Managed Identity** (preferred in App Service)
3. **Azure CLI** (local dev fallback)

### 8.3 PostgreSQL Entra Authentication

Replace password auth with Entra AD:

```env
# Before
PGUSER=talentiq_admin
PGPASSWORD=<secret>

# After
PGUSER=talentiq-app-mi    # Managed identity name registered in PG
PGPASSWORD=               # Empty — token acquired via DefaultAzureCredential
```

The `PGAgeHelper` connection setup must acquire an access token:

```python
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
# Pass token.token as password in libpq connection string
```

---

## 9. Egress Control

### 9.1 NAT Gateway

- Attach to `snet-app`
- Provides static public IP for outbound connections (needed for Entra JWKS, any external API)
- All egress from App Service → VNet → NAT Gateway → Internet

### 9.2 Alternative: Azure Firewall (Enterprise)

For stricter egress control:
- Route all outbound through Azure Firewall
- Allowlist: `login.microsoftonline.com`, `*.openai.azure.com`, `*.documents.azure.com`
- Deny all other outbound
- Higher cost — use only if compliance requires it

**Recommendation:** Start with NAT Gateway. Add Azure Firewall only if enterprise security policy mandates egress filtering.

---

## 10. Monitoring Network Flows

### 10.1 NSG Flow Logs

- Enable on all NSGs
- Send to Log Analytics workspace
- Retention: 30 days minimum
- Use Traffic Analytics for visualization

### 10.2 Network Watcher

- Enable in the deployment region
- Use Connection Monitor to validate:
  - App Service → PostgreSQL (port 5432, private endpoint)
  - App Service → Cosmos DB (port 443, private endpoint)
  - App Service → Azure OpenAI (port 443, private endpoint)

### 10.3 Diagnostic Settings

Enable diagnostic logs on:
- App Service (HTTP logs, platform logs)
- PostgreSQL Flexible Server (query logs, connection logs)
- Cosmos DB (data plane requests)

All logs → same Log Analytics workspace used for Application Insights.

---

## 11. Migration Plan

### Phase 1: Foundation (Week 1)

| Step | Action | Validation |
|------|--------|-----------|
| 1.1 | Create VNet `talentiq-vnet` (10.0.0.0/16) | `az network vnet show` |
| 1.2 | Create subnets: `snet-app`, `snet-pe`, `snet-db`, `snet-egress` | `az network vnet subnet list` |
| 1.3 | Create NSGs and attach to subnets | Verify rules |
| 1.4 | Create NAT Gateway with static public IP, attach to `snet-app` | Test outbound connectivity |

### Phase 2: Database Migration (Week 2)

| Step | Action | Validation |
|------|--------|-----------|
| 2.1 | Enable VNet integration on PostgreSQL Flexible Server (delegated subnet `snet-db`) | `psql` from VNet-connected resource |
| 2.2 | Disable public access on PostgreSQL | Verify public connection fails |
| 2.3 | Create Private DNS Zone for PostgreSQL, link to VNet | `nslookup` from VNet returns private IP |
| 2.4 | Enable Entra AD authentication on PostgreSQL | Test managed identity login |

### Phase 3: PaaS Private Endpoints (Week 2-3)

| Step | Action | Validation |
|------|--------|-----------|
| 3.1 | Create private endpoint for Cosmos DB in `snet-pe` | Connection test from VNet |
| 3.2 | Create private endpoint for Azure OpenAI in `snet-pe` | Embedding call from VNet |
| 3.3 | Create private endpoint for Key Vault in `snet-pe` | Secret retrieval from VNet |
| 3.4 | Create Private DNS Zones for all, link to VNet | DNS resolution audit |
| 3.5 | Disable public access on Cosmos DB and Azure OpenAI | Verify public access denied |

### Phase 4: App Service Integration (Week 3)

| Step | Action | Validation |
|------|--------|-----------|
| 4.1 | Enable VNet integration on App Service (`snet-app`) | `WEBSITE_VNET_ROUTE_ALL=1` |
| 4.2 | Move secrets to Key Vault, update App Settings to use `@Microsoft.KeyVault(...)` references | App starts with KV refs |
| 4.3 | Configure managed identity RBAC on all resources | End-to-end test |
| 4.4 | Enable NSG flow logs and diagnostics | Verify logs appear in Log Analytics |

### Phase 5: Lockdown (Week 4)

| Step | Action | Validation |
|------|--------|-----------|
| 5.1 | Add App Service access restrictions (Front Door or Static Web App IPs only) | Public direct access blocked |
| 5.2 | Audit: no public endpoints remain on PaaS services | Security scan |
| 5.3 | Run full integration test suite from App Service | All features work |
| 5.4 | Document final topology in runbook | Ops handoff |

---

## 12. Cost Considerations

| Component | Estimated Monthly Cost | Notes |
|-----------|----------------------|-------|
| VNet | Free | No charge for VNet itself |
| Private Endpoints | ~$7.30 each × 5 = ~$37 | Per endpoint per month |
| NAT Gateway | ~$32 + data processing | $0.045/GB processed |
| App Service VNet Integration | Included in B2+ plan | No extra charge |
| NSG Flow Logs | ~$0.50/GB | Log Analytics ingestion |
| **Total incremental** | **~$75-100/month** | Excludes compute |

This is a modest cost increase for significant security improvement.
