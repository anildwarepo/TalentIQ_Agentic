# Bishop — History

> Older entries archived to `history-archive.md` on 2026-05-21 by Scribe (originally truncated 2026-05-16; 2026-05-22 pass moved 2026-05-21 deep-dive Learnings; 2026-05-22T23:59:59Z pass moved full text of the mojibake-cascading parser bug + GitGuardian remediation entries; 2026-05-22T23:59:59.9Z pass moved full text of the `-AlwaysPrompt` switch entry AND removed `(Archived)` stubs for 5 older 2026-05-22 entries — their full text remains in `history-archive.md`).

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

### 2026-05-22 — 11-file `.ps1` UTF-8-with-BOM sweep (Archived)

Executed the deferred sweep from Decision `2026-05-22T23:59:59Z`. **11/11 files swept clean** (BOM `EF BB BF`, 0 non-ASCII bytes, parse OK in pwsh 7+); ~4330 chars substituted this pass (~6927 cumulative across all sweep runs). **Substitution map extended by 5 new entries** (↔ → `<->`, ═ → `=`, █ → `#`, ⚠ → `[WARN]`, ✅/✓ → `[OK]`); full 18-entry working map preserved in archive. **One pwsh-7+-only syntax dependency surfaced and confirmed pre-existing** in `02-backend/deploy.ps1` (`?.` 2x + `??` 1x); HEAD already failed PS 5.1 parse with mojibake red-herrings — encoding fix STRICTLY IMPROVES the file. Tagged `EXPECT_FAIL_PS7_ONLY`. **Prevention guards landed**: `.editorconfig` + `.vscode/settings.json` (Anil owns code commit). **2 BOM-less files flagged for a future cleanup pass**: `.squad/templates/skills/distributed-mesh/sync-mesh.ps1` and `talent_infra_v2/scripts/Purge-SoftDeletedFoundryAccounts.ps1`. **adwarakanat2 unblocker**: `git pull` + retry any `talent_infra_modules/*/deploy.ps1` on his box. **See `history-archive.md` for full sweep helper design, per-file char counts, dual-engine parse setup, repo-wide BOM scan, and `.scratch/` cleanup list.**

### 2026-05-22 - 11-file sweep ROLLBACK + 12-file BYTE-LEVEL re-sweep (sweep methodology hardened) (Archived)

Anil hit `Get-ParameterValue: A positional parameter cannot be found that accepts argument ''.` running `talent_infra_modules/01-postgresql/deploy.ps1`. Root cause: the prior sweep (commit `53a94e9`) used a **regex** `\s+-\w+` over the full file text, which mangled ASCII parameter prefixes (`    -Value`, `    -EnvVar`, `    -Default`) into ` - Value`, ` - EnvVar`, ` - Default` -- breaking 5 `Get-ParameterValue` calls in lines 122-131. Rolled back all 11 swept files, rebuilt the sweep helper at **byte-level (codepoint >= 0x80; ASCII PASSTHROUGH)**, re-sourced `01-postgresql/deploy.ps1` from `HEAD~2 cbb8b23` (the prior HEAD was already broken), re-swept all 12 files clean. **Final: 10,283 codepoint substitutions, 0 ASCII touched, 0 unknown.** Dual-engine parse: 12/12 pwsh 7+ OK; 11/12 PS 5.1 OK (`02-backend` still `EXPECT_FAIL_PS7_ONLY`). Smoke-test grep `^\s+-\s+\w+`: 0 real regressions. Discovered + fixed second-order bug: `git show <ref>:<path>` piped through PowerShell stdout decodes UTF-8 via console code page (CP1252) -- mitigated by `cmd.exe /c "... > tempfile"` byte-level capture + em-dash byte-sequence assertion. Per Anil's plan: DO NOT COMMIT -- 12 swept files left unstaged for Anil to commit. Decision proposal `bishop-ps1-sweep-byte-level-fix.md` merged this Scribe pass as `decisions.md 2026-05-23T01:30:00Z` (supersedes-in-part the implementation contract of `2026-05-23T00:30:00Z`; rule statement unchanged). **See `history-archive.md` for full per-file substitution counts, dual-engine parse setup, console-code-page mitigation walkthrough, visual confirmation excerpt, and Step-7-through-Step-11 evidence.**

