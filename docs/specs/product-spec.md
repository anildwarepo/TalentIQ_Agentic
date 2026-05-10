# TalentIQ v2 — Product Specification

> **Version:** 1.0  
> **Date:** 2026-05-08  
> **Author:** Ash (Scrum Master / Requirements Analyst)  
> **Source:** `talentiq_requirements/user_stories_v9.csv`, `talentiq_requirements/features.csv`

---

## 1. Product Vision

TalentIQ v2 is an **agent-first** internal talent matching and management platform for DXC Technology. It enables managers, account leads, pre-sales teams, and staffing managers to search for internal candidates, generate standardized CVs, manage certifications, and respond to tender/RFI requirements — all backed by AI-powered scoring, Workday integration, and agentic orchestration.

## 2. Target Users

| Role | Primary Needs |
|------|---------------|
| **Manager / Account Lead** | Search candidates, view dashboards, trigger reminder campaigns, manage teams |
| **Pre-Sales Lead** | Detect RFI/NSSR opportunities, run talent previews, hand off to staffing |
| **Tender Contributor** | Generate CVs, package response bundles, upload tender documents |
| **Staffing Manager** | Receive pre-sales handoffs, manage resource requests |
| **System Administrator** | Configure weights, maintain EQF/MECES tables, manage templates, RBAC |
| **Employee** | Optionally import skills, browse Career Navigator opportunities |
| **Privacy / Compliance Officer** | Audit trails, DPIA controls, role-based access |

## 3. Platform Architecture Needs

- **Frontend:** React + Vite
- **Backend:** Python with agentic orchestration framework
- **Data Layer:** Graph database (Cypher, vector search, full-text search)
- **Integrations:** Workday API, My Growth (FDS) API, CPQ system
- **AI:** Multi-dimensional scoring engine with configurable weights, semantic matching, skill adjacency
- **Export:** Excel, CSV, PDF, PPTX with DXC branding
- **Localization:** ES, EN, FR, PT
- **Chat interface:** Agent-first conversational UI

## 4. Epic Summary

| Epic | Title | Priority | Sprint | Stories |
|------|-------|----------|--------|---------|
| EPIC-01 | Workday Data Integration | 1 | Sprint 1-2 | US-001 – US-004 |
| EPIC-02 | Integration with FDS / My Growth | 1 | Sprint 1 | US-005 |
| EPIC-03 | EQF / MECES Study Mapping | 1 | Sprint 2-3 | US-006 – US-008 |
| EPIC-04 | Candidate Search & CV Search | 1 | Sprint 3-4 | US-009 – US-015 |
| EPIC-05 | Resume / CV Generation | 1 | Sprint 4 | US-016 – US-019 |
| EPIC-06 | Certifications and Test Handling | 1 | Sprint 4 | US-020 – US-022 |
| EPIC-07 | Manager Dashboards (People Analytics) | 1 | Sprint 5 | US-023 – US-028 |
| EPIC-08 | Automation and Notifications | 1 | Sprint 5 | US-029 – US-031 |
| EPIC-09 | Receiving Bids and Extracting Roles | 2 | Sprint 7 | US-032 – US-036 |
| EPIC-10 | Privacy, Access Control and Compliance | 1 | Sprint 1 | US-037 – US-038 |
| EPIC-11 | Soft Hold (Optional) | 3 | Backlog | US-039 – US-040 |
| EPIC-12 | Skills Enrichment (Optional) | 3 | Backlog | US-041 – US-042 |
| EPIC-13 | Quality / Level of Satisfaction | 1 | Sprint 5 | US-043 |
| EPIC-14 | FAQs and Grants | 1 | Sprint 6 | US-044 |
| EPIC-15 | Query History | 1 | Sprint 4 | US-045 |
| EPIC-16 | Usability Language | 1 | Sprint 2 | US-046 |
| EPIC-17 | CPQ Pre-Sales Talent Preview | 1 | Backlog | US-047 – US-052 |

**Total:** 17 epics, 52 user stories, ~164 story points

## 5. Feature Categories (from features.csv)

