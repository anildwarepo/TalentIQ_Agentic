# API FAQ test runner

Runs the chat FAQs surfaced in the UI sidebar against the backend's
streaming endpoint (`POST /af/graph/responses`) and captures, per FAQ:

- which retrieval strategies fired (`CYPHER`, `VECTOR`, `FTS`, `SQL`, `STATS`)
- agent handoffs
- row counts and per-tool latency reported by the MCP server
- final assistant answer
- end-to-end wall-clock latency

The FAQs are split into four buckets matching the retrieval pattern they
*should* trigger; a run that ends up using a different strategy is still
captured (in `strategies_invoked`) so you can spot regressions in the
agent's tool selection.

## Layout

```
tests/api_faqs/
├── cypher/
│   ├── faqs.json            # input FAQs for this category
│   └── results/
│       ├── 01_<slug>.json   # per-FAQ capture
│       └── _summary.json    # rolled-up category summary
├── vector/   (same shape)
├── fts/      (same shape)
├── hybrid/   (same shape)
├── _overall.json            # written when --all is used
└── runner.py
```

## Prereqs

1. Backend + MCP server running locally (`python run_all.py`).
2. A bearer token, supplied either via:
   - `TEST_BEARER_TOKEN=<jwt>` env var, **or**
   - `az login` — the runner falls back to
     `az account get-access-token --resource $AZURE_TOKEN_AUDIENCE`
     (defaults to `https://ai.azure.com`).

If the backend is in dev mode (`AZURE_TENANT_ID` unset) you can run with
no token.

## Usage

```pwsh
# single category
python -m tests.api_faqs.runner --category cypher

# everything (writes results/_overall.json)
python -m tests.api_faqs.runner --all

# fan out (careful: each FAQ holds a backend stream open)
python -m tests.api_faqs.runner --category fts --concurrency 3 --timeout 90
```

Exit code is non-zero if any FAQ errored.

## Adding / re-bucketing FAQs

Edit the relevant `faqs/<category>.json` — it's just a list of strings.
Outputs are regenerated on the next run; old per-FAQ files are
overwritten (no automatic cleanup).