### 2026-05-22 — `Get-ParameterValue` silent-default bug for env-specific resource names + `-AlwaysPrompt` switch (Archived)

Anil hit silent-bind: `pwsh .\deploy.ps1` from `talent_infra_modules\01-postgresql\` bound `$PeSubnetName` to the param-block default `"pe-subnet"` without prompting. Root cause: `Get-ParameterValue` short-circuits on non-empty `-Value`, and a script `param()` default makes the variable always non-empty at the call site. Fix: added `[switch]$AlwaysPrompt` to `Get-ParameterValue` in `shared/common.ps1` (skips fast-path, always prompts with `Value > envVar > Default` priority). Applied to **2 call sites**: `01-postgresql/deploy.ps1:~167` (`$PeSubnetName` — the actual bug) and `00-container-apps-env/deploy.ps1:~129` (`$AcaSubnetName` — defensive). 35 platform-invariant call sites left unchanged; ~25 verified out of scope (Subscription, RG, ACR, Foundry, Container Apps env, admin login, PG version, SKU tier, etc.); 4 VNet/VNet-RG calls already promptable. Hooks files: 0 `Get-ParameterValue` calls. Verification: UTF-8+BOM preserved 3/3; pwsh 7+ parse OK 3/3; PS 5.1 parse OK 3/3; smoke-test grep clean (1 known false positive in `common.ps1` docstring). Decision merged as `decisions.md 2026-05-22T23:59:59.9Z`. **3 modified `.ps1` files left unstaged — Anil owns the code commit.** **See `history-archive.md` for full root-cause + call-site inventory + verification table + operator UX walkthrough.**

## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.

## Cross-agent note — 2026-05-22T23:55:00Z (Scribe, from Brett)
- `talent_data_pipeline.main` gained `--mode {env,manual}` CLI flag + `DATALOAD_MODE` env var (precedence: CLI > env var > default `env`). Default `env` preserves today's behavior — no prompts, reads `PGHOST` from `.env`. `manual` interactively prompts `PG host [<current PGHOST>]:` (host only — port/user/database/sslmode stay from `.env`); fails fast with exit 2 when no TTY, so CI never hangs. Entra `DefaultAzureCredential` path is fully preserved (no password fallback). Inner package only; outer stubs deliberately untouched per 2026-05-22 cleanup. Relevant to `talent_infra_modules/04-data-loading/deploy.ps1` if operators ever want to override the deployed PG host ad-hoc without re-publishing `.env`. Per `decisions.md 2026-05-22T23:55:00Z`.

## Cross-agent note — 2026-05-22T23:58:00Z (Scribe, from Brett)
- **Empty-`PGUSER` pitfall + new `pg_entra` hint behavior (from the Phase 1 connectivity test root cause on 2026-05-22).** Empty `PGUSER` in any env source (`.env`, Container App env array, Functions app setting, K8s manifest) makes libpq fall back to the **OS account name**, which is then sent to PG as the role to authenticate — even when the Entra bearer token is for a completely different principal. PG rejects with the misleading `password authentication failed for user "<OS-account>"`. Toolkit implication: every UAMI-bound role provisioned by `talent_infra_modules/01-postgresql/` and `talent_infra_modules/02-backend/` MUST set the consumer's `PGUSER` env var to the **UAMI resource name** (which equals the PG role name after `microsoft-entra-admin create --display-name <UAMI-name>`) — never empty, never the OID, never the client GUID. Decision `2026-05-21 talent_infra_modules/02-backend` already does this (`PGUSER=${backendAppName}-identity`); reaffirmed here for any new compute (data-loader job, future workers, sidecar containers) the toolkit adds. `pg_entra.pg_connect()` and `EntraThreadedConnectionPool._connect()` now wrap libpq `password authentication failed` errors with an actionable hint surfacing the empty-PGUSER vs short-PGUSER vs full-UPN cases — Container App stderr from any pipeline job will now point straight at the misconfigured env var instead of looking like a missing password. Per `decisions.md 2026-05-22T23:59:00Z`.