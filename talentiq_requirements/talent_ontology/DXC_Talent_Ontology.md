# DXC Talent Graph — Ontology Reference

> **Graph:** `talent_graph` | **Database:** PostgreSQL + Apache AGE 1.6.0
> **Scale:** 130,475 nodes | 2,609,663 edges | 14 node labels | 12 edge types
> **Source:** 130,000 DXC employees across 19 countries, 46 office locations

---

## Node Labels (14)

### Employee — 130,000 nodes

The central entity. Represents a DXC Technology employee with full HR profile, skills assessment, bench status, cost data, and education.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `name` | string | `"Antonio García"` | Full name |
| `first_name` | string | `"Antonio"` | First name |
| `last_name` | string | `"García"` | Last name |
| `email` | string | `"antonio.garcia2@dxc.com"` | DXC email address |
| `phone` | string | `"+34-6xxxxxxx"` | Phone number |
| `workday_id` | string | `"WD-159942"` | Workday HR system ID |
| `job_title` | string | `"Architect Backend Engineer"` | Current job title |
| `job_level` | int | `12` | Numeric job level (3–14) |
| `skill_level` | string | `"Architect"` | Seniority tier: Junior, Mid, Senior, Lead, Principal, Architect |
| `hire_date` | string | `"2018-03-15"` | ISO date of hire |
| `years_of_experience` | int | `12` | Total years of professional experience |
| `employment_status` | string | `"Active"` | Status: Active, Bench, Notice Period, Long-term Leave |
| `is_bench` | bool | `false` | Currently on bench (unassigned) |
| `bench_start_date` | string | `"2026-02-01"` | When bench period started (empty if not on bench) |
| `bench_duration_days` | int | `45` | Days on bench (0 if not on bench) |
| `availability_date` | string | `"2026-07-15"` | When the employee becomes available |
| `current_project` | string | `"Cloud Migration Program"` | Active project name (empty if on bench) |
| `fte_current_month` | int | `100` | FTE allocation % this month |
| `fte_next_month` | int | `75` | FTE allocation % next month |
| `fte_next2_month` | int | `50` | FTE allocation % month after next |
| `hourly_cost_usd` | float | `85.50` | Internal hourly cost rate (USD) |
| `bill_rate_usd` | float | `140.00` | Client bill rate (USD) |
| `cv_last_updated` | string | `"2025-11-20"` | Last CV update date |
| `cv_freshness_days` | int | `169` | Days since CV was last updated |
| `cv_source` | string | `"Workday"` | CV source: Workday, Manual Upload, My Growth |
| `impressiveness_score` | float | `88.0` | AI-computed score (0–100) based on certs, experience, seniority |
| `data_source` | string | `"Workday+CV"` | Data origin: Workday, Workday+CV, CV Only |
| `delivery_model` | string | `"onshore"` | Delivery model: onshore, nearshore, offshore |
| `eqf_level` | int | `7` | European Qualifications Framework level (5–8) |
| `meces_level` | int | `3` | Spanish MECES equivalent (1–4) |
| `eqf_mapping_status` | string | `"Mapped"` | EQF mapping status: Mapped, Pending mapping |
| `education_degree` | string | `"Master of Science (MSc)"` | Highest degree |
| `education_field` | string | `"Computer Science"` | Field of study |
| `resume_summary` | string | `"Experienced Senior..."` | Free-text resume summary (for full-text search) |

### Location — 46 nodes

A DXC office location with full address detail.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `city` | string | `"Madrid"` | City name |
| `country` | string | `"Spain"` | Country name |
| `country_code` | string | `"ES"` | ISO 2-letter country code |
| `region` | string | `"Europe"` | Geographic region |
| `subregion` | string | `"Iberia"` | DXC subregion (Iberia, CEE, GDN-IN, etc.) |
| `zip` | string | `"28042"` | Postal code |
| `address` | string | `"Calle Albasanz 16"` | Street address |
| `timezone` | string | `"Europe/Madrid"` | IANA timezone |
| `delivery_model` | string | `"onshore"` | onshore, nearshore, offshore |

### Country — 19 nodes

A country where DXC operates.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Spain"` |
| `code` | string | `"ES"` |
| `region` | string | `"Europe"` |

### Subregion — 15 nodes

A DXC organizational subregion.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Iberia"` |
| `region` | string | `"Europe"` |

### Skill — 96 nodes

A technical skill (individual technology/tool).

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Django"` |

