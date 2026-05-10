"""Base generator with common utilities for all data generators."""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from talent_data_pipeline.config import pipeline_config


class BaseGenerator:
    """Shared utilities for data generation."""

    def __init__(self, seed: int | None = None):
        self.seed = seed or pipeline_config.random_seed
        self.rng = random.Random(self.seed)
        self.np_rng = np.random.default_rng(self.seed)

    def weighted_choice(self, options: list[Any], weights: list[float]) -> Any:
        """Pick one item using weighted probabilities."""
        return self.rng.choices(options, weights=weights, k=1)[0]

    def weighted_sample(self, options: list[Any], weights: list[float], k: int) -> list[Any]:
        """Sample k items without replacement using weights."""
        if k >= len(options):
            return list(options)
        chosen: list[Any] = []
        pool = list(zip(options, weights))
        for _ in range(k):
            total = sum(w for _, w in pool)
            if total == 0:
                break
            probs = [w / total for _, w in pool]
            idx = self.np_rng.choice(len(pool), p=probs)
            chosen.append(pool[idx][0])
            pool.pop(idx)
        return chosen

    def normal_int(self, mean: float, std: float, lo: int, hi: int) -> int:
        """Generate a normally-distributed integer clamped to [lo, hi]."""
        return int(np.clip(round(self.np_rng.normal(mean, std)), lo, hi))

    def date_between(self, start_year: int, end_year: int) -> str:
        """Generate a random ISO date between two years."""
        y = self.rng.randint(start_year, end_year)
        m = self.rng.randint(1, 12)
        d = self.rng.randint(1, 28)  # safe for all months
        return f"{y:04d}-{m:02d}-{d:02d}"

    def generate_email(self, first: str, last: str, existing: set[str]) -> str:
        """Generate a unique DXC email address."""
        base = f"{first.lower()}.{last.lower()}".replace(" ", "").replace("'", "")
        # Strip accents for email
        import unicodedata
        base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
        email = f"{base}@dxc.com"
        counter = 2
        while email in existing:
            email = f"{base}{counter}@dxc.com"
            counter += 1
        existing.add(email)
        return email

    def batched(self, iterable: list[Any], n: int):
        """Yield successive n-sized chunks from iterable."""
        for i in range(0, len(iterable), n):
            yield iterable[i : i + n]
