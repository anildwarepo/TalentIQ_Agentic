# Bishop — History

> Older entries archived to `history-archive.md` on 2026-05-21 by Scribe (originally truncated 2026-05-16; second pass moved 2026-05-21 deep-dive entries).

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

### 2026-05-21: `talent_infra_modules/` — per-component deploy chain (this session)
Owned three of the four component folders:

- **01-postgresql/** — standalone PG Flex Server deployer. `deploy.ps1` + `infra/main.bicep` + parameters + verbatim copies of v2's `postgresql-flexible-server.bicep` and `private-endpoint.bicep` under `infra/modules/`. Folder is self-contained — no `../../talent_infra_v2/...` paths. Bicep compiles zero-diagnostics. Admin registration moved out of Bicep into deploy.ps1 control-plane calls (avoids `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible` re-PUT race). Deterministic server name `tiqpg<sha5>` from `subId|rg|location`. Emits `.outputs.json` consumed by 02-backend and 04-data-loading.
- **02-backend/** — Container App + MCP sidecar sharing one UAMI. `deploy.ps1` + `infra/main.bicep` + parameters + `infra/modules/container-app.bicep` + `.acrignore`. Bicep validation passed (1 cosmetic `use-safe-access` warning preserved for parity with v2). Reads `01-postgresql/.outputs.json`; same-RG fail-fast on AcrResourceGroup/FoundryResourceGroup/CosmosResourceGroup mismatches. `az acr build` for both Dockerfile + Dockerfile.mcp. Post-deploy control-plane PG admin registration using `--display-name <UAMI-name>` (display-name == UAMI name == PGUSER). Emits `.outputs.json` consumed by 03-frontend and 04-data-loading.
- **04-data-loading/** — terminal step. Pure local Python invocation, no Bicep. `deploy.ps1` (~510 lines) reads 01 and 02 outputs, acquires OSSRDBMS Entra token, snapshots/restores all `PG*`/`GRAPH_NAME`/`AZURE_OPENAI_*`/`FORCE_REGENERATE` env vars in `try/finally`, pipes idempotent extension+graph SQL through psql, runs `python -m talent_data_pipeline.main`. `-NarrowBackendGrants` (opt-in) invokes `talent_infra_v2/scripts/provision_pg_entra_roles.py` AS-IS. `-RestartBackend` (opt-in) restarts the active revision. No `.outputs.json` (terminal). README.md was pre-authored.

**Files produced this session (all under `talent_infra_modules/`):** 3 deploy.ps1 files + 3 `infra/main.bicep` + 3 parameter files + module copies (postgresql, private-endpoint, container-app) + 1 `.acrignore`. Plus the shared `AUTH-DISABLED.md`, `DEPLOYMENT-ORDER.md`, `README.md` from prior turns.

**See history-archive.md for the full per-folder flow narratives and the ~25 learnings (cross-RG BCP139/BCP120, AZURE_TENANT_ID omission contract, PE detection via private IP, deterministic naming SHA recipes, psql here-string dollar-quoting, env-var hygiene, etc.).**

### 2026-05-21 (later): `00-container-apps-env/` — standalone ACA env deployer (follow-on, silent-success)
Anil added a 5th component to the toolkit after Lambert's APPROVED verdict: an optional standalone deployer for the Container Apps Environment itself. This closes the last greenfield gap — operators on a brand-new tenant can now bring up `00 + 01 + 02 + 03 + 04` end-to-end through `talent_infra_modules/` without falling back to `talent_infra_v2/`.

- **Files produced (new):** `talent_infra_modules/00-container-apps-env/{README.md, deploy.ps1, infra/main.bicep, infra/main.parameters.json, infra/modules/container-apps-environment.bicep, infra/modules/aca-subnet.bicep}`.
- **Cross-folder edits:** `talent_infra_modules/README.md` (added `00` to component table + prerequisites), `DEPLOYMENT-ORDER.md` (added Step 0 — foundational, parallel-with-`01`, blocks `02` + `03`), `02-backend/deploy.ps1` and `03-frontend/deploy.ps1` (soft-fallback: when `ContainerAppsEnvName` not provided, read `../00-container-apps-env/.outputs.json` — operators no longer need to copy CAE names between commands).
- **Key choice — subnet handling lives in `deploy.ps1`, not Bicep.** The pre-existing-or-create branch validates delegation to `Microsoft.App/environments`, soft-lock awareness, and CIDR membership before any control-plane call. Bicep only ever receives a resolved `subnetId`, so the Bicep is a clean module take-or-create-CAE-against-a-subnet — single source of truth for subnet shape lives in PowerShell where it can talk to the control plane.
- **No data-plane operations.** This module never touches PG, Cosmos, or Foundry; it just produces a CAE id + subnet id that 02 and 03 will consume.
- **Validation (coordinator-side).** `az bicep build` against `00-container-apps-env/infra/main.bicep` → zero diagnostics. PowerShell AST parser against `00-container-apps-env/deploy.ps1` → zero parse errors.
- **Silent-success caveat — read this if you re-open the 00 work.** My spawn for this module returned no chat text and produced no `decisions/inbox/` drop file, but all 10 affected paths landed on disk correctly. Squad coordinator filesystem-verified everything per the `<!-- KNOWN PLATFORM BUGS -->` workaround in `squad.agent.md`, then handed Scribe a recovery manifest. The `decisions.md` entry for this work is attributed to Bishop with explicit `(recovered by Squad coordinator — Bishop spawn returned silent success; all artifacts verified on filesystem and validated)` status so the audit trail is honest — that decision was authored from the recovery manifest, not by me directly. If you re-spawn me on this module, the artifacts and design choices recorded here are authoritative; the silent-success episode is a platform symptom, not missing work.

## Cross-agent note — 2026-05-21 (Scribe)
- **Auth-disable contract is a two-agent deliverable.** Bishop owns the Container App env-vars + deploy scripts (omit `AZURE_TENANT_ID` on backend; pass `VITE_DISABLE_AUTH=true` to the frontend Docker build); Dallas owns the React source change (conditional `<MsalProvider>`, suppressed bearer header, synthetic demo account in `talent_ui/`). Both halves must move together to deliver the "auth-off demo deploy" promised by `talent_infra_modules/AUTH-DISABLED.md`. Changing the contract requires coordinated edits across both surfaces — never one in isolation.
- **Lambert APPROVED the talent_infra_modules/ output (2026-05-21).** All 6 hazards from `/memories/repo/talentiq-azd-deploy.md` covered; all `.bicep` files compile; all `.ps1` files parse zero errors; `.outputs.json` schema consistent across folder boundaries. Three WARN-level cosmetic findings logged but non-blocking. No Reviewer Rejection Protocol invoked.
- **00-container-apps-env shipped (2026-05-21, later).** The toolkit is now 5 components (`00 + 01-04`) and self-contained end-to-end on greenfield environments. Decision recorded under coordinator-recovered attribution; see Work Log entry above for the silent-success postmortem.
