"""Checkpoint management for resumable data loading.

Tracks completed phases and batch progress in a JSON file so that
a crashed/interrupted load can resume from where it left off instead
of re-running completed work.

Checkpoint file: talent_synthetic_data/.load_checkpoint.json
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKPOINT_PATH = _REPO_ROOT / "talent_synthetic_data" / ".load_checkpoint.json"

# How often to flush batch progress to disk (every N batches)
_FLUSH_INTERVAL = 5

_VERSION = 1


class LoadCheckpoint:
    """Thread-safe checkpoint for resumable data loading.

    Stores per-phase status (not_started / in_progress / completed) and,
    for in-progress phases, tracks which batches have finished so we can
    skip them on restart.
    """

    def __init__(self, path: Path | None = None):
        self._path = path or CHECKPOINT_PATH
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()
        self._dirty_count = 0  # batches since last flush

    # ── Public API ────────────────────────────────────────────────

    def is_phase_done(self, phase_key: str) -> bool:
        """Return True if *phase_key* has already completed."""
        with self._lock:
            phase = self._data["phases"].get(phase_key, {})
            return phase.get("status") == "completed"

    def mark_phase_done(self, phase_key: str, count: int = 0) -> None:
        """Mark *phase_key* as completed and save immediately."""
        with self._lock:
            self._data["phases"][phase_key] = {
                "status": "completed",
                "completed_at": _now_iso(),
                "count": count,
            }
            self._flush()

    def get_completed_batches(self, phase_key: str) -> int:
        """Return the number of completed batches for an in-progress phase."""
        with self._lock:
            phase = self._data["phases"].get(phase_key, {})
            return phase.get("completed_batches", 0)

    def get_completed_batch_indices(self, phase_key: str) -> set[int]:
        """Return the set of batch indices that have completed."""
        with self._lock:
            phase = self._data["phases"].get(phase_key, {})
            return set(phase.get("completed_batch_set", []))

    def mark_batch_done(
        self, phase_key: str, batch_idx: int, total_batches: int
    ) -> None:
        """Record that *batch_idx* finished. Flushes every N batches."""
        with self._lock:
            phase = self._data["phases"].setdefault(phase_key, {
                "status": "in_progress",
                "completed_batches": 0,
                "total_batches": total_batches,
                "completed_batch_set": [],
                "completed_at": None,
            })
            phase["status"] = "in_progress"
            phase["total_batches"] = total_batches

            batch_set: list[int] = phase.setdefault("completed_batch_set", [])
            if batch_idx not in batch_set:
                batch_set.append(batch_idx)
            phase["completed_batches"] = len(batch_set)

            self._dirty_count += 1
            if self._dirty_count >= _FLUSH_INTERVAL:
                self._flush()
                self._dirty_count = 0

    def reset(self) -> None:
        """Delete the checkpoint file and reset in-memory state."""
        with self._lock:
            if self._path.exists():
                self._path.unlink()
            self._data = self._empty()
            self._dirty_count = 0

    def print_summary(self) -> None:
        """Print a human-friendly resume summary."""
        phases = self._data.get("phases", {})
        if not phases:
            print("  (no checkpoint — starting fresh)")
            return

        for key, info in phases.items():
            status = info.get("status", "not_started")
            if status == "completed":
                cnt = info.get("count", 0)
                print(f"  ✅ {key} — {cnt:,} loaded")
            elif status == "in_progress":
                done = info.get("completed_batches", 0)
                total = info.get("total_batches", "?")
                next_batch = done + 1
                print(f"  🔄 {key} — {done}/{total} batches (resuming from batch {next_batch})")
            else:
                print(f"  ⏳ {key} — not started")

    @property
    def has_progress(self) -> bool:
        """True if the checkpoint file exists with any recorded phases."""
        return bool(self._data.get("phases"))

    def flush(self) -> None:
        """Force a save to disk (public wrapper)."""
        with self._lock:
            self._flush()
            self._dirty_count = 0

    # ── Internal ──────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        """Load the checkpoint from disk, or return a fresh structure."""
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("version") == _VERSION:
                    return data
            except (json.JSONDecodeError, KeyError):
                pass
        return self._empty()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": _VERSION,
            "started_at": _now_iso(),
            "phases": {},
        }

    def _flush(self) -> None:
        """Atomically write checkpoint to disk (write tmp → rename)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            # Atomic rename (Windows: os.replace handles overwrite)
            os.replace(tmp, str(self._path))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
