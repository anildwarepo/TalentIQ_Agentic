"""Generate realistic resume summaries for full-text search and vectorization."""

from __future__ import annotations

from typing import Any

from talent_data_pipeline.generators.base import BaseGenerator


class ResumeGenerator(BaseGenerator):
    """Generate free-text resume summaries per employee profile."""

    # Template fragments — combined to produce varied, realistic summaries
    _INTRO_TEMPLATES = [
        "Experienced {skill_level} {domain} professional with {yoe} years in enterprise IT consulting.",
        "{skill_level}-level {domain} specialist with {yoe}+ years of hands-on experience at DXC Technology.",
        "Results-driven {domain} {title} with {yoe} years delivering mission-critical solutions.",
        "Passionate {skill_level} {domain} practitioner with {yoe} years building scalable systems.",
        "Dedicated {domain} {title} bringing {yoe} years of cross-industry consulting expertise.",
    ]

    _DOMAIN_DETAILS: dict[str, list[str]] = {
        "Python": [
            "Proficient in Python-based microservices using Django and FastAPI.",
            "Built high-throughput data pipelines with Pandas, NumPy, and Celery.",
            "Designed RESTful APIs and event-driven architectures in Python.",
        ],
        "Java": [
            "Extensive experience with Spring Boot microservices and Kafka-based event streaming.",
            "Delivered enterprise-grade applications using Java, Hibernate, and Maven.",
            "Led migration of monolithic Java applications to containerized microservices.",
        ],
        "C#/.NET": [
            "Expert in .NET Core, ASP.NET, and Entity Framework for enterprise web applications.",
            "Built cloud-native applications on Azure using C# and Azure Functions.",
            "Developed WPF desktop applications and Blazor front-ends for LOB systems.",
        ],
        "JavaScript/TS": [
            "Full-stack JavaScript/TypeScript developer with React and Node.js expertise.",
            "Built modern single-page applications with Angular and Next.js.",
            "Implemented real-time collaborative features using WebSockets and Vue.js.",
        ],
        "Cloud (Azure)": [
            "Azure-certified architect with deep experience in AKS, Azure DevOps, and ARM/Bicep.",
            "Led cloud migration programs moving workloads from on-premises to Azure.",
            "Designed multi-region, highly available Azure architectures for global clients.",
        ],
        "Cloud (AWS)": [
            "AWS-certified with hands-on experience in Lambda, EKS, and CloudFormation.",
            "Architected serverless solutions using API Gateway, SQS, and DynamoDB.",
            "Managed large-scale EC2 fleets with auto-scaling and cost optimization.",
        ],
        "DevOps/SRE": [
            "DevOps engineer specializing in CI/CD pipelines, Docker, and Kubernetes.",
            "Implemented infrastructure-as-code using Terraform and Ansible across hybrid environments.",
            "Built observability stacks with Prometheus, Grafana, and ELK for SRE teams.",
        ],
        "Data Engineering": [
            "Data engineer with expertise in Apache Spark, Databricks, and Snowflake.",
            "Designed end-to-end ETL/ELT pipelines using Airflow and dbt.",
            "Built real-time streaming architectures with Kafka and event-driven data platforms.",
        ],
        "AI/ML": [
            "Machine learning engineer with production experience in TensorFlow and PyTorch.",
            "Developed NLP models and deployed LLM-based applications with LangChain.",
            "Built computer vision pipelines and MLOps workflows using MLflow.",
        ],
        "SAP": [
            "SAP consultant with deep expertise in S/4HANA, BTP, and Fiori development.",
            "Led SAP ABAP modernization projects and integration suite implementations.",
            "Configured SAP SuccessFactors and Analytics Cloud for HR transformation.",
        ],
        "Salesforce": [
            "Certified Salesforce developer experienced in Apex, LWC, and CPQ.",
            "Implemented end-to-end CRM solutions with Marketing Cloud and MuleSoft integrations.",
            "Built custom Salesforce apps with Lightning Web Components and Tableau CRM.",
        ],
        "Cybersecurity": [
            "Cybersecurity analyst with SIEM, SOC operations, and incident response expertise.",
            "Implemented Zero Trust architectures and Identity & Access Management solutions.",
            "Conducted penetration testing and threat intelligence for enterprise clients.",
        ],
        "ServiceNow": [
            "ServiceNow developer and administrator with ITSM and ITOM experience.",
            "Built custom applications using ServiceNow App Engine and Flow Designer.",
            "Implemented ServiceNow SecOps and CSM modules for global enterprises.",
        ],
    }

    _CLOSING_TEMPLATES = [
        "Strong communicator with experience leading distributed teams across multiple time zones.",
        "Proven track record of delivering on time and within budget for Fortune 500 clients.",
        "Committed to continuous learning and staying current with emerging technologies.",
        "Experienced in Agile/Scrum methodologies with a focus on quality and stakeholder collaboration.",
        "Track record of mentoring junior engineers and building high-performing teams.",
    ]

    def generate_summaries(self, employees: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add resume_summary to each employee dict. Modifies in place and returns the list."""
        for emp in employees:
            domain = emp.get("_domain", "Python")
            intro = self.rng.choice(self._INTRO_TEMPLATES).format(
                skill_level=emp["skill_level"],
                domain=domain,
                yoe=emp["years_of_experience"],
                title=emp["job_title"],
            )

            details = self._DOMAIN_DETAILS.get(domain, self._DOMAIN_DETAILS["Python"])
            detail = self.rng.choice(details)
            closing = self.rng.choice(self._CLOSING_TEMPLATES)

            emp["resume_summary"] = f"{intro} {detail} {closing}"

        return employees
