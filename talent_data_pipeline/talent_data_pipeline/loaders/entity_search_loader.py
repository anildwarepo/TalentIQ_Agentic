"""Populate entity_search table with all reference/dimension entities for unified search."""

from __future__ import annotations

from typing import Any

from tqdm import tqdm

from talent_data_pipeline.generators.reference_data import (
    CERTIFICATIONS,
    CLIENTS,
    COUNTRIES,
    LANGUAGES,
    OFFERINGS,
    PROJECTS,
    ROLES,
    SERVICE_LINES,
    SKILL_DOMAINS,
    UNIVERSITIES,
    ALL_SKILLS,
)
from talent_data_pipeline.generators.embedding_generator import EmbeddingGenerator
from talent_data_pipeline.loaders.base_loader import BaseLoader


# Map entity type label → (data list, has_code, has_aliases)
ENTITY_SOURCES: list[tuple[str, list[dict[str, Any]]]] = [
    ("Certification", CERTIFICATIONS),
    ("Skill",         ALL_SKILLS),
    ("SkillDomain",   SKILL_DOMAINS),
    ("Country",       COUNTRIES),
    ("Language",      LANGUAGES),
    ("ServiceLine",   SERVICE_LINES),
    ("Offering",      OFFERINGS),
    ("University",    UNIVERSITIES),
    ("Client",        CLIENTS),
    ("Project",       PROJECTS),
    ("Role",          ROLES),
]


class EntitySearchLoader(BaseLoader):
    """Upsert all reference entities into the entity_search table."""

    def load_entity_search(self) -> None:
        """Populate entity_search with FTS-ready records. Idempotent via UPSERT."""
        total = sum(len(data) for _, data in ENTITY_SOURCES)
        print(f"Loading {total:,} entity_search records...")

        with self.get_conn() as conn:
            cur = conn.cursor()
            for entity_type, entities in ENTITY_SOURCES:
                for entity in tqdm(entities, desc=f"  {entity_type}", disable=len(entities) < 20):
                    name = entity["name"]
                    code = entity.get("code", "")
                    aliases = entity.get("aliases", [])
                    aliases_text = ", ".join(aliases) if aliases else ""

                    # Build composite search text
                    search_text = " ".join(filter(None, [name, code, aliases_text]))

                    self.execute_with_retry(
                        conn,
                        cur,
                        """
                        INSERT INTO entity_search
                            (entity_type, name, code, aliases, search_text, fts_vector, updated_at)
                        VALUES
                            (%s, %s, %s, %s, %s,
                             to_tsvector('english', %s), NOW())
                        ON CONFLICT (entity_type, name) DO UPDATE SET
                            code = EXCLUDED.code,
                            aliases = EXCLUDED.aliases,
                            search_text = EXCLUDED.search_text,
                            fts_vector = EXCLUDED.fts_vector,
                            updated_at = NOW();
                        """,
                        (entity_type, name, code, aliases_text, search_text, search_text),
                    )
                conn.commit()

        print("Entity search load complete.")

    def embed_entities(self, batch_size: int = 16) -> None:
        """Generate and store vector embeddings for all entity_search records.

        Uses the same Azure OpenAI embedding model as employee embeddings.
        Skips entities that already have embeddings (idempotent).
        """
        emb_gen = EmbeddingGenerator()
        emb_gen._load_client()

        with self.get_conn() as conn:
            cur = conn.cursor()

            # Fetch entities without embeddings
            self.execute_with_retry(
                conn, cur,
                "SELECT id, search_text FROM entity_search "
                "WHERE embedding IS NULL ORDER BY id",
            )
            rows = cur.fetchall()

            if not rows:
                print("All entities already have embeddings — nothing to do.")
                return

            print(f"Generating embeddings for {len(rows)} entities...")

            for i in tqdm(range(0, len(rows), batch_size), desc="  Embedding"):
                batch = rows[i : i + batch_size]
                texts = [r[1] for r in batch]
                ids = [r[0] for r in batch]

                vecs = emb_gen._encode_batch(texts)

                for j, vec in enumerate(vecs):
                    self.execute_with_retry(
                        conn, cur,
                        "UPDATE entity_search SET embedding = %s, updated_at = NOW() "
                        "WHERE id = %s",
                        (str(vec.tolist()), ids[j]),
                    )
                conn.commit()

        print("Entity embedding generation complete.")
