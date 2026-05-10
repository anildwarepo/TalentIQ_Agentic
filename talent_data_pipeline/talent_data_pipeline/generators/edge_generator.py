"""Generate all 12 edge types with correct cardinalities and properties."""

from __future__ import annotations

from typing import Any

from tqdm import tqdm

from talent_data_pipeline.generators.base import BaseGenerator
from talent_data_pipeline.generators.reference_data import (
    ALL_SKILLS,
    CERTIFICATIONS,
    CLIENTS,
    COUNTRY_NATIVE_LANGUAGES,
    COUNTRY_UNIVERSITIES,
    LANGUAGES,
    MANAGERS,
    OFFERINGS,
    PROJECTS,
    SERVICE_LINES,
    SKILLS_BY_DOMAIN,
)


class EdgeGenerator(BaseGenerator):
    """Generate edges between employees and reference nodes."""

    def __init__(self, employees: list[dict[str, Any]], seed: int | None = None):
        super().__init__(seed)
        self.employees = employees

        # Build skill name → domain mapping
        self._skill_to_domain: dict[str, str] = {}
        for domain, skills in SKILLS_BY_DOMAIN.items():
            for s in skills:
                self._skill_to_domain[s] = domain

        # All skill names
        self._all_skill_names = [s["name"] for s in ALL_SKILLS]
        self._cert_names = [c["name"] for c in CERTIFICATIONS]
        self._lang_names = [l["name"] for l in LANGUAGES]
        self._sl_names = [s["name"] for s in SERVICE_LINES]
        self._off_names = [o["name"] for o in OFFERINGS]
        self._mgr_ids = [m["employee_id"] for m in MANAGERS]
        self._client_names = [c["name"] for c in CLIENTS]
        self._project_names = [p["name"] for p in PROJECTS]

    def generate_located_in(self) -> list[dict[str, Any]]:
        """LOCATED_IN: Employee → Location (130K edges, no props)."""
        edges = []
        for emp in self.employees:
            edges.append({
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("city", emp["_location_city"]),
            })
        return edges

    def generate_specializes_in(self) -> list[dict[str, Any]]:
        """SPECIALIZES_IN: Employee → SkillDomain (130K edges, no props)."""
        edges = []
        for emp in self.employees:
            edges.append({
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("name", emp["_domain"]),
            })
        return edges

    def generate_has_skill(self) -> list[dict[str, Any]]:
        """HAS_SKILL: Employee → Skill (~714K edges, with proficiency properties).

        Avg ~5.5 skills per employee, range 1-12.
        Primary skill domain has higher weight.
        """
        edges = []
        levels = ["Basic", "Intermediate", "Advanced", "Expert", "Guru"]
        level_weights = [0.10, 0.25, 0.35, 0.20, 0.10]

        for emp in tqdm(self.employees, desc="HAS_SKILL edges", miniters=10000):
            domain = emp["_domain"]
            domain_skills = SKILLS_BY_DOMAIN.get(domain, [])

            # Number of skills: normal distribution avg 5.5, range 1-12
            n_skills = self.normal_int(5.5, 2.0, 1, 12)

            # Pick skills: prefer domain skills
            chosen_skills: list[str] = []
            # Always include 1-3 from primary domain
            n_domain = min(len(domain_skills), self.rng.randint(1, 3))
            chosen_skills.extend(self.rng.sample(domain_skills, n_domain))

            # Fill remaining from all skills
            remaining = n_skills - len(chosen_skills)
            other_skills = [s for s in self._all_skill_names if s not in chosen_skills]
            if remaining > 0 and other_skills:
                chosen_skills.extend(self.rng.sample(other_skills, min(remaining, len(other_skills))))

            for i, skill in enumerate(chosen_skills):
                yoe = round(max(0.5, self.np_rng.normal(3.0, 2.0)), 1)
                edges.append({
                    "from_key": ("workday_id", emp["workday_id"]),
                    "to_key": ("name", skill),
                    "props": {
                        "level": self.weighted_choice(levels, level_weights),
                        "years_of_experience": yoe,
                        "active": self.rng.random() > 0.1,
                        "is_primary": i == 0,
                    },
                })

        print(f"Generated {len(edges):,} HAS_SKILL edges")
        return edges

    def generate_holds_cert(self) -> list[dict[str, Any]]:
        """HOLDS_CERT: Employee → Certification (~183K edges).

        ~1.4 certs per employee avg. ~60% Valid, ~1.6% Expiring, ~38.6% Expired.
        """
        edges = []
        # Not all employees have certs. ~70% have at least one
        for emp in tqdm(self.employees, desc="HOLDS_CERT edges", miniters=10000):
            if self.rng.random() > 0.70:
                continue

            n_certs = self.normal_int(1.4, 1.0, 1, 5)
            chosen = self.rng.sample(self._cert_names, min(n_certs, len(self._cert_names)))

            for cert in chosen:
                # Status distribution: 60% Valid, 1.6% Expiring, 38.4% Expired
                status = self.weighted_choice(
                    ["Valid", "Expiring", "Expired"],
                    [0.60, 0.016, 0.384],
                )
                issue_year = self.rng.randint(2018, 2025)
                issue_date = self.date_between(issue_year, issue_year)

                if status == "Expired":
                    issue_year = min(issue_year, 2024)  # ensure room for expiry
                    issue_date = self.date_between(issue_year, issue_year)
                    expiry_year = self.rng.randint(issue_year + 1, 2025)
                elif status == "Expiring":
                    expiry_year = 2026  # within 90 days
                else:
                    expiry_year = self.rng.randint(2026, 2029)

                expiry_date = self.date_between(expiry_year, expiry_year)

                edges.append({
                    "from_key": ("workday_id", emp["workday_id"]),
                    "to_key": ("name", cert),
                    "props": {
                        "issue_date": issue_date,
                        "expiry_date": expiry_date,
                        "status": status,
                        "credential_id": f"CERT-{self.rng.randint(100000, 999999)}",
                        "has_evidence": self.rng.random() > 0.3,
                    },
                })

        print(f"Generated {len(edges):,} HOLDS_CERT edges")
        return edges

    def generate_speaks(self) -> list[dict[str, Any]]:
        """SPEAKS: Employee → Language (~261K edges).

        ~2 languages per employee (native + 1-2 others).
        """
        edges = []
        cefr_levels = ["A1", "A2", "B1", "B2", "C1", "C2"]

        for emp in tqdm(self.employees, desc="SPEAKS edges", miniters=10000):
            country = emp["_country"]
            native_langs = COUNTRY_NATIVE_LANGUAGES.get(country, ["English"])

            # Pick 1 native language
            native = self.rng.choice(native_langs)
            edges.append({
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("name", native),
                "props": {"level": "C2", "is_native": True},
            })

            # Additional languages: 0-2
            n_extra = self.weighted_choice([0, 1, 2], [0.20, 0.50, 0.30])
            if n_extra > 0:
                other = [l for l in self._lang_names if l != native]
                # English is most common second language
                if "English" in other and native != "English":
                    extras = ["English"]
                    other.remove("English")
                    if n_extra > 1 and other:
                        extras.append(self.rng.choice(other))
                else:
                    extras = self.rng.sample(other, min(n_extra, len(other)))

                for lang in extras:
                    level = self.weighted_choice(cefr_levels, [0.05, 0.10, 0.25, 0.30, 0.20, 0.10])
                    edges.append({
                        "from_key": ("workday_id", emp["workday_id"]),
                        "to_key": ("name", lang),
                        "props": {"level": level, "is_native": False},
                    })

        print(f"Generated {len(edges):,} SPEAKS edges")
        return edges

    def generate_belongs_to_sl(self) -> list[dict[str, Any]]:
        """BELONGS_TO_SL: Employee → ServiceLine (130K edges)."""
        return [
            {
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("name", self.rng.choice(self._sl_names)),
            }
            for emp in self.employees
        ]

    def generate_works_in_offering(self) -> list[dict[str, Any]]:
        """WORKS_IN_OFFERING: Employee → Offering (130K edges)."""
        return [
            {
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("name", self.rng.choice(self._off_names)),
            }
            for emp in self.employees
        ]

    def generate_reports_to(self) -> list[dict[str, Any]]:
        """REPORTS_TO: Employee → Manager (130K edges)."""
        return [
            {
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("employee_id", self.rng.choice(self._mgr_ids)),
            }
            for emp in self.employees
        ]

    def generate_studied_at(self) -> list[dict[str, Any]]:
        """STUDIED_AT: Employee → University (130K edges, with education props)."""
        edges = []
        for emp in self.employees:
            country = emp["_country"]
            unis = COUNTRY_UNIVERSITIES.get(country, ["Massachusetts Institute of Technology"])
            uni = self.rng.choice(unis)

            grad_year = max(1990, int(emp["hire_date"][:4]) - self.rng.randint(0, 3))

            edges.append({
                "from_key": ("workday_id", emp["workday_id"]),
                "to_key": ("name", uni),
                "props": {
                    "degree": emp["education_degree"],
                    "field": emp["education_field"],
                    "graduation_year": grad_year,
                    "eqf_level": emp["eqf_level"],
                    "meces_level": emp["meces_level"],
                },
            })
        return edges

    def generate_worked_for(self) -> list[dict[str, Any]]:
        """WORKED_FOR: Employee → Client (~336K edges).

        ~2.6 client engagements per employee avg.
        """
        edges = []
        roles = [
            "Software Engineer", "Lead Developer", "Solutions Architect",
            "Data Engineer", "DevOps Engineer", "Project Manager",
            "Business Analyst", "Cloud Architect", "Security Consultant",
            "Full Stack Developer", "Lead ML Engineer", "Platform Engineer",
        ]

        for emp in tqdm(self.employees, desc="WORKED_FOR edges", miniters=10000):
            n = self.normal_int(2.6, 1.2, 1, 6)
            chosen_clients = self.rng.sample(self._client_names, min(n, len(self._client_names)))

            for i, client in enumerate(chosen_clients):
                is_current = i == 0 and not emp["is_bench"]
                start_year = self.rng.randint(2018, 2025) if is_current else self.rng.randint(2018, 2024)
                end_year = self.rng.randint(start_year + 1, 2026) if not is_current else 0

                edges.append({
                    "from_key": ("workday_id", emp["workday_id"]),
                    "to_key": ("name", client),
                    "props": {
                        "role": self.rng.choice(roles),
                        "project": self.rng.choice(self._project_names),
                        "start_date": self.date_between(start_year, start_year),
                        "end_date": "" if is_current else self.date_between(end_year, end_year),
                        "is_current": is_current,
                    },
                })

        print(f"Generated {len(edges):,} WORKED_FOR edges")
        return edges

    def generate_worked_on(self) -> list[dict[str, Any]]:
        """WORKED_ON: Employee → Project (~336K edges)."""
        edges = []
        roles = [
            "Software Engineer", "Lead Developer", "Solutions Architect",
            "Data Engineer", "DevOps Engineer", "Project Manager",
            "Business Analyst", "Cloud Architect", "Security Consultant",
        ]

        for emp in tqdm(self.employees, desc="WORKED_ON edges", miniters=10000):
            n = self.normal_int(2.6, 1.2, 1, 6)
            chosen_projects = self.rng.sample(self._project_names, min(n, len(self._project_names)))

            for i, project in enumerate(chosen_projects):
                is_current = i == 0 and not emp["is_bench"]
                start_year = self.rng.randint(2018, 2025) if is_current else self.rng.randint(2018, 2024)
                end_year = self.rng.randint(start_year + 1, 2026) if not is_current else 0

                edges.append({
                    "from_key": ("workday_id", emp["workday_id"]),
                    "to_key": ("name", project),
                    "props": {
                        "role": self.rng.choice(roles),
                        "start_date": self.date_between(start_year, start_year),
                        "end_date": "" if is_current else self.date_between(end_year, end_year),
                    },
                })

        print(f"Generated {len(edges):,} WORKED_ON edges")
        return edges
