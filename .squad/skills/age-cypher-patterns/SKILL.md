# Apache AGE Cypher Query Patterns

## Critical Rules

### WITH Destroys Property Access
After `WITH` with aggregation, node property access breaks:
```
❌ WITH e, l, c, collect(s.name) AS skills ORDER BY e.years_of_experience DESC
✅ WITH e.name AS name, e.years_of_experience AS yoe, collect(s.name) AS skills ORDER BY yoe DESC
```

### OPTIONAL MATCH Cartesian Products
Multiple OPTIONAL MATCH without WITH between them → cartesian products:
```
❌ OPTIONAL MATCH (e)-[]->(cert) OPTIONAL MATCH (e)-[]->(lang) → duplicates
✅ OPTIONAL MATCH ... WITH ... OPTIONAL MATCH ... WITH ... (3-WITH chain)
```

### 3-WITH Chain Pattern (for skills + certs + langs)
1. First WITH: collect skills, extract employee properties
2. Second WITH: collect certs (after OPTIONAL MATCH for certs)
3. Third WITH: extract all scalar properties, collect langs (after OPTIONAL MATCH for langs)

### Unsupported Functions
`toLower()`, `toUpper()`, `toString()`, `split()`, `trim()`, `CONTAINS`, `STARTS WITH`, `CALL {}`, `EXISTS {}`

### psycopg3 Placeholders
Use `%s` (not `$1`/`$2` which are PostgreSQL-native). Must pass embedding string twice when it appears in both SELECT and ORDER BY.

## Confidence: high
