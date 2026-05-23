"""Generate vector embeddings for resume summaries and skill combinations."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from tqdm import tqdm

from talent_data_pipeline.config import pipeline_config

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_EMBEDDING_CHECKPOINT_DIR = _REPO_ROOT / "talent_synthetic_data" / ".embedding_gen_checkpoint"


class EmbeddingGenerator:
    """Generate embeddings using Azure OpenAI (or synthetic fallback)."""

    def __init__(self):
        self.dim = pipeline_config.embedding_dim
        self._client = None
        self._deployment = pipeline_config.azure_openai_embedding_deployment

    # ── Checkpoint helpers ────────────────────────────────────────

    @staticmethod
    def clear_checkpoint() -> None:
        """Remove the embedding generation checkpoint directory."""
        if _EMBEDDING_CHECKPOINT_DIR.exists():
            shutil.rmtree(_EMBEDDING_CHECKPOINT_DIR)

    @staticmethod
    def _batch_path(batch_idx: int) -> Path:
        return _EMBEDDING_CHECKPOINT_DIR / f"batch_{batch_idx:06d}.npz"

    def _save_batch(
        self,
        batch_idx: int,
        workday_ids: list[str],
        resume_vecs: np.ndarray,
        skills_vecs: np.ndarray,
    ) -> None:
        """Save a completed batch of embeddings to disk (atomic write)."""
        _EMBEDDING_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        path = self._batch_path(batch_idx)
        fd, tmp = tempfile.mkstemp(
            dir=str(_EMBEDDING_CHECKPOINT_DIR), suffix=".npz"
        )
        try:
            os.close(fd)
            np.savez(
                tmp,
                workday_ids=np.array(workday_ids),
                resume_embeddings=resume_vecs,
                skills_embeddings=skills_vecs,
            )
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _load_batch(batch_idx: int) -> list[dict[str, Any]] | None:
        """Load a saved batch from disk. Returns None if missing or corrupt."""
        path = _EMBEDDING_CHECKPOINT_DIR / f"batch_{batch_idx:06d}.npz"
        if not path.exists():
            return None
        try:
            data = np.load(path, allow_pickle=False)
            wids = data["workday_ids"]
            resume = data["resume_embeddings"]
            skills = data["skills_embeddings"]
            return [
                {
                    "workday_id": str(wids[i]),
                    "resume_embedding": resume[i].tolist(),
                    "skills_embedding": skills[i].tolist(),
                }
                for i in range(len(wids))
            ]
        except Exception:
            # Corrupt file — remove so the batch is re-generated
            try:
                path.unlink()
            except OSError:
                pass
            return None

    # ── Client / encoding ─────────────────────────────────────────

    def _load_client(self):
        """Lazy-load the Azure OpenAI client with DefaultAzureCredential."""
        if self._client is not None:
            return
        try:
            from openai import AzureOpenAI
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            endpoint = pipeline_config.azure_openai_endpoint.strip().rstrip("/")
            if not endpoint.startswith(("https://", "http://")):
                raise ValueError(
                    "AZURE_OPENAI_ENDPOINT must include http:// or https://. "
                    f"Loaded value: {pipeline_config.azure_openai_endpoint!r}"
                )
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._client = AzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-06-01",
                timeout=120.0,
                max_retries=5,
            )
            print(f"Azure OpenAI client ready — deployment: {self._deployment}, dim: {self.dim}")
        except Exception as exc:
            print(f"WARNING: Could not initialize Azure OpenAI client: {exc}")
            print("Falling back to deterministic synthetic embeddings.")
            self._client = "synthetic"

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        """Encode a batch of texts to embeddings via Azure OpenAI."""
        if self._client == "synthetic" or self._client is None:
            vecs = []
            for t in texts:
                seed = hash(t) % (2**31)
                r = np.random.default_rng(seed)
                v = r.standard_normal(self.dim).astype(np.float32)
                v /= np.linalg.norm(v)
                vecs.append(v)
            return np.array(vecs)

        # Call Azure OpenAI embeddings API with retry
        for attempt in range(3):
            try:
                # ada-002 doesn't support dimensions param; only embedding-3-* models do
                kwargs: dict[str, Any] = {
                    "input": texts,
                    "model": self._deployment,
                }
                if "embedding-3" in self._deployment:
                    kwargs["dimensions"] = self.dim

                response = self._client.embeddings.create(**kwargs)
                vecs = [item.embedding for item in response.data]
                return np.array(vecs, dtype=np.float32)
            except Exception as exc:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"  Embedding API error (retry {attempt + 1}/3 in {wait}s): {exc}")
                    time.sleep(wait)
                else:
                    print(f"  Embedding API failed after 3 retries: {exc}")
                    raise

    def generate_embeddings(
        self,
        employees: list[dict[str, Any]],
        skill_edges: list[dict[str, Any]],
        batch_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Generate resume and skills embeddings with batch-level checkpointing.

        Completed batches are saved to disk so that a crashed/interrupted run
        can resume without re-calling the Azure OpenAI API for finished batches.

        Returns a flat list of dicts with workday_id, resume_embedding,
        skills_embedding (legacy interface). Streaming callers should use
        :meth:`iter_embedding_batches` directly.
        """
        return [
            rec
            for batch in self.iter_embedding_batches(employees, skill_edges, batch_size)
            for rec in batch
        ]

    def iter_embedding_batches(
        self,
        employees: list[dict[str, Any]],
        skill_edges: list[dict[str, Any]],
        batch_size: int = 100,
    ):
        """Yield embedding dicts one batch at a time (streaming).

        Each yielded item is a list[dict] for one batch. Batches are loaded
        from checkpoint cache when available, or generated via Azure OpenAI.
        """
        self._load_client()

        # Build skills text per employee
        emp_skills: dict[str, list[str]] = {}
        for edge in skill_edges:
            wid = edge["from_key"][1]
            skill_name = edge["to_key"][1]
            emp_skills.setdefault(wid, []).append(skill_name)

        total_batches = -(-len(employees) // batch_size)  # ceil division

        # Scan for cached batches from a previous interrupted run
        cached_indices: set[int] = set()
        for batch_idx in range(total_batches):
            if self._batch_path(batch_idx).exists():
                cached_indices.add(batch_idx)

        if cached_indices:
            new_batches = total_batches - len(cached_indices)
            print(
                f"  Checkpoint: {len(cached_indices)}/{total_batches} batches cached — "
                f"skipping ~{len(cached_indices) * 2:,} API calls, "
                f"{new_batches} batches remaining"
            )

        for batch_idx in tqdm(range(total_batches), desc="Embeddings"):
            # Try loading from checkpoint
            if batch_idx in cached_indices:
                cached = self._load_batch(batch_idx)
                if cached is not None:
                    yield cached
                    continue
                # Corrupt file was removed by _load_batch — re-generate

            i = batch_idx * batch_size
            batch = employees[i : i + batch_size]

            resume_texts = [emp.get("resume_summary", "") or emp["job_title"] for emp in batch]
            resume_vecs = self._encode_batch(resume_texts)

            skills_texts = [
                ", ".join(emp_skills.get(emp["workday_id"], [emp.get("_domain", "")]))
                for emp in batch
            ]
            skills_vecs = self._encode_batch(skills_texts)

            # Save batch to checkpoint before building result dicts
            wids = [emp["workday_id"] for emp in batch]
            self._save_batch(batch_idx, wids, resume_vecs, skills_vecs)

            batch_results = []
            for j, emp in enumerate(batch):
                batch_results.append({
                    "workday_id": emp["workday_id"],
                    "resume_embedding": resume_vecs[j].tolist(),
                    "skills_embedding": skills_vecs[j].tolist(),
                })
            yield batch_results
