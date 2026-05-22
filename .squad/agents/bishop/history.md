# Bishop — History

> Older entries archived to `history-archive.md` on 2026-05-21 by Scribe (originally truncated 2026-05-16; 2026-05-22 pass moved 2026-05-21 deep-dive Learnings).

## Project Context
- **Project:** TalentIQ — Talent Matching/Searching platform
- **Owner:** Anil
- **Stack:** React Vite (frontend), Python (backend, Agent Framework, MCP servers), PostgreSQL + Apache AGE + DiskANN + FTS, Cosmos DB, Azure AI Foundry (`gpt-5.4`)
- **My role:** Deployment Engineer — own Azure infra (Bicep), `azd` config, VNet, private endpoints, Entra ID + MI auth, and end-to-end `azd up` deployment

## Target Topology
- VNet 10.0.0.0/16 with subnets: snet-aca (/23), snet-pe (/24), snet-db (/24)
- Container Apps Environment (Consumption, VNet-integrated, `internal: false`)
  - **backend** (port 8000) — internal ingress only
  - **frontend** (port 80) — external ingress
  - **mcp-server** (port 3002) — internal ingress only
- Cosmos DB — PE + RBAC-only (disableLocalAuth: true)
- PostgreSQL Flex Server — PG 16, delegated subnet, Entra ID-only auth, extensions: age, vector, pg_trgm, pg_stat_statements
- Azure AI Foundry — AIServices, gpt-5.4, PE dual DNS, RBAC-only
- App Insights + Log Analytics, Key Vault (RBAC, PE), ACR (Premium, PE)
- 3 UAMIs (backend, frontend, mcp) with RBAC: Cosmos Data Contributor, Foundry OpenAI User, KV Secrets User, ACR Pull, PG Entra Admin
- Private DNS zones: cosmos, postgres, cognitive, openai, keyvault, ACR
- Naming: `{abbreviation}-talentiq-{env}-{resourceToken}`

## Key References
- `talentiq_requirements/azd_deploy/`, `talentiq_requirements/foundy-managed-vnet-setup/`
- `docs/specs/vnet-integration.md`, `authentication.md`, `backend-architecture.md`, `database-architecture.md`
- Skills: `azure-postgres`, `microsoft-foundry`

## Work Log

### 2026-05-12: Passes 1–3 — initial infra (Archived)
Built complete infra in 3 passes: networking foundation → data/supporting services → Container App workloads + UAMI + RBAC. Also created deployment runbook and fixed MCP Dockerfile override in azure.yaml. **See history-archive.md.**

### 2026-05-16: Passes 4–5 — rebuild then reference-pattern alignment (Archived)
Pass 4 rebuilt entire `talent_infra/` (17 files lost to disk) from this history as blueprint; Bicep validation zero diagnostics. Pass 5 then deleted everything and rebuilt to match `talentiq_requirements/reference_code/azd_deploy/` — two-phase deploy (azd provision + postprovision hook), Bicep moved under `talent_infra/infra/`, password-PG for dev parity, Cosmos added, AGE+VECTOR+PG_TRGM extensions, 13 modules + 4 hook scripts. **Full design decisions + learnings in history-archive.md.**

### 2026-05-21: `talent_infra_modules/` — per-component deploy chain (Archived)
Authored `01-postgresql/`, `02-backend/`, `04-data-loading/`: self-contained `deploy.ps1` + Bicep + module copies per folder; `.outputs.json` hand-off chain; control-plane PG admin registration; same-RG fail-fast on cross-RG ACR/Foundry/Cosmos mismatches. Bicep zero-diagnostics; PowerShell zero parse errors; Lambert APPROVED. **See history-archive.md (2026-05-21 entry) for full per-folder breakdown + ~25 learnings.**

## Learnings

> Older Learnings (2026-05-21 PowerShell case-insensitive shadowing in `Get-ParameterValue`, 00-container-apps-env silent-success postmortem, Postgres SKU/tier parity; 2026-05-22T00:00:00Z asymmetric-RBAC prereq checks; 2026-05-22T12:15:00Z Private DNS zone discover-and-reuse; 2026-05-22T00:30:00Z ARM/Bicep param-file no-comment rule) moved to `history-archive.md` by Scribe. All patterns also codified in `.squad/decisions.md` (search by ISO date) and reusable skills under `.squad/skills/`.

