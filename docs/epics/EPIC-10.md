# EPIC-10: Privacy, Access Control and Compliance

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 1  
> **Business Requirement:** BR-09  
> **Total Story Points:** 6

## Summary

Role-based access control and DPIA-compliant data flows for all sensitive employee data. Ensures CV content, certification evidence, and personal data are only visible to authorized users, with all access auditable.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-037](../user-stories/US-037.md) | Role-based access control for CV and certification data | 3 | Sprint 1 | New |
| [US-038](../user-stories/US-038.md) | DPIA/privacy compliance controls | 3 | Sprint 1 | New |

## Dependencies

- **Upstream:** None — foundational, must be in place before data is accessible
- **Downstream:** All other epics depend on RBAC and privacy controls

## Gap Features

- M05-16: Mandatory internal search before external (audit trail proof)
- M05-44: AI model versioning (track which model version produced each match)

## Acceptance Criteria (Epic Level)

- Unauthorized access to CVs or certification tests denied and logged
- Data flows match approved DPIA controls
- All access is auditable
