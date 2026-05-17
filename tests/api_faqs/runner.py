"""REST API wrapper that runs FAQ test cases against the TalentIQ backend.

Posts each FAQ to ``POST /af/graph/responses`` (NDJSON streaming endpoint),
parses the stream for [QUERY] / [RESULT] / [HANDOFF] events, and writes
per-FAQ + per-category result files.

Usage
-----
    # 1. Make sure backend + MCP are running (`python run_all.py`)
    # 2. Acquire a bearer token (one of):
    #      a) az login   (the runner will fall back to `az account get-access-token`)
    #      b) export TEST_BEARER_TOKEN=<jwt>
    # 3. Run a single category:
    #      python -m tests.api_faqs.runner --category cypher
    #    Or all categories:
    #      python -m tests.api_faqs.runner --all
    #    Optional:
    #      --concurrency 1     (sequential; bump to fan out)
    #      --timeout 120       (per-FAQ seconds)
    #      --backend http://localhost:8000

Outputs land in ``tests/api_faqs/results/<category>/<NN>_<slug>.json`` plus
a ``_summary.json`` per category.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND = os.getenv("TEST_BACKEND_URL", "http://localhost:8000")
DEFAULT_AUDIENCE = os.getenv("AZURE_TOKEN_AUDIENCE", "https://ai.azure.com")

CATEGORIES = ("cypher", "vector", "fts", "hybrid")


def _category_dir(category: str) -> Path:
    return ROOT / category


def _faq_path(category: str) -> Path:
    return _category_dir(category) / "faqs.json"


def _results_dir(category: str) -> Path:
    return _category_dir(category) / "results"


# ── auth ────────────────────────────────────────────────────

def _get_bearer_token() -> str | None:
    """Return a bearer token from env or `az account get-access-token`.

    Returns None if neither path produces a token; the caller may then
    proceed unauthenticated (works only when the backend is in dev mode
    with AZURE_TENANT_ID unset).
    """
    token = os.getenv("TEST_BEARER_TOKEN")
    if token:
        return token.strip()

    audience = os.getenv("TEST_TOKEN_RESOURCE", DEFAULT_AUDIENCE)
    try:
        completed = subprocess.run(
            ["az", "account", "get-access-token", "--resource", audience, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=(os.name == "nt"),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as ex:
        print(f"[auth] az CLI unavailable ({ex}); proceeding without bearer token")
        return None

    if completed.returncode != 0:
        print(f"[auth] az get-access-token failed: {completed.stderr.strip()[:200]}")
        return None

    try:
        return json.loads(completed.stdout)["accessToken"]
    except (KeyError, json.JSONDecodeError) as ex:
        print(f"[auth] could not parse az output: {ex}")
        return None


# ── parsing ─────────────────────────────────────────────────

_QUERY_RE = re.compile(r"\[QUERY\]\s*(CYPHER|SQL|FTS|VECTOR|STATS)\b", re.IGNORECASE)
_RESULT_RE = re.compile(r"\[RESULT\]\s*(\w+)\s+returned\s+(\d+)\s+rows?\s*\((\d+)ms\)", re.IGNORECASE)
_HANDOFF_RE = re.compile(r"\[HANDOFF\][^\w]*(?:→\s*)?(.+?)(?:\s+completed)?$", re.IGNORECASE)


def _parse_event(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        outer = json.loads(line)
    except json.JSONDecodeError:
        return None
    return outer.get("response_message") or outer


# ── runner ──────────────────────────────────────────────────

async def _run_one(
    client: httpx.AsyncClient,
    backend: str,
    token: str | None,
    question: str,
    timeout: float,
) -> dict[str, Any]:
    """Post one FAQ and return a structured result dict."""
    url = f"{backend.rstrip('/')}/af/graph/responses"
    headers = {"Accept": "application/x-ndjson", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = {"input": question, "session_id": uuid.uuid4().hex[:16]}

    queries: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    handoffs: list[str] = []
    other_events: list[str] = []
    final_text = ""
    error: str | None = None

    started = time.perf_counter()
    started_iso = datetime.now(timezone.utc).isoformat()

    try:
        async with client.stream("POST", url, json=body, headers=headers, timeout=timeout) as resp:
            if resp.status_code >= 400:
                error_body = (await resp.aread()).decode("utf-8", "replace")[:500]
                error = f"HTTP {resp.status_code}: {error_body}"
            else:
                async for line in resp.aiter_lines():
                    msg = _parse_event(line)
                    if not msg:
                        continue
                    mtype = msg.get("type")
                    delta = msg.get("delta") or ""

                    if mtype == "WorkflowOutputEvent":
                        final_text = delta
                    elif mtype == "AgentEvent":
                        m = _QUERY_RE.search(delta)
                        if m:
                            queries.append({"strategy": m.group(1).upper(), "raw": delta})
                            continue
                        m = _RESULT_RE.search(delta)
                        if m:
                            results.append({
                                "strategy": m.group(1).upper(),
                                "rows": int(m.group(2)),
                                "latency_ms": int(m.group(3)),
                                "raw": delta,
                            })
                            continue
                        m = _HANDOFF_RE.search(delta)
                        if m:
                            handoffs.append(m.group(1).strip())
                            continue
                        other_events.append(delta)
                    elif mtype == "OrchestratorEvent":
                        other_events.append(delta)
                    elif mtype == "error":
                        error = msg.get("message", "unknown error")
                    elif mtype == "done":
                        if not final_text:
                            final_text = msg.get("result", "") or ""
    except (httpx.HTTPError, asyncio.TimeoutError) as ex:
        error = f"{type(ex).__name__}: {ex}"

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return {
        "question": question,
        "started_at": started_iso,
        "elapsed_ms": elapsed_ms,
        "error": error,
        "strategies_invoked": sorted({q["strategy"] for q in queries}),
        "queries": queries,
        "results": results,
        "handoffs": handoffs,
        "rows_total": sum(r["rows"] for r in results),
        "final_answer": final_text,
        "other_events": other_events[:50],
    }


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s[:max_len] or "faq"


async def _run_category(
    backend: str,
    token: str | None,
    category: str,
    concurrency: int,
    timeout: float,
) -> dict[str, Any]:
    faq_path = _faq_path(category)
    if not faq_path.exists():
        raise FileNotFoundError(f"No FAQ file for category '{category}': {faq_path}")
    payload = json.loads(faq_path.read_text(encoding="utf-8"))
    faqs: list[str] = payload["faqs"]

    out_dir = _results_dir(category)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {category.upper()} ({len(faqs)} FAQs, concurrency={concurrency}) ===")

    sem = asyncio.Semaphore(concurrency)
    results: list[dict[str, Any]] = [None] * len(faqs)  # type: ignore

    async with httpx.AsyncClient() as client:
        async def _worker(idx: int, q: str):
            async with sem:
                t0 = time.perf_counter()
                print(f"  [{idx+1:02d}/{len(faqs)}] {q[:80]}")
                res = await _run_one(client, backend, token, q, timeout)
                results[idx] = res
                # Persist immediately so a crash doesn't lose data
                fname = f"{idx+1:02d}_{_slug(q)}.json"
                (out_dir / fname).write_text(
                    json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                tag = "OK" if not res["error"] else "ERR"
                strat = ",".join(res["strategies_invoked"]) or "-"
                print(
                    f"       {tag} {res['elapsed_ms']:>5}ms  "
                    f"strategies={strat}  rows={res['rows_total']}"
                    f"{('  ' + res['error']) if res['error'] else ''}"
                )

            return time.perf_counter() - t0

        await asyncio.gather(*[_worker(i, q) for i, q in enumerate(faqs)])

    summary = {
        "category": category,
        "description": payload.get("description", ""),
        "backend": backend,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "errors": sum(1 for r in results if r["error"]),
        "avg_elapsed_ms": int(sum(r["elapsed_ms"] for r in results) / max(len(results), 1)),
        "strategy_counts": _strategy_counts(results),
        "faqs": [
            {
                "question": r["question"],
                "elapsed_ms": r["elapsed_ms"],
                "strategies_invoked": r["strategies_invoked"],
                "rows_total": r["rows_total"],
                "error": r["error"],
            }
            for r in results
        ],
    }
    (out_dir / "_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  -> {summary['total']} runs, {summary['errors']} errors, "
        f"avg {summary['avg_elapsed_ms']}ms, strategies={summary['strategy_counts']}"
    )
    return summary


def _strategy_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        for s in r["strategies_invoked"]:
            counts[s] = counts.get(s, 0) + 1
    return dict(sorted(counts.items()))


# ── CLI ─────────────────────────────────────────────────────

async def _amain() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--category", choices=CATEGORIES, help="Run a single category")
    g.add_argument("--all", action="store_true", help="Run every category")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend base URL (default: {DEFAULT_BACKEND})")
    parser.add_argument("--concurrency", type=int, default=1, help="Parallel FAQs per category (default: 1)")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-FAQ seconds (default: 120)")
    args = parser.parse_args()

    token = _get_bearer_token()
    if token:
        print(f"[auth] using bearer token (len={len(token)})")
    else:
        print("[auth] no bearer token — backend must be in dev mode (AZURE_TENANT_ID unset)")

    cats = list(CATEGORIES) if args.all else [args.category]
    summaries: list[dict[str, Any]] = []
    for cat in cats:
        summaries.append(await _run_category(args.backend, token, cat, args.concurrency, args.timeout))

    if args.all:
        roll = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "backend": args.backend,
            "categories": summaries,
        }
        overall = ROOT / "_overall.json"
        overall.write_text(
            json.dumps(roll, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nWrote overall summary -> {overall}")

    return 0 if all(s["errors"] == 0 for s in summaries) else 1


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
