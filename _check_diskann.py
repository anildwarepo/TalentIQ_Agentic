"""One-shot diagnostic: which vector extensions + indexes are live."""
import os
import psycopg2

c = psycopg2.connect(
    host=os.environ["PGHOST"],
    port=5432,
    dbname="postgres",
    user="tiqadmin",
    password=os.environ["PGPASSWORD"],
    sslmode="require",
)
cur = c.cursor()

cur.execute(
    "SELECT extname, extversion FROM pg_extension "
    "WHERE extname IN ('pg_diskann','vectorscale','vector','age') ORDER BY extname"
)
print("EXTENSIONS:")
for r in cur.fetchall():
    print(f"  {r[0]:15} {r[1]}")

cur.execute("SELECT to_regclass('public.employee_embeddings') IS NOT NULL")
print(f"\ntable employee_embeddings exists: {cur.fetchone()[0]}")

cur.execute(
    "SELECT indexname, indexdef FROM pg_indexes "
    "WHERE tablename = 'employee_embeddings' ORDER BY indexname"
)
rows = cur.fetchall()
print(f"\nINDEXES on employee_embeddings ({len(rows)}):")
for name, ddl in rows:
    print(f"  {name}")
    print(f"    {ddl}")

cur.execute("SELECT count(*) FROM employee_embeddings")
print(f"\nemployee_embeddings row count: {cur.fetchone()[0]:,}")

# Show planner choice for a fake vector query
cur.execute(
    "EXPLAIN (FORMAT TEXT) "
    "SELECT workday_id FROM employee_embeddings "
    "WHERE resume_embedding IS NOT NULL "
    "ORDER BY resume_embedding <=> "
    "(SELECT resume_embedding FROM employee_embeddings WHERE resume_embedding IS NOT NULL LIMIT 1) "
    "LIMIT 5"
)
print("\nPLAN for vector KNN:")
for r in cur.fetchall():
    print(f"  {r[0]}")
