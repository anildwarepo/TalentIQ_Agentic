"""Generate 130,000 employees with culturally appropriate names and realistic distributions."""

from __future__ import annotations

from typing import Any

from faker import Faker
from tqdm import tqdm

from talent_data_pipeline.config import pipeline_config
from talent_data_pipeline.generators.base import BaseGenerator
from talent_data_pipeline.generators.reference_data import (
    COUNTRY_DELIVERY_MODEL,
    COUNTRY_EMPLOYEE_COUNTS,
    DOMAIN_WEIGHTS,
    LOCATIONS,
    SKILL_DOMAINS,
    SERVICE_LINES,
    OFFERINGS,
)

# Faker locale mapping per country
COUNTRY_FAKER_LOCALES: dict[str, list[str]] = {
    "India":        ["en_IN", "hi_IN"],
    "USA":          ["en_US"],
    "UK":           ["en_GB"],
    "Philippines":  ["en_PH"],
    "Germany":      ["de_DE"],
    "Spain":        ["es_ES"],
    "Vietnam":      ["vi_VN"],
    "Poland":       ["pl_PL"],
    "France":       ["fr_FR"],
    "Romania":      ["ro_RO"],
    "Serbia":       ["sr_RS"],
    "Australia":    ["en_AU"],
    "Portugal":     ["pt_PT"],
    "Brazil":       ["pt_BR"],
    "Bulgaria":     ["bg_BG"],
    "Italy":        ["it_IT"],
    "Costa Rica":   ["es_MX"],     # closest locale
    "Netherlands":  ["nl_NL"],
    "Denmark":      ["da_DK"],
}

SKILL_LEVELS = ["Junior", "Mid", "Senior", "Lead", "Principal", "Architect"]
SKILL_LEVEL_JOB_LEVEL: dict[str, tuple[int, int]] = {
    "Junior":    (3, 5),
    "Mid":       (5, 7),
    "Senior":    (7, 9),
    "Lead":      (9, 11),
    "Principal": (11, 13),
    "Architect": (12, 14),
}

EMPLOYMENT_STATUSES = ["Active", "Bench", "Notice Period", "Long-term Leave"]
CV_SOURCES = ["Workday", "Manual Upload", "My Growth"]
DATA_SOURCES = ["Workday", "Workday+CV", "CV Only"]

DEGREES = [
    "Bachelor of Science (BSc)",
    "Bachelor of Engineering (BE)",
    "Bachelor of Technology (BTech)",
    "Bachelor of Arts (BA)",
    "Master of Science (MSc)",
    "Master of Engineering (ME)",
    "Master of Technology (MTech)",
    "Master of Business Administration (MBA)",
    "Doctor of Philosophy (PhD)",
]

EDUCATION_FIELDS = [
    "Computer Science", "Software Engineering", "Information Technology",
    "Electrical Engineering", "Electronics & Communication",
    "Mathematics", "Physics", "Data Science",
    "Mechanical Engineering", "Business Administration",
    "Information Systems", "Cybersecurity",
]

PHONE_PREFIXES: dict[str, str] = {
    "India": "+91", "USA": "+1", "UK": "+44", "Philippines": "+63",
    "Germany": "+49", "Spain": "+34", "Vietnam": "+84", "Poland": "+48",
    "France": "+33", "Romania": "+40", "Serbia": "+381", "Australia": "+61",
    "Portugal": "+351", "Brazil": "+55", "Bulgaria": "+359", "Italy": "+39",
    "Costa Rica": "+506", "Netherlands": "+31", "Denmark": "+45",
}


