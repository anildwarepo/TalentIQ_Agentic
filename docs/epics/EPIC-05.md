# EPIC-05: Resume / CV Generation

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 4  
> **Business Requirement:** BR-03  
> **Total Story Points:** 13

## Summary

Generate, view and package candidate CVs in DXC standardized format. Includes individual CV generation, mass generation for shortlists, anonymization for tender requirements, and standardized/anonymized CV viewing from search results. CV templates are configurable per offering or client.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-016](../user-stories/US-016.md) | View CV in standardized anonymized format from search | 3 | Sprint 4 | New |
| [US-017](../user-stories/US-017.md) | Generate standardized CV in DXC format with configurable templates | 5 | Sprint 4 | New |
| [US-018](../user-stories/US-018.md) | Mass generate standardized CVs for multiple candidates | 3 | Sprint 4 | New |
| [US-019](../user-stories/US-019.md) | Generate anonymized CV for tender requirements | 2 | Sprint 4 | New |

## Dependencies

- **Upstream:** EPIC-01 (Workday CV artifacts), EPIC-04 (search results feed CV generation)
- **Downstream:** EPIC-06 (certification packages include CVs), EPIC-09 (bid-specific CV generation)

## Acceptance Criteria (Epic Level)

- CVs viewable in standardized, anonymized format from search results
- CV generation using DXC-approved templates, configurable per offering/client
- Mass generation for multiple candidates
- Anonymization per agreed rules when required by tender
- Template management with audit trail