### SkillDomain — 13 nodes

A skill domain grouping related technologies.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Python"` |

**Domains:** Python, Java, C#/.NET, JavaScript/TS, Cloud (Azure), Cloud (AWS), DevOps/SRE, Data Engineering, AI/ML, SAP, Salesforce, Cybersecurity, ServiceNow

### Certification — 39 nodes

A professional certification type.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"PMI Project Management Professional (PMP)"` |

### Language — 18 nodes

A spoken language.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"French"` |

### ServiceLine — 8 nodes

A DXC service line.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"GBS – Analytics & Engineering"` |

**Service Lines:** GBS – Analytics & Engineering, GBS – Applications, GBS – Cloud & ITO, GBS – Modern Workplace, GIS – Cloud Infrastructure, GIS – Security, GIS – Workplace & Mobility, Industry Software & BPS

### Offering — 8 nodes

A DXC offering.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Analytics & AI"` |

**Offerings:** Cloud & ITO, Analytics & AI, Application Services, Modern Workplace, Security, Industry Software, Insurance Software, Banking & Capital Markets

### Manager — 80 nodes

A people manager.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Carmen Pérez"` |
| `email` | string | `"carmen.perez@dxc.com"` |
| `employee_id` | string | `"DXC-M0039"` |

### University — 75 nodes

An educational institution.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Universidad Politécnica de Madrid"` |

### Client — 36 nodes

An external client organization.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Telefónica"` |

### Project — 22 nodes

A project engagement.

| Property | Type | Example |
|----------|------|---------|
| `name` | string | `"Cloud Migration Program"` |

---

## Edge Types (12)

### LOCATED_IN — 130,000 edges

**Employee → Location** | No edge properties

Links an employee to their office location.

### IN_COUNTRY — 46 edges

**Location → Country** | No edge properties

Links a location to its country.

### SPECIALIZES_IN — 130,000 edges

**Employee → SkillDomain** | No edge properties

Links an employee to their primary skill domain.

### HAS_SKILL — 713,981 edges

**Employee → Skill** | Has edge properties

Links an employee to an individual skill with proficiency details.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `level` | string | `"Expert"` | Proficiency: Basic, Intermediate, Advanced, Expert, Guru |
| `years_of_experience` | float | `5.2` | Years of experience with this skill |
| `active` | bool | `true` | Whether skill is currently active |
| `is_primary` | bool | `true` | Whether this is the employee's primary skill |

### HOLDS_CERT — 183,060 edges

**Employee → Certification** | Has edge properties

Links an employee to a certification with validity tracking.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `issue_date` | string | `"2023-06-15"` | Date certification was issued |
| `expiry_date` | string | `"2026-06-15"` | Expiration date (empty for lifetime certs) |
| `status` | string | `"Valid"` | Validity: Valid, Expiring (< 90 days), Expired |
| `credential_id` | string | `"CERT-234567"` | Credential identifier |
| `has_evidence` | bool | `true` | Whether certification evidence document exists |

### SPEAKS — 260,982 edges

**Employee → Language** | Has edge properties

Links an employee to a spoken language with CEFR proficiency level.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `level` | string | `"C1"` | CEFR level: A1, A2, B1, B2, C1, C2 |
| `is_native` | bool | `true` | Whether this is a native language |

### BELONGS_TO_SL — 130,000 edges

**Employee → ServiceLine** | No edge properties

Links an employee to their DXC service line.

### WORKS_IN_OFFERING — 130,000 edges

**Employee → Offering** | No edge properties

Links an employee to their DXC offering.

### REPORTS_TO — 130,000 edges

**Employee → Manager** | No edge properties

Links an employee to their people manager (for My Team dashboard).

### STUDIED_AT — 130,000 edges

**Employee → University** | Has edge properties

Links an employee to their educational institution with qualification details.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `degree` | string | `"Master of Science (MSc)"` | Degree type |
| `field` | string | `"Computer Science"` | Field of study |
| `graduation_year` | int | `2016` | Year of graduation |
| `eqf_level` | int | `7` | EQF level of this qualification (5–8) |
| `meces_level` | int | `3` | MECES equivalent (1–4) |

### WORKED_FOR — 335,797 edges

**Employee → Client** | Has edge properties

Links an employee to a client they have worked for, with engagement details.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `role` | string | `"Lead ML Engineer"` | Role held during engagement |
| `project` | string | `"AI/ML Platform"` | Project name |
| `start_date` | string | `"2023-08-10"` | Engagement start date |
| `end_date` | string | `"2025-01-15"` | Engagement end date (empty if current) |
| `is_current` | bool | `false` | Whether this is the current engagement |

