# EPIC-09: Receiving Bids and Extracting Roles

> **Priority:** P2 (Should) — Future  
> **Sprint:** Sprint 7  
> **Business Requirement:** BR-08  
> **Total Story Points:** 16

## Summary

Upload tender documents and automatically extract required roles/profiles to accelerate candidate searches. Includes pre-populating search positions from extracted roles and bid-specific CV generation (standardized, mass, anonymized).

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-032](../user-stories/US-032.md) | Upload tender document and extract required roles | 5 | Sprint 7 | New |
| [US-033](../user-stories/US-033.md) | Pre-populate candidate search positions from extracted roles | 3 | Sprint 7 | New |
| [US-034](../user-stories/US-034.md) | Generate standardized CV in DXC format (Bids) | 3 | Sprint 7 | New |
| [US-035](../user-stories/US-035.md) | Mass generate standardized CVs (Bids) | 3 | Sprint 7 | New |
| [US-036](../user-stories/US-036.md) | Generate anonymized CV for bid requirements | 2 | Sprint 7 | New |

## Dependencies

- **Upstream:** EPIC-04 (search engine), EPIC-05 (CV generation engine)
- **Downstream:** None

## Notes

- US-034/US-035/US-036 overlap with EPIC-05 stories (US-017/US-018/US-019) — these are bid-specific variants that reuse the same CV generation engine but are scoped to the bid intake workflow.

## Acceptance Criteria (Epic Level)

- Tender documents uploadable (paste or file)
- System extracts structured list of roles and constraints
- Extracted roles pre-populate candidate search positions
- CV generation (standard, mass, anonymized) available within bid workflow