## Cross-agent note — 2026-05-21 (Scribe)
- **Auth-disable contract is a two-agent deliverable.** Bishop owns the Container App env-vars + deploy scripts (omit `AZURE_TENANT_ID` on backend; pass `VITE_DISABLE_AUTH=true` to the frontend Docker build); Dallas owns the React source change (conditional `<MsalProvider>`, suppressed bearer header, synthetic demo account in `talent_ui/`). Both halves must move together to deliver the "auth-off demo deploy" promised by `talent_infra_modules/AUTH-DISABLED.md`. Changing the contract requires coordinated edits across both surfaces — never one in isolation.
- **Lambert APPROVED the talent_infra_modules/ output (2026-05-21).** All 6 hazards from `/memories/repo/talentiq-azd-deploy.md` covered; all `.bicep` files compile; all `.ps1` files parse zero errors; `.outputs.json` schema consistent across folder boundaries. Three WARN-level cosmetic findings logged but non-blocking. No Reviewer Rejection Protocol invoked.
- **00-container-apps-env shipped (2026-05-21, later).** The toolkit is now 5 components (`00 + 01-04`) and self-contained end-to-end on greenfield environments. Decision recorded under coordinator-recovered attribution; see Work Log entry above for the silent-success postmortem.

### 2026-05-22T18:00:00Z — Stale PE `privateDnsZoneGroup` self-heal in `01-postgresql/deploy.ps1` (Archived)

Azure forbids in-place mutation of `privateDnsZoneConfigs[*].properties.privateDnsZoneId` (`UpdatingPrivateDnsZoneIdOnPrivateDnsZoneConfigNotAllowed`) — script-only fix (Bicep cannot recover). Added `[switch]$FixStaleDnsZoneGroup` (umbrella `-Force` implies) + Section 6c read-only detection + Section 7b gated delete + Section 7c best-effort orphan-zone cleanup (same-RG + `rsCount -le 1 -and linkCount -eq 0` guards). Bicep surface untouched. Pattern is normative for every PE-bearing module — see `decisions.md` `2026-05-22T18:00:00Z` and `.squad/skills/azure-pe-dns-zone-group-self-heal/SKILL.md`. **See `history-archive.md` for full root-cause + section-by-section walkthrough + live recovery transcript.**

### 2026-05-22T22:15:00Z — `01-postgresql/deploy.ps1` Bug 2: Section 8 `az deployment group create` JSON-capture stream pollution (Archived)

`Invoke-Native { az ... --output json 2>&1 }` merged the Bicep upgrade notice (and other stderr lines) into the JSON body, breaking `ConvertFrom-Json` even though the deployment succeeded. Fix: separate streams (`2>$stderrLog` to `.deploy-logs/{stamp}-bicep-stderr.txt`), force `-o json`, validate non-empty before parsing, dump unparseable stdout to disk (never echo — may contain secrets/IDs), surface stderr inline only on non-zero exit, scrub `$plainPw` immediately. Same antipattern lives in every `talent_infra_modules/*/deploy.ps1` — Lambert sweep candidate. **See `history-archive.md` for full root-cause + Section 8 walkthrough.**

### 2026-05-22T23:00:00Z — `talent_infra_v2/scripts/test_pg_entra_connection.py` path-aware + PRIVATE-BY-DEFAULT (Archived)

Script silently connected over the public PaaS firewall when run from a non-VNet host (PE never actually exercised). Installed **resolve → classify → gate → connect** pattern: `socket.getaddrinfo` → `ipaddress.ip_address(ip).is_private` (covers RFC1918 + CGNAT 100.64/10) → colored indicator line → gate BEFORE Entra token. New flags `--allow-public` (opt-in for public path, yellow warning) and `--show-path-only` (network-only diagnostic, skips token+psycopg2). Diagnostic hint surfaces the firewall-rule check when public-path connections fail. stdlib-only, exit-code contract unchanged. Pattern lifts to every PE-fronted PaaS probe (Cosmos, Cognitive, OpenAI, ACR, KeyVault) — captured as skill `azure-pe-test-script-private-default`. **See `history-archive.md` for full pattern walkthrough + live verification transcript.**


## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.

## Cross-agent note — 2026-05-22T23:55:00Z (Scribe, from Brett)
- `talent_data_pipeline.main` gained `--mode {env,manual}` CLI flag + `DATALOAD_MODE` env var (precedence: CLI > env var > default `env`). Default `env` preserves today's behavior — no prompts, reads `PGHOST` from `.env`. `manual` interactively prompts `PG host [<current PGHOST>]:` (host only — port/user/database/sslmode stay from `.env`); fails fast with exit 2 when no TTY, so CI never hangs. Entra `DefaultAzureCredential` path is fully preserved (no password fallback). Inner package only; outer stubs deliberately untouched per 2026-05-22 cleanup. Relevant to `talent_infra_modules/04-data-loading/deploy.ps1` if operators ever want to override the deployed PG host ad-hoc without re-publishing `.env`. Per `decisions.md 2026-05-22T23:55:00Z`.