The platform includes 48 AI-matching and operational features across 12 categories:

| Category | Feature Count | Key Capabilities |
|----------|--------------|-------------------|
| **Scoring** | 11 | Skills match (direct + semantic), availability, location, cost, job level, engagement history, client familiarity, bench duration, bench-first priority, bench aging, skill adjacency, semantic affinity |
| **Matching Constraints** | 4 | GDN vs onshore, language hard filters, ARPG-first scope, cross-region search |
| **Match Readiness** | 4 | High (auto-recommend), Medium (validation), Low (manual review), Developable (training pathway) |
| **Governance** | 3 | Mandatory internal search, AI model versioning, matching audit trail |
| **Shortlist** | 8 | Persistent object per RR, ranked list, shareable, manual add/remove, self-nominations, comparison view, RM notes, status tracking |
| **Career Navigator** | 3 | Employee opportunity browser, self-nomination, skill gap visibility |
| **Explainability** | 3 | Score breakdown by dimension, direct vs semantic distinction, confidence indicator |
| **Feedback Loop** | 3 | Acceptance reasons, rejection reasons, model weighting feedback |
| **Configuration** | 2 | Admin-tunable weights, offering-specific profiles |
| **Performance** | 1 | Match result caching |
| **Analytics** | 1 | Accuracy, acceptance rate, time-to-fill metrics |
| **Adoption** | 3 | Phased rollout — Assist, Recommend, Auto-assign modes |

## 6. Coverage Gap Analysis

Of 48 features in `features.csv`, **18 are covered** by existing user stories and **30 are gaps** requiring new stories or scope decisions. See `docs/traceability.md` for the full mapping.

**Critical gaps requiring backlog grooming:**
- AI scoring dimensions: availability (M05-03), cost optimization (M05-05), engagement history (M05-07), client familiarity (M05-08), bench duration (M05-09)
- Match Readiness tiers (M05-12 through M05-14)
- Shortlist management features (M05-23 through M05-26)
- Career Navigator (M05-27, M05-28)
- Phased AI adoption modes (M05-45 through M05-47)
- Governance: mandatory internal search (M05-16), AI model versioning (M05-44)

## 7. Non-Functional Requirements

- **Performance:** Export generation < 60 seconds for up to 10 candidates
- **Security:** Role-based access control, DPIA-compliant data flows, audit trails
- **Localization:** Full interface in ES, EN, FR, PT
- **Data sources:** Production-quality Workday data (not UAT/simulated)
- **Branding:** DXC format for CV/PDF/PPTX exports, configurable per offering/client
- **Audit:** All reminder campaigns, certification downloads, match decisions, and talent previews logged

## 8. Key Integrations

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Workday   │────▶│  TalentIQ   │◀────│  My Growth  │
│  (HR Data)  │     │  Platform   │     │  (FDS/API)  │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │   CPQ    │ │  Export   │ │  Graph   │
        │ (Deals)  │ │ (Office) │ │   DB     │
        └──────────┘ └──────────┘ └──────────┘
```

## 9. Sprint Roadmap

| Sprint | Focus | Story Points |
|--------|-------|-------------|
| Sprint 1 | Data foundations: Workday, My Growth, Privacy/RBAC | 17 |
| Sprint 2 | Data enrichment: EQF/MECES, Multilanguage, Data Source | 10 |
| Sprint 3 | Core search: Multi-criteria, Filters, Positions, Export | 26 |
| Sprint 4 | CV generation, Certifications, Query History, Gaps | 32 |
| Sprint 5 | Dashboards, Notifications, Feedback | 28 |
| Sprint 6 | Help & FAQs | 2 |
| Sprint 7 | Bid intake & role extraction | 16 |
| Backlog | Soft Hold, Skills Enrichment, CPQ Integration | 33 |
| **Total** | | **164** |

## 10. Document Index

- Epics: `docs/epics/EPIC-{NN}.md`
- User Stories: `docs/user-stories/US-{NNN}.md`
- Backlog: `docs/backlog.md`
- Traceability: `docs/traceability.md`
- This spec: `docs/specs/product-spec.md`
