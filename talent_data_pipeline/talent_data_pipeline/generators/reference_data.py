"""Generate all reference/dimension data nodes per the TalentIQ ontology."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from talent_data_pipeline.generators.base import BaseGenerator

# ─────────────────────────────────────────────────────────────
# COUNTRIES & GEOGRAPHIC DATA (19 countries, 46 locations)
# ─────────────────────────────────────────────────────────────

COUNTRIES: list[dict[str, str]] = [
    {"name": "India",        "code": "IN", "region": "Asia-Pacific"},
    {"name": "USA",          "code": "US", "region": "Americas"},
    {"name": "UK",           "code": "GB", "region": "Europe"},
    {"name": "Philippines",  "code": "PH", "region": "Asia-Pacific"},
    {"name": "Germany",      "code": "DE", "region": "Europe"},
    {"name": "Spain",        "code": "ES", "region": "Europe"},
    {"name": "Vietnam",      "code": "VN", "region": "Asia-Pacific"},
    {"name": "Poland",       "code": "PL", "region": "Europe"},
    {"name": "France",       "code": "FR", "region": "Europe"},
    {"name": "Romania",      "code": "RO", "region": "Europe"},
    {"name": "Serbia",       "code": "RS", "region": "Europe"},
    {"name": "Australia",    "code": "AU", "region": "Asia-Pacific"},
    {"name": "Portugal",     "code": "PT", "region": "Europe"},
    {"name": "Brazil",       "code": "BR", "region": "Americas"},
    {"name": "Bulgaria",     "code": "BG", "region": "Europe"},
    {"name": "Italy",        "code": "IT", "region": "Europe"},
    {"name": "Costa Rica",   "code": "CR", "region": "Americas"},
    {"name": "Netherlands",  "code": "NL", "region": "Europe"},
    {"name": "Denmark",      "code": "DK", "region": "Europe"},
]

# Employee distribution by country (must sum to 130,000)
COUNTRY_EMPLOYEE_COUNTS: dict[str, int] = {
    "India": 45979, "USA": 12389, "UK": 8299, "Philippines": 8149,
    "Germany": 6832, "Spain": 5563, "Vietnam": 5535, "Poland": 5454,
    "France": 4175, "Romania": 4149, "Serbia": 4116, "Australia": 4089,
    "Portugal": 2852, "Brazil": 2803, "Bulgaria": 2716, "Italy": 2711,
    "Costa Rica": 1423, "Netherlands": 1419, "Denmark": 1347,
}

COUNTRY_DELIVERY_MODEL: dict[str, str] = {
    "India": "offshore", "USA": "onshore", "UK": "onshore",
    "Philippines": "offshore", "Germany": "onshore", "Spain": "onshore",
    "Vietnam": "offshore", "Poland": "nearshore", "France": "onshore",
    "Romania": "nearshore", "Serbia": "nearshore", "Australia": "onshore",
    "Portugal": "onshore", "Brazil": "nearshore", "Bulgaria": "nearshore",
    "Italy": "onshore", "Costa Rica": "nearshore", "Netherlands": "onshore",
    "Denmark": "onshore",
}

SUBREGIONS: list[dict[str, Any]] = [
    {"name": "GDN-IN",          "region": "Asia-Pacific"},
    {"name": "Americas-US",     "region": "Americas"},
    {"name": "UKI",             "region": "Europe"},
    {"name": "GDN-PH",          "region": "Asia-Pacific"},
    {"name": "DACH",            "region": "Europe"},
    {"name": "Iberia",          "region": "Europe"},
    {"name": "GDN-VN",          "region": "Asia-Pacific"},
    {"name": "CEE",             "region": "Europe"},
    {"name": "France",          "region": "Europe"},
    {"name": "SEE",             "region": "Europe"},
    {"name": "ANZ",             "region": "Asia-Pacific"},
    {"name": "Southern Europe", "region": "Europe"},
    {"name": "Americas-LATAM",  "region": "Americas"},
    {"name": "Benelux",         "region": "Europe"},
    {"name": "Nordics",         "region": "Europe"},
]

COUNTRY_SUBREGION: dict[str, str] = {
    "India": "GDN-IN", "USA": "Americas-US", "UK": "UKI",
    "Philippines": "GDN-PH", "Germany": "DACH", "Spain": "Iberia",
    "Vietnam": "GDN-VN", "Poland": "CEE", "France": "France",
    "Romania": "SEE", "Serbia": "SEE", "Australia": "ANZ",
    "Portugal": "Iberia", "Brazil": "Americas-LATAM",
    "Bulgaria": "SEE", "Italy": "Southern Europe",
    "Costa Rica": "Americas-LATAM", "Netherlands": "Benelux",
    "Denmark": "Nordics",
}

# 46 locations across 19 countries
LOCATIONS: list[dict[str, str]] = [
    # India (8)
    {"city": "Bangalore",  "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "560048",  "address": "DXC Manyata Tech Park",          "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Hyderabad",  "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "500081",  "address": "DXC Hitech City Campus",         "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Chennai",    "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "600096",  "address": "DXC SIPCOT IT Park",             "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Noida",      "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "201301",  "address": "DXC Sector 62 Tower",            "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Pune",       "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "411057",  "address": "DXC Hinjewadi Phase III",         "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Mumbai",     "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "400076",  "address": "DXC Airoli Knowledge Park",       "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Kolkata",    "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "700156",  "address": "DXC Sector V Salt Lake",          "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    {"city": "Gurgaon",    "country": "India",  "country_code": "IN", "region": "Asia-Pacific", "subregion": "GDN-IN", "zip": "122002",  "address": "DXC Cyber City Tower",            "timezone": "Asia/Kolkata",       "delivery_model": "offshore"},
    # USA (4)
    {"city": "Ashburn",       "country": "USA", "country_code": "US", "region": "Americas", "subregion": "Americas-US", "zip": "20147",  "address": "1775 Tysons Blvd",              "timezone": "America/New_York",    "delivery_model": "onshore"},
    {"city": "Plano",         "country": "USA", "country_code": "US", "region": "Americas", "subregion": "Americas-US", "zip": "75024",  "address": "5400 Legacy Dr",                "timezone": "America/Chicago",     "delivery_model": "onshore"},
    {"city": "New Orleans",   "country": "USA", "country_code": "US", "region": "Americas", "subregion": "Americas-US", "zip": "70130",  "address": "1555 Poydras St",               "timezone": "America/Chicago",     "delivery_model": "onshore"},
    {"city": "Tulsa",         "country": "USA", "country_code": "US", "region": "Americas", "subregion": "Americas-US", "zip": "74103",  "address": "One Williams Center",            "timezone": "America/Chicago",     "delivery_model": "onshore"},
    # UK (3)
    {"city": "London",     "country": "UK",  "country_code": "GB", "region": "Europe", "subregion": "UKI", "zip": "EC2N 1HQ", "address": "20 Fenchurch St",    "timezone": "Europe/London",  "delivery_model": "onshore"},
    {"city": "Newcastle",  "country": "UK",  "country_code": "GB", "region": "Europe", "subregion": "UKI", "zip": "NE1 3DY",  "address": "The Core, Bath Lane","timezone": "Europe/London",  "delivery_model": "onshore"},
    {"city": "Manchester", "country": "UK",  "country_code": "GB", "region": "Europe", "subregion": "UKI", "zip": "M1 4BT",   "address": "Peter House, Oxford St","timezone": "Europe/London","delivery_model": "onshore"},
    # Philippines (2)
    {"city": "Manila",     "country": "Philippines", "country_code": "PH", "region": "Asia-Pacific", "subregion": "GDN-PH", "zip": "1634", "address": "McKinley West Corporate Center", "timezone": "Asia/Manila", "delivery_model": "offshore"},
    {"city": "Cebu",       "country": "Philippines", "country_code": "PH", "region": "Asia-Pacific", "subregion": "GDN-PH", "zip": "6000", "address": "Cebu IT Park Tower 1",           "timezone": "Asia/Manila", "delivery_model": "offshore"},
    # Germany (3)
    {"city": "Munich",      "country": "Germany", "country_code": "DE", "region": "Europe", "subregion": "DACH", "zip": "80807", "address": "Frankfurter Ring 105",      "timezone": "Europe/Berlin",  "delivery_model": "onshore"},
    {"city": "Stuttgart",   "country": "Germany", "country_code": "DE", "region": "Europe", "subregion": "DACH", "zip": "70567", "address": "Industriestr. 32",           "timezone": "Europe/Berlin",  "delivery_model": "onshore"},
    {"city": "Frankfurt",   "country": "Germany", "country_code": "DE", "region": "Europe", "subregion": "DACH", "zip": "60528", "address": "Hahnstraße 40",              "timezone": "Europe/Berlin",  "delivery_model": "onshore"},
    # Spain (2)
    {"city": "Madrid",     "country": "Spain", "country_code": "ES", "region": "Europe", "subregion": "Iberia", "zip": "28042", "address": "Calle Albasanz 16",  "timezone": "Europe/Madrid",  "delivery_model": "onshore"},
    {"city": "Barcelona",  "country": "Spain", "country_code": "ES", "region": "Europe", "subregion": "Iberia", "zip": "08019", "address": "Carrer Llull 95",     "timezone": "Europe/Madrid",  "delivery_model": "onshore"},
    # Vietnam (2)
    {"city": "Ho Chi Minh City", "country": "Vietnam", "country_code": "VN", "region": "Asia-Pacific", "subregion": "GDN-VN", "zip": "700000", "address": "Saigon Hi-Tech Park",     "timezone": "Asia/Ho_Chi_Minh", "delivery_model": "offshore"},
    {"city": "Hanoi",            "country": "Vietnam", "country_code": "VN", "region": "Asia-Pacific", "subregion": "GDN-VN", "zip": "100000", "address": "Cau Giay Tech Hub",        "timezone": "Asia/Ho_Chi_Minh", "delivery_model": "offshore"},
    # Poland (2)
    {"city": "Wroclaw",  "country": "Poland", "country_code": "PL", "region": "Europe", "subregion": "CEE", "zip": "50-086", "address": "Plac Grunwaldzki 23", "timezone": "Europe/Warsaw",  "delivery_model": "nearshore"},
    {"city": "Warsaw",   "country": "Poland", "country_code": "PL", "region": "Europe", "subregion": "CEE", "zip": "00-150", "address": "ul. Marszalkowska 82","timezone": "Europe/Warsaw",  "delivery_model": "nearshore"},
    # France (2)
    {"city": "Paris",     "country": "France", "country_code": "FR", "region": "Europe", "subregion": "France", "zip": "92400", "address": "Tour Areva, La Défense",  "timezone": "Europe/Paris",  "delivery_model": "onshore"},
    {"city": "Lyon",      "country": "France", "country_code": "FR", "region": "Europe", "subregion": "France", "zip": "69003", "address": "21 Rue de la Villette",    "timezone": "Europe/Paris",  "delivery_model": "onshore"},
    # Romania (2)
    {"city": "Bucharest", "country": "Romania", "country_code": "RO", "region": "Europe", "subregion": "SEE", "zip": "020335", "address": "Str. Buzesti 75-77",       "timezone": "Europe/Bucharest", "delivery_model": "nearshore"},
    {"city": "Cluj-Napoca","country": "Romania", "country_code": "RO", "region": "Europe", "subregion": "SEE", "zip": "400000", "address": "Str. Memorandumului 28",   "timezone": "Europe/Bucharest", "delivery_model": "nearshore"},
    # Serbia (1)
    {"city": "Belgrade", "country": "Serbia", "country_code": "RS", "region": "Europe", "subregion": "SEE", "zip": "11070", "address": "Vladimira Popovica 6", "timezone": "Europe/Belgrade", "delivery_model": "nearshore"},
    # Australia (2)
    {"city": "Sydney",    "country": "Australia", "country_code": "AU", "region": "Asia-Pacific", "subregion": "ANZ", "zip": "2000", "address": "201 Elizabeth St",    "timezone": "Australia/Sydney",    "delivery_model": "onshore"},
    {"city": "Melbourne", "country": "Australia", "country_code": "AU", "region": "Asia-Pacific", "subregion": "ANZ", "zip": "3000", "address": "500 Collins St",      "timezone": "Australia/Melbourne",  "delivery_model": "onshore"},
    # Portugal (2)
    {"city": "Lisbon", "country": "Portugal", "country_code": "PT", "region": "Europe", "subregion": "Iberia", "zip": "1990-084", "address": "Parque das Nações, Rua do Bojador", "timezone": "Europe/Lisbon", "delivery_model": "onshore"},
    {"city": "Porto",  "country": "Portugal", "country_code": "PT", "region": "Europe", "subregion": "Iberia", "zip": "4100-136", "address": "Rua Eng. Ferreira Dias 728",      "timezone": "Europe/Lisbon", "delivery_model": "onshore"},
    # Brazil (2)
    {"city": "São Paulo",       "country": "Brazil", "country_code": "BR", "region": "Americas", "subregion": "Americas-LATAM", "zip": "04543-011", "address": "Av. Brigadeiro Faria Lima 3900", "timezone": "America/Sao_Paulo", "delivery_model": "nearshore"},
    {"city": "Rio de Janeiro",  "country": "Brazil", "country_code": "BR", "region": "Americas", "subregion": "Americas-LATAM", "zip": "20031-170", "address": "Av. Rio Branco 115",              "timezone": "America/Sao_Paulo", "delivery_model": "nearshore"},
    # Bulgaria (1)
    {"city": "Sofia", "country": "Bulgaria", "country_code": "BG", "region": "Europe", "subregion": "SEE", "zip": "1407", "address": "103 Cherni Vrah Blvd", "timezone": "Europe/Sofia", "delivery_model": "nearshore"},
    # Italy (2)
    {"city": "Milan", "country": "Italy", "country_code": "IT", "region": "Europe", "subregion": "Southern Europe", "zip": "20124", "address": "Via Pirelli 39",   "timezone": "Europe/Rome", "delivery_model": "onshore"},
    {"city": "Rome",  "country": "Italy", "country_code": "IT", "region": "Europe", "subregion": "Southern Europe", "zip": "00144", "address": "Viale Europa 175", "timezone": "Europe/Rome", "delivery_model": "onshore"},
    # Costa Rica (1)
    {"city": "San José", "country": "Costa Rica", "country_code": "CR", "region": "Americas", "subregion": "Americas-LATAM", "zip": "10104", "address": "Oficentro La Virgen", "timezone": "America/Costa_Rica", "delivery_model": "nearshore"},
    # Netherlands (1)
    {"city": "Amsterdam", "country": "Netherlands", "country_code": "NL", "region": "Europe", "subregion": "Benelux", "zip": "1101 CM", "address": "Bijlmerdreef 24", "timezone": "Europe/Amsterdam", "delivery_model": "onshore"},
    # Denmark (1)
    {"city": "Copenhagen", "country": "Denmark", "country_code": "DK", "region": "Europe", "subregion": "Nordics", "zip": "2300", "address": "Amager Strandvej 390", "timezone": "Europe/Copenhagen", "delivery_model": "onshore"},
]

# ─────────────────────────────────────────────────────────────
# SKILL DOMAINS & SKILLS (13 domains, 96 skills)
# ─────────────────────────────────────────────────────────────

SKILL_DOMAINS: list[dict[str, str]] = [
    {"name": "Python"},
    {"name": "Java"},
    {"name": "C#/.NET"},
    {"name": "JavaScript/TS"},
    {"name": "Cloud (Azure)"},
    {"name": "Cloud (AWS)"},
    {"name": "DevOps/SRE"},
    {"name": "Data Engineering"},
    {"name": "AI/ML"},
    {"name": "SAP"},
    {"name": "Salesforce"},
    {"name": "Cybersecurity"},
    {"name": "ServiceNow"},
]

SKILLS_BY_DOMAIN: dict[str, list[str]] = {
    "Python": ["Python", "Django", "Flask", "FastAPI", "Pandas", "NumPy", "Celery", "SQLAlchemy"],
    "Java": ["Java", "Spring Boot", "Hibernate", "Maven", "Gradle", "Kafka", "Microservices", "JUnit"],
    "C#/.NET": ["C#", ".NET Core", "ASP.NET", "Entity Framework", "Blazor", "WPF", "Azure Functions", "NUnit"],
    "JavaScript/TS": ["JavaScript", "TypeScript", "React", "Angular", "Node.js", "Vue.js", "Next.js", "Express"],
    "Cloud (Azure)": ["Azure DevOps", "Azure Kubernetes Service", "Azure Functions", "Azure SQL", "Azure Data Factory", "Azure Cosmos DB", "ARM Templates", "Bicep"],
    "Cloud (AWS)": ["AWS Lambda", "EC2", "S3", "DynamoDB", "CloudFormation", "EKS", "SQS", "API Gateway"],
    "DevOps/SRE": ["Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "GitHub Actions", "Prometheus", "Grafana"],
    "Data Engineering": ["Apache Spark", "Databricks", "Snowflake", "dbt", "Airflow", "Kafka", "ETL", "Data Modeling"],
    "AI/ML": ["TensorFlow", "PyTorch", "Scikit-learn", "OpenAI API", "LangChain", "MLflow", "Computer Vision", "NLP"],
    "SAP": ["SAP S/4HANA", "SAP ABAP", "SAP Fiori", "SAP BTP", "SAP Integration Suite", "SAP SuccessFactors", "SAP Analytics Cloud"],
    "Salesforce": ["Salesforce Admin", "Apex", "Lightning Web Components", "Salesforce CPQ", "MuleSoft", "Salesforce Marketing Cloud", "Tableau CRM"],
    "Cybersecurity": ["SIEM", "SOC", "Penetration Testing", "Identity & Access Management", "Zero Trust", "Cloud Security", "Threat Intelligence", "Incident Response"],
    "ServiceNow": ["ServiceNow ITSM", "ServiceNow ITOM", "ServiceNow CSM", "ServiceNow SecOps", "ServiceNow Flow Designer", "ServiceNow App Engine"],
}

# Flatten for the Skill node list
ALL_SKILLS: list[dict[str, str]] = [{"name": s} for skills in SKILLS_BY_DOMAIN.values() for s in skills]

# Domain weights for employee distribution
DOMAIN_WEIGHTS: dict[str, float] = {
    "Python": 0.12, "Java": 0.14, "C#/.NET": 0.10, "JavaScript/TS": 0.11,
    "Cloud (Azure)": 0.10, "Cloud (AWS)": 0.07, "DevOps/SRE": 0.09,
    "Data Engineering": 0.07, "AI/ML": 0.05, "SAP": 0.05,
    "Salesforce": 0.04, "Cybersecurity": 0.04, "ServiceNow": 0.02,
}

# ─────────────────────────────────────────────────────────────
# CERTIFICATIONS (39)
# ─────────────────────────────────────────────────────────────

CERTIFICATIONS: list[dict[str, str]] = [
    {"name": "AWS Certified Solutions Architect – Associate"},
    {"name": "AWS Certified Solutions Architect – Professional"},
    {"name": "AWS Certified Developer – Associate"},
    {"name": "AWS Certified SysOps Administrator"},
    {"name": "Microsoft Azure Administrator (AZ-104)"},
    {"name": "Microsoft Azure Solutions Architect (AZ-305)"},
    {"name": "Microsoft Azure Developer (AZ-204)"},
    {"name": "Microsoft Azure DevOps Engineer (AZ-400)"},
    {"name": "Microsoft Azure AI Engineer (AI-102)"},
    {"name": "Microsoft Azure Data Engineer (DP-203)"},
    {"name": "Microsoft Power Platform Developer (PL-400)"},
    {"name": "Google Cloud Professional Cloud Architect"},
    {"name": "Google Cloud Professional Data Engineer"},
    {"name": "Certified Kubernetes Administrator (CKA)"},
    {"name": "Certified Kubernetes Application Developer (CKAD)"},
    {"name": "HashiCorp Terraform Associate"},
    {"name": "PMI Project Management Professional (PMP)"},
    {"name": "PRINCE2 Foundation"},
    {"name": "PRINCE2 Practitioner"},
    {"name": "Certified ScrumMaster (CSM)"},
    {"name": "SAFe Agilist (SA)"},
    {"name": "ITIL 4 Foundation"},
    {"name": "ITIL 4 Managing Professional"},
    {"name": "CompTIA Security+"},
    {"name": "CISSP (Certified Information Systems Security Professional)"},
    {"name": "CEH (Certified Ethical Hacker)"},
    {"name": "SAP Certified Application Associate"},
    {"name": "SAP Certified Technology Associate"},
    {"name": "Salesforce Certified Administrator"},
    {"name": "Salesforce Certified Platform Developer I"},
    {"name": "Salesforce Certified Platform Developer II"},
    {"name": "ServiceNow Certified System Administrator"},
    {"name": "ServiceNow Certified Application Developer"},
    {"name": "Databricks Certified Data Engineer Associate"},
    {"name": "Snowflake SnowPro Core Certification"},
    {"name": "Oracle Certified Professional Java SE"},
    {"name": "Red Hat Certified System Administrator (RHCSA)"},
    {"name": "Cisco CCNA"},
    {"name": "TOGAF Certified"},
]

# ─────────────────────────────────────────────────────────────
# LANGUAGES (18)
# ─────────────────────────────────────────────────────────────

LANGUAGES: list[dict[str, str]] = [
    {"name": "English"}, {"name": "Hindi"}, {"name": "Spanish"},
    {"name": "French"}, {"name": "German"}, {"name": "Portuguese"},
    {"name": "Italian"}, {"name": "Dutch"}, {"name": "Polish"},
    {"name": "Romanian"}, {"name": "Serbian"}, {"name": "Bulgarian"},
    {"name": "Danish"}, {"name": "Vietnamese"}, {"name": "Filipino"},
    {"name": "Telugu"}, {"name": "Tamil"}, {"name": "Kannada"},
]

# Native languages per country
COUNTRY_NATIVE_LANGUAGES: dict[str, list[str]] = {
    "India": ["Hindi", "Telugu", "Tamil", "Kannada", "English"],
    "USA": ["English"],
    "UK": ["English"],
    "Philippines": ["Filipino", "English"],
    "Germany": ["German"],
    "Spain": ["Spanish"],
    "Vietnam": ["Vietnamese"],
    "Poland": ["Polish"],
    "France": ["French"],
    "Romania": ["Romanian"],
    "Serbia": ["Serbian"],
    "Australia": ["English"],
    "Portugal": ["Portuguese"],
    "Brazil": ["Portuguese"],
    "Bulgaria": ["Bulgarian"],
    "Italy": ["Italian"],
    "Costa Rica": ["Spanish"],
    "Netherlands": ["Dutch"],
    "Denmark": ["Danish"],
}

# ─────────────────────────────────────────────────────────────
# SERVICE LINES (8) & OFFERINGS (8)
# ─────────────────────────────────────────────────────────────

SERVICE_LINES: list[dict[str, str]] = [
    {"name": "GBS – Analytics & Engineering"},
    {"name": "GBS – Applications"},
    {"name": "GBS – Cloud & ITO"},
    {"name": "GBS – Modern Workplace"},
    {"name": "GIS – Cloud Infrastructure"},
    {"name": "GIS – Security"},
    {"name": "GIS – Workplace & Mobility"},
    {"name": "Industry Software & BPS"},
]

OFFERINGS: list[dict[str, str]] = [
    {"name": "Cloud & ITO"},
    {"name": "Analytics & AI"},
    {"name": "Application Services"},
    {"name": "Modern Workplace"},
    {"name": "Security"},
    {"name": "Industry Software"},
    {"name": "Insurance Software"},
    {"name": "Banking & Capital Markets"},
]

# ─────────────────────────────────────────────────────────────
# UNIVERSITIES (75) — realistic global distribution
# ─────────────────────────────────────────────────────────────

UNIVERSITIES: list[dict[str, str]] = [
    # India (15)
    {"name": "Indian Institute of Technology Bombay"},
    {"name": "Indian Institute of Technology Delhi"},
    {"name": "Indian Institute of Technology Madras"},
    {"name": "Indian Institute of Science Bangalore"},
    {"name": "National Institute of Technology Trichy"},
    {"name": "BITS Pilani"},
    {"name": "Jawaharlal Nehru University"},
    {"name": "University of Delhi"},
    {"name": "Anna University Chennai"},
    {"name": "Osmania University Hyderabad"},
    {"name": "VIT University"},
    {"name": "Manipal Institute of Technology"},
    {"name": "SRM Institute of Science and Technology"},
    {"name": "Amity University"},
    {"name": "Lovely Professional University"},
    # USA (8)
    {"name": "Massachusetts Institute of Technology"},
    {"name": "Stanford University"},
    {"name": "Carnegie Mellon University"},
    {"name": "Georgia Institute of Technology"},
    {"name": "University of Illinois Urbana-Champaign"},
    {"name": "University of Texas at Austin"},
    {"name": "Purdue University"},
    {"name": "Arizona State University"},
    # UK (6)
    {"name": "University of Oxford"},
    {"name": "University of Cambridge"},
    {"name": "Imperial College London"},
    {"name": "University of Edinburgh"},
    {"name": "University of Manchester"},
    {"name": "University College London"},
    # Germany (5)
    {"name": "Technische Universität München"},
    {"name": "RWTH Aachen University"},
    {"name": "Karlsruhe Institute of Technology"},
    {"name": "Freie Universität Berlin"},
    {"name": "Universität Stuttgart"},
    # Spain (5)
    {"name": "Universidad Politécnica de Madrid"},
    {"name": "Universitat Politècnica de Catalunya"},
    {"name": "Universidad de Barcelona"},
    {"name": "Universidad Carlos III de Madrid"},
    {"name": "Universidad de Sevilla"},
    # France (4)
    {"name": "École Polytechnique"},
    {"name": "Sorbonne Université"},
    {"name": "INSA Lyon"},
    {"name": "Université Paris-Saclay"},
    # Philippines (3)
    {"name": "University of the Philippines Diliman"},
    {"name": "Ateneo de Manila University"},
    {"name": "De La Salle University"},
    # Vietnam (3)
    {"name": "Hanoi University of Science and Technology"},
    {"name": "Ho Chi Minh City University of Technology"},
    {"name": "Vietnam National University Hanoi"},
    # Poland (3)
    {"name": "Warsaw University of Technology"},
    {"name": "AGH University of Science and Technology"},
    {"name": "Wroclaw University of Science and Technology"},
    # Romania (2)
    {"name": "Politehnica University of Bucharest"},
    {"name": "Babeș-Bolyai University"},
    # Serbia (2)
    {"name": "University of Belgrade"},
    {"name": "University of Novi Sad"},
    # Australia (3)
    {"name": "University of Melbourne"},
    {"name": "University of Sydney"},
    {"name": "UNSW Sydney"},
    # Portugal (2)
    {"name": "Universidade de Lisboa"},
    {"name": "Universidade do Porto"},
    # Brazil (3)
    {"name": "Universidade de São Paulo"},
    {"name": "Universidade Federal do Rio de Janeiro"},
    {"name": "Universidade Estadual de Campinas"},
    # Bulgaria (2)
    {"name": "Sofia University"},
    {"name": "Technical University of Sofia"},
    # Italy (3)
    {"name": "Politecnico di Milano"},
    {"name": "Sapienza Università di Roma"},
    {"name": "Università di Bologna"},
    # Others (2)
    {"name": "Delft University of Technology"},
    {"name": "Technical University of Denmark"},
    # Costa Rica (1)
    {"name": "Universidad de Costa Rica"},
    # Netherlands (1)
    {"name": "Eindhoven University of Technology"},
    # Denmark (1)
    {"name": "Aarhus University"},
]

# Country → Universities mapping for realistic education
COUNTRY_UNIVERSITIES: dict[str, list[str]] = {
    "India": [u["name"] for u in UNIVERSITIES[:15]],
    "USA": [u["name"] for u in UNIVERSITIES[15:23]],
    "UK": [u["name"] for u in UNIVERSITIES[23:29]],
    "Germany": [u["name"] for u in UNIVERSITIES[29:34]],
    "Spain": [u["name"] for u in UNIVERSITIES[34:39]],
    "France": [u["name"] for u in UNIVERSITIES[39:43]],
    "Philippines": [u["name"] for u in UNIVERSITIES[43:46]],
    "Vietnam": [u["name"] for u in UNIVERSITIES[46:49]],
    "Poland": [u["name"] for u in UNIVERSITIES[49:52]],
    "Romania": [u["name"] for u in UNIVERSITIES[52:54]],
    "Serbia": [u["name"] for u in UNIVERSITIES[54:56]],
    "Australia": [u["name"] for u in UNIVERSITIES[56:59]],
    "Portugal": [u["name"] for u in UNIVERSITIES[59:61]],
    "Brazil": [u["name"] for u in UNIVERSITIES[61:64]],
    "Bulgaria": [u["name"] for u in UNIVERSITIES[64:66]],
    "Italy": [u["name"] for u in UNIVERSITIES[66:69]],
    "Costa Rica": ["Universidad de Costa Rica"],
    "Netherlands": ["Delft University of Technology", "Eindhoven University of Technology"],
    "Denmark": ["Technical University of Denmark", "Aarhus University"],
}

# ─────────────────────────────────────────────────────────────
# CLIENTS (36) & PROJECTS (22)
# ─────────────────────────────────────────────────────────────

CLIENTS: list[dict[str, str]] = [
    {"name": "Telefónica"}, {"name": "BBVA"}, {"name": "Siemens"},
    {"name": "BMW Group"}, {"name": "AXA"}, {"name": "BNP Paribas"},
    {"name": "Rolls-Royce"}, {"name": "BP"}, {"name": "Shell"},
    {"name": "Unilever"}, {"name": "Deutsche Bank"}, {"name": "Allianz"},
    {"name": "Nestlé"}, {"name": "Novartis"}, {"name": "Roche"},
    {"name": "Toyota Motor"}, {"name": "Sony"}, {"name": "Samsung"},
    {"name": "Infosys (subcontract)"}, {"name": "Tata Motors"},
    {"name": "Reliance Industries"}, {"name": "Airbus"},
    {"name": "Volkswagen"}, {"name": "Bosch"}, {"name": "SAP SE"},
    {"name": "L'Oréal"}, {"name": "Philips"}, {"name": "Ericsson"},
    {"name": "Nokia"}, {"name": "ABB"}, {"name": "Schneider Electric"},
    {"name": "TotalEnergies"}, {"name": "Enel"}, {"name": "Vodafone"},
    {"name": "Commonwealth Bank"}, {"name": "Petrobras"},
]

PROJECTS: list[dict[str, str]] = [
    {"name": "Cloud Migration Program"},
    {"name": "SAP S/4HANA Transformation"},
    {"name": "Digital Workplace Modernization"},
    {"name": "AI/ML Platform Build"},
    {"name": "Cybersecurity Operations Center"},
    {"name": "Data Lake & Analytics Platform"},
    {"name": "Salesforce CRM Implementation"},
    {"name": "ServiceNow ITSM Rollout"},
    {"name": "DevOps Pipeline Automation"},
    {"name": "Application Modernization"},
    {"name": "IoT Edge Computing Platform"},
    {"name": "Blockchain Supply Chain"},
    {"name": "Managed Cloud Services"},
    {"name": "Network Infrastructure Refresh"},
    {"name": "ERP Consolidation"},
    {"name": "Customer Experience Platform"},
    {"name": "Insurance Claims Automation"},
    {"name": "Banking Digital Channels"},
    {"name": "HR Transformation Program"},
    {"name": "Sustainability Dashboard"},
    {"name": "Zero Trust Security Program"},
    {"name": "API Gateway Modernization"},
]

# ─────────────────────────────────────────────────────────────
# MANAGERS (80) — generated with locale-appropriate names
# ─────────────────────────────────────────────────────────────

MANAGERS: list[dict[str, str]] = [
    {"name": "Carmen Pérez",       "email": "carmen.perez@dxc.com",       "employee_id": "DXC-M0001"},
    {"name": "Rajesh Kumar",       "email": "rajesh.kumar@dxc.com",       "employee_id": "DXC-M0002"},
    {"name": "Sarah Johnson",      "email": "sarah.johnson@dxc.com",      "employee_id": "DXC-M0003"},
    {"name": "Hans Müller",        "email": "hans.mueller@dxc.com",       "employee_id": "DXC-M0004"},
    {"name": "Marie Dubois",       "email": "marie.dubois@dxc.com",       "employee_id": "DXC-M0005"},
    {"name": "Priya Sharma",       "email": "priya.sharma@dxc.com",       "employee_id": "DXC-M0006"},
    {"name": "James Williams",     "email": "james.williams@dxc.com",     "employee_id": "DXC-M0007"},
    {"name": "Ana García",         "email": "ana.garcia@dxc.com",         "employee_id": "DXC-M0008"},
    {"name": "Marco Rossi",        "email": "marco.rossi@dxc.com",        "employee_id": "DXC-M0009"},
    {"name": "Jan Kowalski",       "email": "jan.kowalski@dxc.com",       "employee_id": "DXC-M0010"},
    {"name": "Nguyen Van Minh",    "email": "nguyen.van.minh@dxc.com",    "employee_id": "DXC-M0011"},
    {"name": "Maria Santos",       "email": "maria.santos@dxc.com",       "employee_id": "DXC-M0012"},
    {"name": "Elena Popescu",      "email": "elena.popescu@dxc.com",      "employee_id": "DXC-M0013"},
    {"name": "Dragan Jović",       "email": "dragan.jovic@dxc.com",       "employee_id": "DXC-M0014"},
    {"name": "Petar Dimitrov",     "email": "petar.dimitrov@dxc.com",     "employee_id": "DXC-M0015"},
    {"name": "Lars Jensen",        "email": "lars.jensen@dxc.com",        "employee_id": "DXC-M0016"},
    {"name": "Pieter de Vries",    "email": "pieter.devries@dxc.com",     "employee_id": "DXC-M0017"},
    {"name": "Carlos Rodríguez",   "email": "carlos.rodriguez@dxc.com",   "employee_id": "DXC-M0018"},
    {"name": "Sofia Petrov",       "email": "sofia.petrov@dxc.com",       "employee_id": "DXC-M0019"},
    {"name": "Thomas Brown",       "email": "thomas.brown@dxc.com",       "employee_id": "DXC-M0020"},
    {"name": "Anita Desai",        "email": "anita.desai@dxc.com",        "employee_id": "DXC-M0021"},
    {"name": "Vikram Patel",       "email": "vikram.patel@dxc.com",       "employee_id": "DXC-M0022"},
    {"name": "Deepa Nair",         "email": "deepa.nair@dxc.com",         "employee_id": "DXC-M0023"},
    {"name": "Suresh Reddy",       "email": "suresh.reddy@dxc.com",       "employee_id": "DXC-M0024"},
    {"name": "Arun Iyer",          "email": "arun.iyer@dxc.com",          "employee_id": "DXC-M0025"},
    {"name": "Kavitha Raman",      "email": "kavitha.raman@dxc.com",      "employee_id": "DXC-M0026"},
    {"name": "Michael Scott",      "email": "michael.scott@dxc.com",      "employee_id": "DXC-M0027"},
    {"name": "David Chen",         "email": "david.chen@dxc.com",         "employee_id": "DXC-M0028"},
    {"name": "Jennifer Lee",       "email": "jennifer.lee@dxc.com",       "employee_id": "DXC-M0029"},
    {"name": "Robert Taylor",      "email": "robert.taylor@dxc.com",      "employee_id": "DXC-M0030"},
    {"name": "Wolfgang Schmidt",   "email": "wolfgang.schmidt@dxc.com",   "employee_id": "DXC-M0031"},
    {"name": "Klaus Weber",        "email": "klaus.weber@dxc.com",        "employee_id": "DXC-M0032"},
    {"name": "Sabine Fischer",     "email": "sabine.fischer@dxc.com",     "employee_id": "DXC-M0033"},
    {"name": "Pierre Martin",      "email": "pierre.martin@dxc.com",      "employee_id": "DXC-M0034"},
    {"name": "Sophie Lefebvre",    "email": "sophie.lefebvre@dxc.com",    "employee_id": "DXC-M0035"},
    {"name": "Maria Cruz",         "email": "maria.cruz@dxc.com",         "employee_id": "DXC-M0036"},
    {"name": "José Reyes",         "email": "jose.reyes@dxc.com",         "employee_id": "DXC-M0037"},
    {"name": "Emma Watson",        "email": "emma.watson@dxc.com",        "employee_id": "DXC-M0038"},
    {"name": "Oliver Smith",       "email": "oliver.smith@dxc.com",       "employee_id": "DXC-M0039"},
    {"name": "Charlotte Davies",   "email": "charlotte.davies@dxc.com",   "employee_id": "DXC-M0040"},
    {"name": "Tran Thi Lan",       "email": "tran.thi.lan@dxc.com",       "employee_id": "DXC-M0041"},
    {"name": "Le Hoang Nam",       "email": "le.hoang.nam@dxc.com",       "employee_id": "DXC-M0042"},
    {"name": "Anna Nowak",         "email": "anna.nowak@dxc.com",         "employee_id": "DXC-M0043"},
    {"name": "Tomasz Wiśniewski",  "email": "tomasz.wisniewski@dxc.com",  "employee_id": "DXC-M0044"},
    {"name": "Ion Popa",           "email": "ion.popa@dxc.com",           "employee_id": "DXC-M0045"},
    {"name": "Miloš Petrović",     "email": "milos.petrovic@dxc.com",     "employee_id": "DXC-M0046"},
    {"name": "Todor Ivanov",       "email": "todor.ivanov@dxc.com",       "employee_id": "DXC-M0047"},
    {"name": "Liam O'Brien",       "email": "liam.obrien@dxc.com",        "employee_id": "DXC-M0048"},
    {"name": "Grace Chen",         "email": "grace.chen@dxc.com",         "employee_id": "DXC-M0049"},
    {"name": "Peter Wilson",       "email": "peter.wilson@dxc.com",       "employee_id": "DXC-M0050"},
    {"name": "João Silva",         "email": "joao.silva@dxc.com",         "employee_id": "DXC-M0051"},
    {"name": "Lucas Oliveira",     "email": "lucas.oliveira@dxc.com",     "employee_id": "DXC-M0052"},
    {"name": "Giuseppe Bianchi",   "email": "giuseppe.bianchi@dxc.com",   "employee_id": "DXC-M0053"},
    {"name": "Francesca Conti",    "email": "francesca.conti@dxc.com",    "employee_id": "DXC-M0054"},
    {"name": "Roberto Morales",    "email": "roberto.morales@dxc.com",    "employee_id": "DXC-M0055"},
    {"name": "Mads Andersen",      "email": "mads.andersen@dxc.com",      "employee_id": "DXC-M0056"},
    {"name": "Willem Bakker",      "email": "willem.bakker@dxc.com",      "employee_id": "DXC-M0057"},
    {"name": "Manish Gupta",       "email": "manish.gupta@dxc.com",       "employee_id": "DXC-M0058"},
    {"name": "Rohit Mehta",        "email": "rohit.mehta@dxc.com",        "employee_id": "DXC-M0059"},
    {"name": "Neha Agarwal",       "email": "neha.agarwal@dxc.com",       "employee_id": "DXC-M0060"},
    {"name": "Sanjay Verma",       "email": "sanjay.verma@dxc.com",       "employee_id": "DXC-M0061"},
    {"name": "Pooja Joshi",        "email": "pooja.joshi@dxc.com",        "employee_id": "DXC-M0062"},
    {"name": "Ramesh Babu",        "email": "ramesh.babu@dxc.com",        "employee_id": "DXC-M0063"},
    {"name": "Maria Ruiz de Eguino", "email": "maria.ruiz@dxc.com",      "employee_id": "DXC-M0064"},
    {"name": "Chen Wei",           "email": "chen.wei@dxc.com",           "employee_id": "DXC-M0065"},
    {"name": "Isabel Fernández",   "email": "isabel.fernandez@dxc.com",   "employee_id": "DXC-M0066"},
    {"name": "Adriana Stanescu",   "email": "adriana.stanescu@dxc.com",   "employee_id": "DXC-M0067"},
    {"name": "Bogdan Marinescu",   "email": "bogdan.marinescu@dxc.com",   "employee_id": "DXC-M0068"},
    {"name": "Stefan Nikolov",     "email": "stefan.nikolov@dxc.com",     "employee_id": "DXC-M0069"},
    {"name": "Andrew Thompson",    "email": "andrew.thompson@dxc.com",    "employee_id": "DXC-M0070"},
    {"name": "Rebecca Hall",       "email": "rebecca.hall@dxc.com",       "employee_id": "DXC-M0071"},
    {"name": "Pham Duc Anh",       "email": "pham.duc.anh@dxc.com",       "employee_id": "DXC-M0072"},
    {"name": "Katarzyna Wójcik",   "email": "katarzyna.wojcik@dxc.com",   "employee_id": "DXC-M0073"},
    {"name": "Alejandro López",    "email": "alejandro.lopez@dxc.com",    "employee_id": "DXC-M0074"},
    {"name": "Paulo Costa",        "email": "paulo.costa@dxc.com",        "employee_id": "DXC-M0075"},
    {"name": "Dimitar Georgiev",   "email": "dimitar.georgiev@dxc.com",   "employee_id": "DXC-M0076"},
    {"name": "Nikola Stanković",   "email": "nikola.stankovic@dxc.com",   "employee_id": "DXC-M0077"},
    {"name": "Chris Anderson",     "email": "chris.anderson@dxc.com",     "employee_id": "DXC-M0078"},
    {"name": "Amit Chatterjee",    "email": "amit.chatterjee@dxc.com",    "employee_id": "DXC-M0079"},
    {"name": "Sunita Menon",       "email": "sunita.menon@dxc.com",       "employee_id": "DXC-M0080"},
]


class ReferenceDataGenerator(BaseGenerator):
    """Generates all reference/dimension data as Python dicts ready for graph loading."""

    def generate_all(self) -> dict[str, list[dict[str, Any]]]:
        """Return a dict keyed by node label → list of node property dicts."""
        return {
            "Country": COUNTRIES,
            "Subregion": SUBREGIONS,
            "Location": LOCATIONS,
            "Skill": ALL_SKILLS,
            "SkillDomain": SKILL_DOMAINS,
            "Certification": CERTIFICATIONS,
            "Language": LANGUAGES,
            "ServiceLine": SERVICE_LINES,
            "Offering": OFFERINGS,
            "Manager": MANAGERS,
            "University": UNIVERSITIES,
            "Client": CLIENTS,
            "Project": PROJECTS,
        }

    def generate_location_country_edges(self) -> list[dict[str, str]]:
        """Generate IN_COUNTRY edges: Location → Country."""
        edges = []
        for loc in LOCATIONS:
            edges.append({
                "from_label": "Location",
                "from_key": ("city", loc["city"]),
                "to_label": "Country",
                "to_key": ("code", loc["country_code"]),
            })
        return edges