class EmployeeGenerator(BaseGenerator):
    """Generate 130,000 employee records per the ontology spec."""

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        # Pre-create Faker instances per country
        self._fakers: dict[str, Faker] = {}
        for country, locales in COUNTRY_FAKER_LOCALES.items():
            fake = Faker(locales)
            fake.seed_instance(self.seed)
            self._fakers[country] = fake

        # Country → list of locations
        self._country_locations: dict[str, list[dict]] = {}
        for loc in LOCATIONS:
            self._country_locations.setdefault(loc["country"], []).append(loc)

        # Pre-compute domain list and weights
        self._domains = [d["name"] for d in SKILL_DOMAINS]
        self._domain_weights = [DOMAIN_WEIGHTS.get(d, 0.05) for d in self._domains]

        self._emails: set[str] = set()

    def _generate_phone(self, country: str) -> str:
        prefix = PHONE_PREFIXES.get(country, "+1")
        digits = "".join([str(self.rng.randint(0, 9)) for _ in range(9)])
        return f"{prefix}-{digits[:3]}{digits[3:6]}{digits[6:]}"

    def generate_all(self) -> list[dict[str, Any]]:
        """Generate all employees. Returns list of property dicts."""
        employees: list[dict[str, Any]] = []
        emp_id_counter = 100001

        # Determine bench assignments (25% = 32,487)
        total = pipeline_config.employee_count
        bench_count = 32487

        # Build ordered country list
        country_order = list(COUNTRY_EMPLOYEE_COUNTS.keys())

        # Assign bench slots proportionally across countries
        bench_remaining = bench_count
        country_bench: dict[str, int] = {}
        for i, country in enumerate(country_order):
            cnt = COUNTRY_EMPLOYEE_COUNTS[country]
            if i == len(country_order) - 1:
                country_bench[country] = bench_remaining
            else:
                cb = round(cnt / total * bench_count)
                country_bench[country] = cb
                bench_remaining -= cb

        print(f"Generating {total:,} employees across {len(country_order)} countries...")

        for country in tqdm(country_order, desc="Countries"):
            count = COUNTRY_EMPLOYEE_COUNTS[country]
            fake = self._fakers[country]
            locs = self._country_locations[country]
            delivery = COUNTRY_DELIVERY_MODEL[country]
            n_bench = country_bench[country]

            # Decide which employees are bench (random selection within country)
            bench_indices = set(self.rng.sample(range(count), min(n_bench, count)))

            for i in range(count):
                first = fake.first_name()
                last = fake.last_name()
                email = self.generate_email(first, last, self._emails)
                workday_id = f"WD-{emp_id_counter}"
                emp_id_counter += 1

                loc = self.rng.choice(locs)
                is_bench = i in bench_indices

                # Job/skill level with bell-curve distribution
                skill_level = self.weighted_choice(
                    SKILL_LEVELS,
                    [0.08, 0.20, 0.30, 0.22, 0.13, 0.07],
                )
                jl_lo, jl_hi = SKILL_LEVEL_JOB_LEVEL[skill_level]
                job_level = self.rng.randint(jl_lo, jl_hi)

                years_exp = max(1, job_level - 2 + self.rng.randint(-1, 3))
                hire_year = max(2000, 2026 - years_exp - self.rng.randint(0, 2))
                hire_date = self.date_between(hire_year, min(hire_year, 2025))

                domain = self.weighted_choice(self._domains, self._domain_weights)

                if is_bench:
                    emp_status = "Bench"
                    bench_start = self.date_between(2025, 2026)
                    bench_dur = self.rng.randint(1, 180)
                    current_project = ""
                    fte_cur = 0
                    fte_next = 0
                    fte_next2 = 0
                    avail = self.date_between(2026, 2026)
                else:
                    emp_status = self.weighted_choice(
                        ["Active", "Notice Period", "Long-term Leave"],
                        [0.92, 0.04, 0.04],
                    )
                    bench_start = ""
                    bench_dur = 0
                    current_project = fake.bs().title()[:60]
                    fte_cur = self.weighted_choice([100, 75, 50], [0.70, 0.20, 0.10])
                    fte_next = self.weighted_choice([100, 75, 50, 25], [0.60, 0.20, 0.10, 0.10])
                    fte_next2 = self.weighted_choice([100, 75, 50, 25, 0], [0.50, 0.20, 0.10, 0.10, 0.10])
                    avail = "" if fte_cur == 100 else self.date_between(2026, 2027)

                hourly_cost = round(20 + (job_level - 3) * 8.5 + self.np_rng.normal(0, 5), 2)
                hourly_cost = max(15.0, hourly_cost)
                bill_rate = round(hourly_cost * self.np_rng.uniform(1.4, 2.0), 2)

                cv_freshness = self.rng.randint(0, 365)
                impressiveness = round(
                    max(5.8, min(99.3, self.np_rng.normal(45.7, 18.0))), 1
                )

                eqf = self.rng.choices([5, 6, 7, 8], weights=[0.15, 0.40, 0.35, 0.10], k=1)[0]
                meces = max(1, min(4, eqf - 4))

                degree = self.rng.choice(DEGREES)
                edu_field = self.rng.choice(EDUCATION_FIELDS)

                job_title_prefix = {
                    "Junior": "Junior", "Mid": "", "Senior": "Senior",
                    "Lead": "Lead", "Principal": "Principal", "Architect": "Architect",
                }.get(skill_level, "")
                job_title_base = self.rng.choice([
                    "Software Engineer", "Developer", "Consultant",
                    "Cloud Engineer", "Data Engineer", "DevOps Engineer",
                    "Solutions Architect", "Business Analyst", "Security Analyst",
                    "Full Stack Developer", "Backend Engineer", "Platform Engineer",
                ])
                job_title = f"{job_title_prefix} {job_title_base}".strip()

                emp = {
                    "name": f"{first} {last}",
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "phone": self._generate_phone(country),
                    "workday_id": workday_id,
                    "job_title": job_title,
                    "job_level": job_level,
                    "skill_level": skill_level,
                    "hire_date": hire_date,
                    "years_of_experience": years_exp,
                    "employment_status": emp_status,
                    "is_bench": is_bench,
                    "bench_start_date": bench_start,
                    "bench_duration_days": bench_dur,
                    "availability_date": avail,
                    "current_project": current_project,
                    "fte_current_month": fte_cur,
                    "fte_next_month": fte_next,
                    "fte_next2_month": fte_next2,
                    "hourly_cost_usd": hourly_cost,
                    "bill_rate_usd": bill_rate,
                    "cv_last_updated": self.date_between(2024, 2026),
                    "cv_freshness_days": cv_freshness,
                    "cv_source": self.rng.choice(CV_SOURCES),
                    "impressiveness_score": impressiveness,
                    "data_source": self.rng.choice(DATA_SOURCES),
                    "delivery_model": delivery,
                    "eqf_level": eqf,
                    "meces_level": meces,
                    "eqf_mapping_status": self.rng.choice(["Mapped", "Pending mapping"]),
                    "education_degree": degree,
                    "education_field": edu_field,
                    "resume_summary": "",  # filled by resume_generator
                    # Metadata for edge generation (not stored as node properties)
                    "_country": country,
                    "_location_city": loc["city"],
                    "_domain": domain,
                }
                employees.append(emp)

        print(f"Generated {len(employees):,} employees")
        return employees
