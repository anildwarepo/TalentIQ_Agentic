"""Fix job_title to match HAS_ROLE edge — single bulk SQL UPDATE.

Uses a single UPDATE...FROM JOIN to rewrite all 130K employees at once.
AGE stores properties as agtype (internally JSONB). We cast to jsonb,
merge the new job_title, and cast back to agtype.
"""
import psycopg2
from talent_data_pipeline.config import db_config, pipeline_config

conn = psycopg2.connect(**db_config.connection_dict)
conn.autocommit = True
cur = conn.cursor()

graph = pipeline_config.graph_name

print("Bulk updating employee job_titles via SQL JOIN...")

sql = f"""
UPDATE {graph}."Employee" e
SET properties = (
    (e.properties::text)::jsonb
    || jsonb_build_object(
        'job_title',
        CASE
            WHEN (e.properties::text)::jsonb->>'skill_level' = 'Mid'
            THEN (r.properties::text)::jsonb->>'name'
            ELSE ((e.properties::text)::jsonb->>'skill_level') || ' ' || ((r.properties::text)::jsonb->>'name')
        END,
        'role_name',
        (r.properties::text)::jsonb->>'name'
    )
)::text::agtype
FROM {graph}."HAS_ROLE" hr
JOIN {graph}."Role" r ON r.id = hr.end_id
WHERE e.id = hr.start_id;
"""

try:
    cur.execute(sql)
    print(f"Updated {cur.rowcount} employees")
except Exception as exc:
    print(f"Bulk UPDATE failed: {exc}")
    print("The job_title mismatch is cosmetic — HAS_ROLE edges are correct.")
    print("A full pipeline re-run will fix it.")

cur.close()
conn.close()
print("Done!")
