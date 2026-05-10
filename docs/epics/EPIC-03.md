# EPIC-03: EQF / MECES Study Mapping and Maintenance

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 2–3  
> **Business Requirement:** BR-EQF  
> **Total Story Points:** 11

## Summary

Manage the mapping between employee academic qualifications and the European Qualifications Framework (EQF) levels and the Spanish equivalent MECES framework. The mapping table is pre-loaded automatically from official sources and can be maintained by an administrator. Employee study data from Workday is automatically identified and mapped to the corresponding EQF/MECES level, enriching the employee profile.

**References:**
- EQF: https://europass.europa.eu/en/european-qualifications-framework-eqf
- MECES (Spain): https://www.ciencia.gob.es/Universidades/MECES.html

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-006](../user-stories/US-006.md) | Pre-load EQF/MECES mapping table from official sources | 3 | Sprint 2 | New |
| [US-007](../user-stories/US-007.md) | Administrator maintenance of EQF/MECES mapping table | 3 | Sprint 2 | New |
| [US-008](../user-stories/US-008.md) | Automatic identification and mapping of employee studies to EQF/MECES | 5 | Sprint 3 | New |

## Dependencies

- **Upstream:** EPIC-01 (Workday education data required for automatic mapping)
- **Downstream:** EPIC-04 (EQF/MECES level usable as search/filter criterion)

## Acceptance Criteria (Epic Level)

- EQF 1–8 and MECES 1–4 levels pre-loaded from official frameworks
- Administrators can add, edit, and deactivate mapping entries with audit trail
- Employee qualifications auto-mapped to EQF/MECES; unmatched flagged for manual resolution
- EQF/MECES level available as search and filter criterion