### WORKED_ON — 335,797 edges

**Employee → Project** | Has edge properties

Links an employee to a project they have worked on.

| Property | Type | Example | Description |
|----------|------|---------|-------------|
| `role` | string | `"Lead ML Engineer"` | Role held on project |
| `start_date` | string | `"2023-08-10"` | Start date |
| `end_date` | string | `""` | End date (empty if current) |

---

## Relationship Map

```
                                    ┌──────────┐
                                    │ Country  │
                                    │ (19)     │
                                    └────▲─────┘
                                         │ IN_COUNTRY
                                    ┌────┴─────┐
                         ┌─────────►│ Location │
                         │          │ (46)     │
                    LOCATED_IN      └──────────┘
                         │
    ┌──────────┐    ┌────┴─────────────────────────────────┐    ┌──────────────┐
    │ Skill    │◄───┤                                      ├───►│ Certification│
    │ (96)     │    │          E M P L O Y E E              │    │ (39)         │
    └──────────┘    │          (130,000)                    │    └──────────────┘
     HAS_SKILL      │                                      │     HOLDS_CERT
                    │                                      │
    ┌──────────┐    │                                      │    ┌──────────────┐
    │SkillDom. │◄───┤                                      ├───►│ Language     │
    │ (13)     │    │                                      │    │ (18)         │
    └──────────┘    │                                      │    └──────────────┘
   SPECIALIZES_IN   │                                      │     SPEAKS
                    │                                      │
    ┌──────────┐    │                                      │    ┌──────────────┐
    │ServiceLn │◄───┤                                      ├───►│ Manager      │
    │ (8)      │    │                                      │    │ (80)         │
    └──────────┘    │                                      │    └──────────────┘
   BELONGS_TO_SL    │                                      │     REPORTS_TO
                    │                                      │
    ┌──────────┐    │                                      │    ┌──────────────┐
    │ Offering │◄───┤                                      ├───►│ University   │
    │ (8)      │    │                                      │    │ (75)         │
    └──────────┘    │                                      │    └──────────────┘
  WORKS_IN_OFFERING │                                      │     STUDIED_AT
                    │                                      │
    ┌──────────┐    │                                      │    ┌──────────────┐
    │ Client   │◄───┤                                      ├───►│ Project      │
    │ (36)     │    │                                      │    │ (22)         │
    └──────────┘    └──────────────────────────────────────┘    └──────────────┘
     WORKED_FOR                                                  WORKED_ON
```

---

## Geographic Distribution

| Country | Employees | % | Delivery |
|---------|----------|---|----------|
| India | 45,979 | 35.4% | Offshore |
| USA | 12,389 | 9.5% | Onshore |
| UK | 8,299 | 6.4% | Onshore |
| Philippines | 8,149 | 6.3% | Offshore |
| Germany | 6,832 | 5.3% | Onshore |
| Spain | 5,563 | 4.3% | Onshore |
| Vietnam | 5,535 | 4.3% | Offshore |
| Poland | 5,454 | 4.2% | Nearshore |
| France | 4,175 | 3.2% | Onshore |
| Romania | 4,149 | 3.2% | Nearshore |
| Serbia | 4,116 | 3.2% | Nearshore |
| Australia | 4,089 | 3.1% | Onshore |
| Portugal | 2,852 | 2.2% | Onshore/Near |
| Brazil | 2,803 | 2.2% | Nearshore |
| Bulgaria | 2,716 | 2.1% | Nearshore |
| Italy | 2,711 | 2.1% | Onshore |
| Costa Rica | 1,423 | 1.1% | Nearshore |
| Netherlands | 1,419 | 1.1% | Onshore |
| Denmark | 1,347 | 1.0% | Onshore |

---

## Key Metrics

| Metric | Value |
|--------|-------|
| Total employees | 130,000 |
| On bench | 32,487 (25%) |
| Avg bench duration | 90 days |
| Total certifications | 183,060 |
| Valid certs | 109,383 |
| Expiring certs | 2,946 |
| Expired certs | 70,731 |
| Impressiveness score range | 5.8 – 99.3 |
| Avg impressiveness score | 45.7 |
| Delivery: Offshore | 46% |
| Delivery: Onshore | 37% |
| Delivery: Nearshore | 17% |
