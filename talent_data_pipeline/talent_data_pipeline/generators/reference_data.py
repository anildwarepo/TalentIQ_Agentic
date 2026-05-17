"""Generate all reference/dimension data nodes per the TalentIQ ontology."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from talent_data_pipeline.generators.base import BaseGenerator

# ─────────────────────────────────────────────────────────────
# COUNTRIES & GEOGRAPHIC DATA (19 countries, 46 locations)
# ─────────────────────────────────────────────────────────────

COUNTRIES: list[dict] = [
    {"name": "India",        "code": "IN", "region": "Asia-Pacific", "aliases": []},
    {"name": "USA",          "code": "US", "region": "Americas",     "aliases": ["United States", "America", "US", "U.S."]},
    {"name": "UK",           "code": "GB", "region": "Europe",       "aliases": ["United Kingdom", "Britain", "Great Britain"]},
    {"name": "Philippines",  "code": "PH", "region": "Asia-Pacific", "aliases": ["Filipinas"]},
    {"name": "Germany",      "code": "DE", "region": "Europe",       "aliases": []},
    {"name": "Spain",        "code": "ES", "region": "Europe",       "aliases": []},
    {"name": "Vietnam",      "code": "VN", "region": "Asia-Pacific", "aliases": []},
    {"name": "Poland",       "code": "PL", "region": "Europe",       "aliases": []},
    {"name": "France",       "code": "FR", "region": "Europe",       "aliases": []},
    {"name": "Romania",      "code": "RO", "region": "Europe",       "aliases": []},
    {"name": "Serbia",       "code": "RS", "region": "Europe",       "aliases": []},
    {"name": "Australia",    "code": "AU", "region": "Asia-Pacific", "aliases": []},
    {"name": "Portugal",     "code": "PT", "region": "Europe",       "aliases": []},
    {"name": "Brazil",       "code": "BR", "region": "Americas",     "aliases": []},
    {"name": "Bulgaria",     "code": "BG", "region": "Europe",       "aliases": []},
    {"name": "Italy",        "code": "IT", "region": "Europe",       "aliases": []},
    {"name": "Costa Rica",   "code": "CR", "region": "Americas",     "aliases": []},
    {"name": "Netherlands",  "code": "NL", "region": "Europe",       "aliases": []},
    {"name": "Denmark",      "code": "DK", "region": "Europe",       "aliases": []},
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

SKILL_DOMAINS: list[dict] = [
    {"name": "Python",         "code": "PYTHON",      "aliases": ["Py"]},
    {"name": "Java",           "code": "JAVA",         "aliases": []},
    {"name": "C#/.NET",        "code": "DOTNET",       "aliases": ["dotnet", "C#", ".NET", "CSharp"]},
    {"name": "JavaScript/TS",  "code": "JS-TS",        "aliases": ["JavaScript", "TypeScript", "JS", "TS"]},
    {"name": "Cloud (Azure)",  "code": "CLOUD-AZURE",  "aliases": ["Azure"]},
    {"name": "Cloud (AWS)",    "code": "CLOUD-AWS",    "aliases": ["AWS"]},
    {"name": "DevOps/SRE",     "code": "DEVOPS-SRE",   "aliases": ["DevOps", "SRE"]},
    {"name": "Data Engineering","code": "DATA-ENG",     "aliases": ["Data"]},
    {"name": "AI/ML",          "code": "AI-ML",         "aliases": ["AI", "ML", "Machine Learning"]},
    {"name": "SAP",            "code": "SAP",           "aliases": []},
    {"name": "Salesforce",     "code": "SFDC",          "aliases": ["SFDC"]},
    {"name": "Cybersecurity",  "code": "CYBERSEC",      "aliases": ["Security", "InfoSec"]},
    {"name": "ServiceNow",     "code": "SNOW",          "aliases": ["SNOW"]},
]

SKILLS_BY_DOMAIN: dict[str, list[dict]] = {
    "Python": [
        {"name": "Python", "code": "PYTHON", "aliases": ["Python3", "Py"]},
        {"name": "Django", "code": "DJANGO", "aliases": []},
        {"name": "Flask", "code": "FLASK", "aliases": []},
        {"name": "FastAPI", "code": "FASTAPI", "aliases": []},
        {"name": "Pandas", "code": "PANDAS", "aliases": []},
        {"name": "NumPy", "code": "NUMPY", "aliases": []},
        {"name": "Celery", "code": "CELERY", "aliases": []},
        {"name": "SQLAlchemy", "code": "SQLALCHEMY", "aliases": []},
    ],
    "Java": [
        {"name": "Java", "code": "JAVA", "aliases": []},
        {"name": "Spring Boot", "code": "SPRING-BOOT", "aliases": ["Spring"]},
        {"name": "Hibernate", "code": "HIBERNATE", "aliases": []},
        {"name": "Maven", "code": "MAVEN", "aliases": []},
        {"name": "Gradle", "code": "GRADLE", "aliases": []},
        {"name": "Kafka", "code": "KAFKA", "aliases": []},
        {"name": "Microservices", "code": "MICROSERVICES", "aliases": []},
        {"name": "JUnit", "code": "JUNIT", "aliases": []},
    ],
    "C#/.NET": [
        {"name": "C#", "code": "CSHARP", "aliases": ["C#", "CSharp", "dotnet"]},
        {"name": ".NET Core", "code": "DOTNET-CORE", "aliases": ["dotnet core", ".NET"]},
        {"name": "ASP.NET", "code": "ASPNET", "aliases": ["ASP.NET"]},
        {"name": "Entity Framework", "code": "EF", "aliases": ["EF"]},
        {"name": "Blazor", "code": "BLAZOR", "aliases": []},
        {"name": "WPF", "code": "WPF", "aliases": []},
        {"name": "Azure Functions", "code": "AZ-FUNC", "aliases": ["Azure Functions"]},
        {"name": "NUnit", "code": "NUNIT", "aliases": []},
    ],
    "JavaScript/TS": [
        {"name": "JavaScript", "code": "JAVASCRIPT", "aliases": ["JS"]},
        {"name": "TypeScript", "code": "TYPESCRIPT", "aliases": ["TS"]},
        {"name": "React", "code": "REACT", "aliases": ["ReactJS"]},
        {"name": "Angular", "code": "ANGULAR", "aliases": []},
        {"name": "Node.js", "code": "NODEJS", "aliases": ["Node", "NodeJS"]},
        {"name": "Vue.js", "code": "VUEJS", "aliases": ["Vue"]},
        {"name": "Next.js", "code": "NEXTJS", "aliases": ["Next"]},
        {"name": "Express", "code": "EXPRESS", "aliases": ["ExpressJS"]},
    ],
    "Cloud (Azure)": [
        {"name": "Azure DevOps", "code": "AZ-DEVOPS", "aliases": ["ADO"]},
        {"name": "Azure Kubernetes Service", "code": "AKS", "aliases": ["AKS"]},
        {"name": "Azure Functions", "code": "AZ-FUNC", "aliases": ["Azure Functions"]},
        {"name": "Azure SQL", "code": "AZ-SQL", "aliases": []},
        {"name": "Azure Data Factory", "code": "ADF", "aliases": ["ADF"]},
        {"name": "Azure Cosmos DB", "code": "COSMOSDB", "aliases": ["CosmosDB", "Cosmos"]},
        {"name": "ARM Templates", "code": "ARM", "aliases": ["ARM"]},
        {"name": "Bicep", "code": "BICEP", "aliases": []},
    ],
    "Cloud (AWS)": [
        {"name": "AWS Lambda", "code": "LAMBDA", "aliases": ["Lambda"]},
        {"name": "EC2", "code": "EC2", "aliases": ["AWS EC2"]},
        {"name": "S3", "code": "S3", "aliases": ["AWS S3"]},
        {"name": "DynamoDB", "code": "DYNAMODB", "aliases": []},
        {"name": "CloudFormation", "code": "CFN", "aliases": ["CFN"]},
        {"name": "EKS", "code": "EKS", "aliases": ["AWS EKS"]},
        {"name": "SQS", "code": "SQS", "aliases": ["AWS SQS"]},
        {"name": "API Gateway", "code": "APIGW", "aliases": ["API GW"]},
    ],
    "DevOps/SRE": [
        {"name": "Docker", "code": "DOCKER", "aliases": []},
        {"name": "Kubernetes", "code": "K8S", "aliases": ["k8s", "Kube"]},
        {"name": "Terraform", "code": "TERRAFORM", "aliases": ["TF"]},
        {"name": "Ansible", "code": "ANSIBLE", "aliases": []},
        {"name": "Jenkins", "code": "JENKINS", "aliases": []},
        {"name": "GitHub Actions", "code": "GH-ACTIONS", "aliases": ["GHA"]},
        {"name": "Prometheus", "code": "PROMETHEUS", "aliases": []},
        {"name": "Grafana", "code": "GRAFANA", "aliases": []},
    ],
    "Data Engineering": [
        {"name": "Apache Spark", "code": "SPARK", "aliases": ["Spark"]},
        {"name": "Databricks", "code": "DATABRICKS", "aliases": []},
        {"name": "Snowflake", "code": "SNOWFLAKE", "aliases": []},
        {"name": "dbt", "code": "DBT", "aliases": []},
        {"name": "Airflow", "code": "AIRFLOW", "aliases": ["Apache Airflow"]},
        {"name": "Kafka", "code": "KAFKA", "aliases": []},
        {"name": "ETL", "code": "ETL", "aliases": []},
        {"name": "Data Modeling", "code": "DATA-MODELING", "aliases": []},
    ],
    "AI/ML": [
        {"name": "TensorFlow", "code": "TENSORFLOW", "aliases": ["TF"]},
        {"name": "PyTorch", "code": "PYTORCH", "aliases": []},
        {"name": "Scikit-learn", "code": "SKLEARN", "aliases": ["sklearn"]},
        {"name": "OpenAI API", "code": "OPENAI", "aliases": ["OpenAI"]},
        {"name": "LangChain", "code": "LANGCHAIN", "aliases": []},
        {"name": "MLflow", "code": "MLFLOW", "aliases": []},
        {"name": "Computer Vision", "code": "CV", "aliases": ["CV"]},
        {"name": "NLP", "code": "NLP", "aliases": ["Natural Language Processing"]},
    ],
    "SAP": [
        {"name": "SAP S/4HANA", "code": "S4HANA", "aliases": ["S/4HANA"]},
        {"name": "SAP ABAP", "code": "ABAP", "aliases": ["ABAP"]},
        {"name": "SAP Fiori", "code": "FIORI", "aliases": ["Fiori"]},
        {"name": "SAP BTP", "code": "BTP", "aliases": ["BTP"]},
        {"name": "SAP Integration Suite", "code": "SAP-IS", "aliases": []},
        {"name": "SAP SuccessFactors", "code": "SAP-SF", "aliases": ["SuccessFactors"]},
        {"name": "SAP Analytics Cloud", "code": "SAC", "aliases": ["SAC"]},
    ],
    "Salesforce": [
        {"name": "Salesforce Admin", "code": "SF-ADMIN", "aliases": []},
        {"name": "Apex", "code": "APEX", "aliases": []},
        {"name": "Lightning Web Components", "code": "LWC", "aliases": ["LWC"]},
        {"name": "Salesforce CPQ", "code": "CPQ", "aliases": ["CPQ"]},
        {"name": "MuleSoft", "code": "MULESOFT", "aliases": []},
        {"name": "Salesforce Marketing Cloud", "code": "SFMC", "aliases": ["SFMC"]},
        {"name": "Tableau CRM", "code": "TABLEAU-CRM", "aliases": ["CRMA"]},
    ],
    "Cybersecurity": [
        {"name": "SIEM", "code": "SIEM", "aliases": []},
        {"name": "SOC", "code": "SOC", "aliases": []},
        {"name": "Penetration Testing", "code": "PENTEST", "aliases": ["PenTest"]},
        {"name": "Identity & Access Management", "code": "IAM", "aliases": ["IAM"]},
        {"name": "Zero Trust", "code": "ZERO-TRUST", "aliases": []},
        {"name": "Cloud Security", "code": "CLOUD-SEC", "aliases": []},
        {"name": "Threat Intelligence", "code": "THREAT-INTEL", "aliases": []},
        {"name": "Incident Response", "code": "IR", "aliases": ["IR"]},
    ],
    "ServiceNow": [
        {"name": "ServiceNow ITSM", "code": "SNOW-ITSM", "aliases": ["ITSM"]},
        {"name": "ServiceNow ITOM", "code": "SNOW-ITOM", "aliases": ["ITOM"]},
        {"name": "ServiceNow CSM", "code": "SNOW-CSM", "aliases": []},
        {"name": "ServiceNow SecOps", "code": "SNOW-SECOPS", "aliases": ["SecOps"]},
        {"name": "ServiceNow Flow Designer", "code": "SNOW-FLOW", "aliases": []},
        {"name": "ServiceNow App Engine", "code": "SNOW-AE", "aliases": []},
    ],
}

# Flatten for the Skill node list
ALL_SKILLS: list[dict] = [s for skills in SKILLS_BY_DOMAIN.values() for s in skills]

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

CERTIFICATIONS: list[dict] = [
    {"name": "AWS Certified Solutions Architect – Associate", "code": "AWS-SAA", "aliases": ["AWS SAA", "AWS Solutions Architect", "AWS Architect Associate"]},
    {"name": "AWS Certified Solutions Architect – Professional", "code": "AWS-SAP", "aliases": ["AWS SAP", "AWS Solutions Architect Pro"]},
    {"name": "AWS Certified Developer – Associate", "code": "AWS-DEV", "aliases": ["AWS Developer"]},
    {"name": "AWS Certified SysOps Administrator", "code": "AWS-SYSOPS", "aliases": ["AWS SysOps"]},
    {"name": "Microsoft Azure Administrator (AZ-104)", "code": "AZ-104", "aliases": ["AZ-104", "Azure Admin"]},
    {"name": "Microsoft Azure Solutions Architect (AZ-305)", "code": "AZ-305", "aliases": ["AZ-305", "Azure Architect"]},
    {"name": "Microsoft Azure Developer (AZ-204)", "code": "AZ-204", "aliases": ["AZ-204", "Azure Developer"]},
    {"name": "Microsoft Azure DevOps Engineer (AZ-400)", "code": "AZ-400", "aliases": ["AZ-400", "Azure DevOps"]},
    {"name": "Microsoft Azure AI Engineer (AI-102)", "code": "AI-102", "aliases": ["AI-102", "Azure AI"]},
    {"name": "Microsoft Azure Data Engineer (DP-203)", "code": "DP-203", "aliases": ["DP-203", "Azure Data"]},
    {"name": "Microsoft Power Platform Developer (PL-400)", "code": "PL-400", "aliases": ["PL-400", "Power Platform"]},
    {"name": "Google Cloud Professional Cloud Architect", "code": "GCP-ARCH", "aliases": ["GCP Architect", "Google Cloud Architect"]},
    {"name": "Google Cloud Professional Data Engineer", "code": "GCP-DE", "aliases": ["GCP Data Engineer", "Google Cloud Data"]},
    {"name": "Certified Kubernetes Administrator (CKA)", "code": "CKA", "aliases": ["CKA", "Kubernetes Admin"]},
    {"name": "Certified Kubernetes Application Developer (CKAD)", "code": "CKAD", "aliases": ["CKAD", "Kubernetes Developer"]},
    {"name": "HashiCorp Terraform Associate", "code": "TERRAFORM", "aliases": ["Terraform", "HCL Terraform"]},
    {"name": "PMI Project Management Professional (PMP)", "code": "PMP", "aliases": ["PMP", "Project Management Professional"]},
    {"name": "PRINCE2 Foundation", "code": "PRINCE2-F", "aliases": ["PRINCE2 Foundation", "PRINCE2"]},
    {"name": "PRINCE2 Practitioner", "code": "PRINCE2-P", "aliases": ["PRINCE2 Practitioner"]},
    {"name": "Certified ScrumMaster (CSM)", "code": "CSM", "aliases": ["CSM", "ScrumMaster", "Scrum Master"]},
    {"name": "SAFe Agilist (SA)", "code": "SA", "aliases": ["SAFe", "SAFe Agilist"]},
    {"name": "ITIL 4 Foundation", "code": "ITIL4-F", "aliases": ["ITIL 4", "ITIL Foundation"]},
    {"name": "ITIL 4 Managing Professional", "code": "ITIL4-MP", "aliases": ["ITIL MP", "ITIL Managing Professional"]},
    {"name": "CompTIA Security+", "code": "SEC+", "aliases": ["Security+", "CompTIA Security"]},
    {"name": "CISSP (Certified Information Systems Security Professional)", "code": "CISSP", "aliases": ["CISSP"]},
    {"name": "CEH (Certified Ethical Hacker)", "code": "CEH", "aliases": ["CEH", "Ethical Hacker"]},
    {"name": "SAP Certified Application Associate", "code": "SAP-APP", "aliases": ["SAP App", "SAP Application"]},
    {"name": "SAP Certified Technology Associate", "code": "SAP-TECH", "aliases": ["SAP Tech", "SAP Technology"]},
    {"name": "Salesforce Certified Administrator", "code": "SF-ADMIN", "aliases": ["Salesforce Admin"]},
    {"name": "Salesforce Certified Platform Developer I", "code": "SF-DEV1", "aliases": ["Salesforce Dev I", "Salesforce Developer 1"]},
    {"name": "Salesforce Certified Platform Developer II", "code": "SF-DEV2", "aliases": ["Salesforce Dev II", "Salesforce Developer 2"]},
    {"name": "ServiceNow Certified System Administrator", "code": "SNOW-ADMIN", "aliases": ["ServiceNow Admin"]},
    {"name": "ServiceNow Certified Application Developer", "code": "SNOW-DEV", "aliases": ["ServiceNow Developer", "ServiceNow Dev"]},
    {"name": "Databricks Certified Data Engineer Associate", "code": "DBR-DE", "aliases": ["Databricks", "Databricks Data Engineer"]},
    {"name": "Snowflake SnowPro Core Certification", "code": "SNOWPRO", "aliases": ["SnowPro", "Snowflake Core"]},
    {"name": "Oracle Certified Professional Java SE", "code": "OCP-JAVA", "aliases": ["Oracle Java", "OCP Java"]},
    {"name": "Red Hat Certified System Administrator (RHCSA)", "code": "RHCSA", "aliases": ["RHCSA", "Red Hat Admin"]},
    {"name": "Cisco CCNA", "code": "CCNA", "aliases": ["CCNA", "Cisco CCNA"]},
    {"name": "TOGAF Certified", "code": "TOGAF", "aliases": ["TOGAF"]},
]

# ─────────────────────────────────────────────────────────────
# LANGUAGES (18)
# ─────────────────────────────────────────────────────────────

LANGUAGES: list[dict] = [
    {"name": "English",    "code": "EN", "aliases": []},
    {"name": "Hindi",      "code": "HI", "aliases": []},
    {"name": "Spanish",    "code": "ES", "aliases": []},
    {"name": "French",     "code": "FR", "aliases": []},
    {"name": "German",     "code": "DE", "aliases": []},
    {"name": "Portuguese", "code": "PT", "aliases": []},
    {"name": "Italian",    "code": "IT", "aliases": []},
    {"name": "Dutch",      "code": "NL", "aliases": []},
    {"name": "Polish",     "code": "PL", "aliases": []},
    {"name": "Romanian",   "code": "RO", "aliases": []},
    {"name": "Serbian",    "code": "SR", "aliases": []},
    {"name": "Bulgarian",  "code": "BG", "aliases": []},
    {"name": "Danish",     "code": "DA", "aliases": []},
    {"name": "Vietnamese", "code": "VI", "aliases": []},
    {"name": "Filipino",   "code": "TL", "aliases": ["Tagalog"]},
    {"name": "Telugu",     "code": "TE", "aliases": []},
    {"name": "Tamil",      "code": "TA", "aliases": []},
    {"name": "Kannada",    "code": "KN", "aliases": []},
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

SERVICE_LINES: list[dict] = [
    {"name": "GBS – Analytics & Engineering", "code": "GBS-AE",    "aliases": ["GBS Analytics", "Analytics & Engineering"]},
    {"name": "GBS – Applications",           "code": "GBS-APP",   "aliases": ["GBS Applications", "GBS Apps"]},
    {"name": "GBS – Cloud & ITO",            "code": "GBS-CLOUD", "aliases": ["GBS Cloud"]},
    {"name": "GBS – Modern Workplace",       "code": "GBS-MW",    "aliases": ["GBS Modern Workplace"]},
    {"name": "GIS – Cloud Infrastructure",   "code": "GIS-CI",    "aliases": ["GIS Cloud"]},
    {"name": "GIS – Security",               "code": "GIS-SEC",   "aliases": ["GIS Security"]},
    {"name": "GIS – Workplace & Mobility",   "code": "GIS-WM",    "aliases": ["GIS Workplace"]},
    {"name": "Industry Software & BPS",      "code": "IS-BPS",    "aliases": ["Industry Software", "BPS"]},
]

OFFERINGS: list[dict] = [
    {"name": "Cloud & ITO",              "code": "CLOUD-ITO",     "aliases": ["Cloud", "ITO"]},
    {"name": "Analytics & AI",           "code": "ANALYTICS-AI",  "aliases": ["Analytics", "AI"]},
    {"name": "Application Services",     "code": "APP-SVC",       "aliases": ["App Services"]},
    {"name": "Modern Workplace",         "code": "MOD-WORK",      "aliases": ["Workplace"]},
    {"name": "Security",                 "code": "SECURITY",      "aliases": []},
    {"name": "Industry Software",        "code": "IND-SW",        "aliases": []},
    {"name": "Insurance Software",       "code": "INS-SW",        "aliases": ["Insurance"]},
    {"name": "Banking & Capital Markets","code": "BCM",            "aliases": ["Banking", "Capital Markets"]},
]

# ─────────────────────────────────────────────────────────────
# UNIVERSITIES (75) — realistic global distribution
# ─────────────────────────────────────────────────────────────

UNIVERSITIES: list[dict] = [
    # India (15)
    {"name": "Indian Institute of Technology Bombay", "code": "IIT-B", "aliases": ["IIT Bombay", "IITB"]},
    {"name": "Indian Institute of Technology Delhi", "code": "IIT-D", "aliases": ["IIT Delhi", "IITD"]},
    {"name": "Indian Institute of Technology Madras", "code": "IIT-M", "aliases": ["IIT Madras", "IITM"]},
    {"name": "Indian Institute of Science Bangalore", "code": "IISC", "aliases": ["IISc"]},
    {"name": "National Institute of Technology Trichy", "code": "NIT-T", "aliases": ["NIT Trichy"]},
    {"name": "BITS Pilani", "code": "BITS", "aliases": ["BITS"]},
    {"name": "Jawaharlal Nehru University", "code": "JNU", "aliases": ["JNU"]},
    {"name": "University of Delhi", "code": "DU", "aliases": ["Delhi University", "DU"]},
    {"name": "Anna University Chennai", "code": "ANNA", "aliases": ["Anna University"]},
    {"name": "Osmania University Hyderabad", "code": "OU-HYD", "aliases": ["Osmania"]},
    {"name": "VIT University", "code": "VIT", "aliases": ["VIT"]},
    {"name": "Manipal Institute of Technology", "code": "MIT-MANIPAL", "aliases": ["Manipal"]},
    {"name": "SRM Institute of Science and Technology", "code": "SRM", "aliases": ["SRM"]},
    {"name": "Amity University", "code": "AMITY", "aliases": ["Amity"]},
    {"name": "Lovely Professional University", "code": "LPU", "aliases": ["LPU"]},
    # USA (8)
    {"name": "Massachusetts Institute of Technology", "code": "MIT", "aliases": ["MIT"]},
    {"name": "Stanford University", "code": "STANFORD", "aliases": ["Stanford"]},
    {"name": "Carnegie Mellon University", "code": "CMU", "aliases": ["CMU"]},
    {"name": "Georgia Institute of Technology", "code": "GATECH", "aliases": ["Georgia Tech"]},
    {"name": "University of Illinois Urbana-Champaign", "code": "UIUC", "aliases": ["UIUC"]},
    {"name": "University of Texas at Austin", "code": "UT-AUSTIN", "aliases": ["UT Austin"]},
    {"name": "Purdue University", "code": "PURDUE", "aliases": ["Purdue"]},
    {"name": "Arizona State University", "code": "ASU", "aliases": ["ASU"]},
    # UK (6)
    {"name": "University of Oxford", "code": "OXFORD", "aliases": ["Oxford"]},
    {"name": "University of Cambridge", "code": "CAMBRIDGE", "aliases": ["Cambridge"]},
    {"name": "Imperial College London", "code": "IMPERIAL", "aliases": ["Imperial"]},
    {"name": "University of Edinburgh", "code": "EDINBURGH", "aliases": ["Edinburgh"]},
    {"name": "University of Manchester", "code": "MANCHESTER", "aliases": ["Manchester"]},
    {"name": "University College London", "code": "UCL", "aliases": ["UCL"]},
    # Germany (5)
    {"name": "Technische Universität München", "code": "TUM", "aliases": ["TUM", "TU Munich"]},
    {"name": "RWTH Aachen University", "code": "RWTH", "aliases": ["RWTH Aachen"]},
    {"name": "Karlsruhe Institute of Technology", "code": "KIT", "aliases": ["KIT"]},
    {"name": "Freie Universität Berlin", "code": "FU-BERLIN", "aliases": ["FU Berlin"]},
    {"name": "Universität Stuttgart", "code": "UNI-STGT", "aliases": ["Uni Stuttgart"]},
    # Spain (5)
    {"name": "Universidad Politécnica de Madrid", "code": "UPM", "aliases": ["UPM"]},
    {"name": "Universitat Politècnica de Catalunya", "code": "UPC", "aliases": ["UPC"]},
    {"name": "Universidad de Barcelona", "code": "UB", "aliases": ["UB"]},
    {"name": "Universidad Carlos III de Madrid", "code": "UC3M", "aliases": ["UC3M"]},
    {"name": "Universidad de Sevilla", "code": "US-SEV", "aliases": ["US Sevilla"]},
    # France (4)
    {"name": "École Polytechnique", "code": "X-POLY", "aliases": ["Polytechnique"]},
    {"name": "Sorbonne Université", "code": "SORBONNE", "aliases": ["Sorbonne"]},
    {"name": "INSA Lyon", "code": "INSA-LYON", "aliases": ["INSA"]},
    {"name": "Université Paris-Saclay", "code": "PARIS-SACLAY", "aliases": ["Paris-Saclay"]},
    # Philippines (3)
    {"name": "University of the Philippines Diliman", "code": "UP-DIL", "aliases": ["UP Diliman"]},
    {"name": "Ateneo de Manila University", "code": "ADMU", "aliases": ["Ateneo"]},
    {"name": "De La Salle University", "code": "DLSU", "aliases": ["DLSU"]},
    # Vietnam (3)
    {"name": "Hanoi University of Science and Technology", "code": "HUST-HN", "aliases": ["HUST Hanoi"]},
    {"name": "Ho Chi Minh City University of Technology", "code": "HCMUT", "aliases": ["HCMUT"]},
    {"name": "Vietnam National University Hanoi", "code": "VNU", "aliases": ["VNU"]},
    # Poland (3)
    {"name": "Warsaw University of Technology", "code": "WUT", "aliases": ["WUT"]},
    {"name": "AGH University of Science and Technology", "code": "AGH", "aliases": ["AGH"]},
    {"name": "Wroclaw University of Science and Technology", "code": "WUST", "aliases": ["WUST"]},
    # Romania (2)
    {"name": "Politehnica University of Bucharest", "code": "UPB", "aliases": ["UPB"]},
    {"name": "Babeș-Bolyai University", "code": "UBB", "aliases": ["UBB"]},
    # Serbia (2)
    {"name": "University of Belgrade", "code": "UB-BEL", "aliases": ["Belgrade"]},
    {"name": "University of Novi Sad", "code": "UNS", "aliases": ["UNS"]},
    # Australia (3)
    {"name": "University of Melbourne", "code": "UMELB", "aliases": ["Melbourne"]},
    {"name": "University of Sydney", "code": "USYD", "aliases": ["Sydney"]},
    {"name": "UNSW Sydney", "code": "UNSW", "aliases": ["UNSW"]},
    # Portugal (2)
    {"name": "Universidade de Lisboa", "code": "ULISBOA", "aliases": ["ULisboa"]},
    {"name": "Universidade do Porto", "code": "UPORTO", "aliases": ["UPorto"]},
    # Brazil (3)
    {"name": "Universidade de São Paulo", "code": "USP", "aliases": ["USP"]},
    {"name": "Universidade Federal do Rio de Janeiro", "code": "UFRJ", "aliases": ["UFRJ"]},
    {"name": "Universidade Estadual de Campinas", "code": "UNICAMP", "aliases": ["Unicamp"]},
    # Bulgaria (2)
    {"name": "Sofia University", "code": "SU-SOFIA", "aliases": ["Sofia Uni"]},
    {"name": "Technical University of Sofia", "code": "TU-SOFIA", "aliases": ["TU Sofia"]},
    # Italy (3)
    {"name": "Politecnico di Milano", "code": "POLIMI", "aliases": ["PoliMi"]},
    {"name": "Sapienza Università di Roma", "code": "SAPIENZA", "aliases": ["Sapienza"]},
    {"name": "Università di Bologna", "code": "UNIBO", "aliases": ["UniBo"]},
    # Others (2)
    {"name": "Delft University of Technology", "code": "TU-DELFT", "aliases": ["TU Delft"]},
    {"name": "Technical University of Denmark", "code": "DTU", "aliases": ["DTU"]},
    # Costa Rica (1)
    {"name": "Universidad de Costa Rica", "code": "UCR", "aliases": ["UCR"]},
    # Netherlands (1)
    {"name": "Eindhoven University of Technology", "code": "TUE", "aliases": ["TU/e"]},
    # Denmark (1)
    {"name": "Aarhus University", "code": "AU-DK", "aliases": ["Aarhus"]},
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

CLIENTS: list[dict] = [
    {"name": "Telefónica",          "code": "TELEFONICA",  "aliases": []},
    {"name": "BBVA",                "code": "BBVA",        "aliases": []},
    {"name": "Siemens",             "code": "SIEMENS",     "aliases": []},
    {"name": "BMW Group",            "code": "BMW",         "aliases": ["BMW"]},
    {"name": "AXA",                 "code": "AXA",         "aliases": []},
    {"name": "BNP Paribas",         "code": "BNP",         "aliases": ["BNP"]},
    {"name": "Rolls-Royce",         "code": "RR",          "aliases": ["RR"]},
    {"name": "BP",                  "code": "BP",          "aliases": []},
    {"name": "Shell",               "code": "SHELL",       "aliases": []},
    {"name": "Unilever",            "code": "UNILEVER",    "aliases": []},
    {"name": "Deutsche Bank",       "code": "DB",          "aliases": ["DB"]},
    {"name": "Allianz",             "code": "ALLIANZ",     "aliases": []},
    {"name": "Nestlé",              "code": "NESTLE",      "aliases": []},
    {"name": "Novartis",            "code": "NOVARTIS",    "aliases": []},
    {"name": "Roche",               "code": "ROCHE",       "aliases": []},
    {"name": "Toyota Motor",        "code": "TOYOTA",      "aliases": ["Toyota"]},
    {"name": "Sony",                "code": "SONY",        "aliases": []},
    {"name": "Samsung",             "code": "SAMSUNG",     "aliases": []},
    {"name": "Infosys (subcontract)","code": "INFOSYS",    "aliases": ["Infosys"]},
    {"name": "Tata Motors",         "code": "TATA",        "aliases": ["Tata"]},
    {"name": "Reliance Industries", "code": "RELIANCE",    "aliases": ["Reliance"]},
    {"name": "Airbus",              "code": "AIRBUS",      "aliases": []},
    {"name": "Volkswagen",          "code": "VW",          "aliases": ["VW"]},
    {"name": "Bosch",               "code": "BOSCH",       "aliases": []},
    {"name": "SAP SE",              "code": "SAP-SE",      "aliases": ["SAP"]},
    {"name": "L'Oréal",             "code": "LOREAL",      "aliases": []},
    {"name": "Philips",             "code": "PHILIPS",     "aliases": []},
    {"name": "Ericsson",            "code": "ERICSSON",    "aliases": []},
    {"name": "Nokia",               "code": "NOKIA",       "aliases": []},
    {"name": "ABB",                 "code": "ABB",         "aliases": []},
    {"name": "Schneider Electric",  "code": "SCHNEIDER",   "aliases": ["Schneider"]},
    {"name": "TotalEnergies",       "code": "TOTAL",       "aliases": ["Total"]},
    {"name": "Enel",                "code": "ENEL",        "aliases": []},
    {"name": "Vodafone",            "code": "VODAFONE",    "aliases": []},
    {"name": "Commonwealth Bank",   "code": "CBA",         "aliases": ["CBA"]},
    {"name": "Petrobras",           "code": "PETROBRAS",   "aliases": []},
]

ROLES: list[dict] = [
    {"name": "Software Engineer",    "code": "SWE",          "aliases": ["Software Developer", "SWE", "Dev"]},
    {"name": "Developer",            "code": "DEV",          "aliases": ["Developer"]},
    {"name": "Consultant",           "code": "CONSULTANT",   "aliases": ["IT Consultant"]},
    {"name": "Cloud Engineer",       "code": "CLOUD-ENG",    "aliases": ["Cloud Eng"]},
    {"name": "Data Engineer",        "code": "DATA-ENG",     "aliases": ["DE", "Data Eng"]},
    {"name": "DevOps Engineer",      "code": "DEVOPS",       "aliases": ["DevOps", "SRE", "Site Reliability"]},
    {"name": "Solutions Architect",  "code": "SA",           "aliases": ["Solution Architect", "SA"]},
    {"name": "Business Analyst",     "code": "BA",           "aliases": ["BA", "Business Analysis"]},
    {"name": "Security Analyst",     "code": "SEC-ANALYST",  "aliases": ["Security", "InfoSec Analyst"]},
    {"name": "Full Stack Developer", "code": "FULLSTACK",    "aliases": ["Full Stack", "Fullstack Dev"]},
    {"name": "Backend Engineer",     "code": "BACKEND",      "aliases": ["Backend Dev"]},
    {"name": "Platform Engineer",    "code": "PLATFORM",     "aliases": ["Platform Eng"]},
    {"name": "Project Manager",      "code": "PM",           "aliases": ["PM", "Project Lead", "Delivery Manager"]},
    {"name": "Cloud Architect",      "code": "CLOUD-ARCH",   "aliases": ["Cloud Architect"]},
    {"name": "Security Consultant",  "code": "SEC-CONSULT",  "aliases": ["Security Consultant"]},
    {"name": "Lead Developer",       "code": "LEAD-DEV",     "aliases": ["Tech Lead", "Development Lead"]},
    {"name": "Lead ML Engineer",     "code": "ML-ENG",       "aliases": ["ML Engineer", "Machine Learning Engineer", "AI Engineer"]},
]

PROJECTS: list[dict] = [
    {"name": "Cloud Migration Program",       "code": "CLOUD-MIG",  "aliases": ["Cloud Migration"]},
    {"name": "SAP S/4HANA Transformation",    "code": "SAP-S4",     "aliases": ["S/4HANA"]},
    {"name": "Digital Workplace Modernization","code": "DW-MOD",     "aliases": ["Workplace Mod"]},
    {"name": "AI/ML Platform Build",          "code": "AIML-PLAT",  "aliases": ["AI Platform"]},
    {"name": "Cybersecurity Operations Center","code": "CSOC",       "aliases": ["SOC Build"]},
    {"name": "Data Lake & Analytics Platform", "code": "DLAP",       "aliases": ["Data Lake"]},
    {"name": "Salesforce CRM Implementation",  "code": "SFDC-CRM",   "aliases": ["SFDC CRM"]},
    {"name": "ServiceNow ITSM Rollout",        "code": "SNOW-ITSM",  "aliases": ["ITSM Rollout"]},
    {"name": "DevOps Pipeline Automation",     "code": "DEVOPS-PA",  "aliases": ["DevOps Pipeline"]},
    {"name": "Application Modernization",      "code": "APP-MOD",    "aliases": ["App Mod"]},
    {"name": "IoT Edge Computing Platform",    "code": "IOT-EDGE",   "aliases": ["IoT Edge"]},
    {"name": "Blockchain Supply Chain",        "code": "BLOCK-SC",   "aliases": ["Blockchain"]},
    {"name": "Managed Cloud Services",         "code": "MCS",        "aliases": ["MCS"]},
    {"name": "Network Infrastructure Refresh", "code": "NET-INFRA",  "aliases": ["Network Refresh"]},
    {"name": "ERP Consolidation",              "code": "ERP-CON",    "aliases": ["ERP"]},
    {"name": "Customer Experience Platform",   "code": "CX-PLAT",    "aliases": ["CX Platform"]},
    {"name": "Insurance Claims Automation",    "code": "INS-AUTO",   "aliases": ["Claims Auto"]},
    {"name": "Banking Digital Channels",       "code": "BANK-DC",    "aliases": ["Digital Channels"]},
    {"name": "HR Transformation Program",      "code": "HR-XFORM",   "aliases": ["HR Transform"]},
    {"name": "Sustainability Dashboard",       "code": "SUST-DASH",  "aliases": ["Sustainability"]},
    {"name": "Zero Trust Security Program",    "code": "ZT-SEC",     "aliases": ["Zero Trust"]},
    {"name": "API Gateway Modernization",      "code": "APIGW-MOD",  "aliases": ["API Gateway"]},
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
            "Role": ROLES,
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
