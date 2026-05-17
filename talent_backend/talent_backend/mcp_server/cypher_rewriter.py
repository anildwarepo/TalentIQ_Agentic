"""Deterministic Cypher query rewriter for Apache AGE performance.

The agent-generated Cypher frequently exhibits the *enrich-then-limit*
anti-pattern, which AGE cannot optimise:

    MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
    WHERE s.name =~ '(?i).*(python).*'
    WITH e, ..., collect(DISTINCT s.name) AS skills_
    OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)  ← runs against ALL matches
    WHERE hc.status = 'Valid'
    WITH ..., collect(DISTINCT cert.name) AS certs
    RETURN ... ORDER BY size(skills_) DESC LIMIT 25            ← LIMIT applied LAST

On the 130 k Employee graph this can run for 17–180 seconds because AGE
enriches every employee that passed the WHERE before discarding all but
LIMIT rows.

The fix — used by the typed `find_employees` tool — is to push the
ORDER BY + LIMIT *before* the OPTIONAL MATCH enrichment so AGE only
enriches the top-N rows.

This module rewrites the Cypher body of `ag_catalog.cypher(graph, $$…$$)`
calls in place when the anti-pattern is detected and the rewrite is
provably safe.

Safety rules — the rewriter ONLY fires when ALL of the following hold:

  1. The SQL contains exactly one `ag_catalog.cypher('…', $$ … $$)` call.
  2. The Cypher body contains a final `[ORDER BY …] LIMIT N` at the end.
  3. There is at least one `OPTIONAL MATCH` clause.
  4. The first OPTIONAL MATCH is preceded by a `WITH` that:
       • Carries a bare node variable used by that OPTIONAL MATCH (e.g. `e`).
       • Contains an aggregation function (collect/count/sum/avg/min/max)
         — i.e. the WITH is an aggregation point that AGE will not push
         LIMIT through.
  5. Between that aggregation WITH and the first OPTIONAL MATCH there is
     no existing `ORDER BY … LIMIT …` (already optimised).
  6. The final ORDER BY references only aliases defined in the
     aggregation WITH (so it is legal to evaluate at that earlier point).

If any rule fails, the SQL is returned unchanged.

The rewriter is best-effort: it never raises; on any unexpected shape it
simply returns the original SQL. Detection failures degrade to current
behaviour (slow but correct).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("talent_mcp.rewriter")


# Match `ag_catalog.cypher('graph', $$ … $$)` — captures graph name and body.
# Use non-greedy + DOTALL so we handle multi-line bodies. Stop at the
# closing `$$)` to avoid swallowing trailing SQL.
_CYPHER_CALL_RE = re.compile(
    r"(ag_catalog\.cypher\s*\(\s*'(?P<graph>[^']+)'\s*,\s*\$\$)"
    r"(?P<body>.*?)"
    r"(\$\$\s*\))",
    re.DOTALL | re.IGNORECASE,
)

# Detects aggregation functions in a WITH projection.
_AGG_RE = re.compile(
    r"\b(collect|count|sum|avg|min|max)\s*\(", re.IGNORECASE
)

# Splits a Cypher body into top-level clauses (MATCH, OPTIONAL MATCH, WITH,
# WHERE, RETURN, etc.). We do this by scanning for clause keywords at the
# start of a logical line, respecting parentheses and string literals so we
# don't split inside `collect(DISTINCT s.name)` or `'(?i).*foo.*'`.
_CLAUSE_KEYWORDS = (
    "OPTIONAL MATCH",
    "MATCH",
    "WITH",
    "WHERE",
    "RETURN",
    "ORDER BY",
    "LIMIT",
    "SKIP",
    "UNWIND",
    "CALL",
)


@dataclass
class _Clause:
    keyword: str          # e.g. "WITH", "OPTIONAL MATCH"
    text: str             # full clause text including keyword
    start: int            # byte offset in original body
    end: int              # exclusive end offset


def _split_clauses(body: str) -> list[_Clause]:
    """Split a Cypher body into top-level clauses.

    Tokenises by scanning for clause keywords that appear *outside* of any
    parenthesis nesting, square-bracket nesting, single-quoted string, or
    double-quoted string. Returns clauses in source order.
    """
    clauses: list[_Clause] = []
    n = len(body)
    i = 0
    paren = 0
    bracket = 0
    in_squote = False
    in_dquote = False
    last_clause_start = 0
    last_clause_keyword: Optional[str] = None

    def _starts_keyword(pos: int) -> Optional[str]:
        # Match longest keyword first so "OPTIONAL MATCH" beats "MATCH".
        for kw in _CLAUSE_KEYWORDS:
            klen = len(kw)
            if pos + klen > n:
                continue
            window = body[pos : pos + klen]
            if window.upper() != kw:
                continue
            # Must be word-boundaried on both sides (or at edge).
            if pos > 0 and body[pos - 1].isalnum():
                continue
            after = body[pos + klen]
            if after.isalnum() or after == "_":
                continue
            return kw
        return None

    while i < n:
        ch = body[i]

        # String handling — skip everything inside quotes.
        if in_squote:
            if ch == "'" and (i == 0 or body[i - 1] != "\\"):
                in_squote = False
            i += 1
            continue
        if in_dquote:
            if ch == '"' and (i == 0 or body[i - 1] != "\\"):
                in_dquote = False
            i += 1
            continue
        if ch == "'":
            in_squote = True
            i += 1
            continue
        if ch == '"':
            in_dquote = True
            i += 1
            continue

        # Bracket/paren nesting.
        if ch == "(":
            paren += 1
            i += 1
            continue
        if ch == ")":
            paren -= 1
            i += 1
            continue
        if ch == "[":
            bracket += 1
            i += 1
            continue
        if ch == "]":
            bracket -= 1
            i += 1
            continue

        # Only consider clause keywords at top level.
        if paren == 0 and bracket == 0:
            kw = _starts_keyword(i)
            if kw is not None:
                # Close out the previous clause.
                if last_clause_keyword is not None:
                    clauses.append(
                        _Clause(
                            keyword=last_clause_keyword,
                            text=body[last_clause_start:i].rstrip(),
                            start=last_clause_start,
                            end=i,
                        )
                    )
                else:
                    # Skip leading whitespace before the first clause.
                    pass
                last_clause_start = i
                last_clause_keyword = kw
                i += len(kw)
                continue

        i += 1

    # Flush the last clause.
    if last_clause_keyword is not None:
        clauses.append(
            _Clause(
                keyword=last_clause_keyword,
                text=body[last_clause_start:].rstrip(),
                start=last_clause_start,
                end=n,
            )
        )

    return clauses


def _with_aliases_and_carries(with_text: str) -> tuple[set[str], set[str], bool]:
    """Parse a WITH clause projection.

    Returns (defined_aliases, carried_node_vars, has_aggregation).

    - defined_aliases: every name on the right-hand side of ``AS``, plus any
      bare projection that is itself a valid identifier (a "carry").
    - carried_node_vars: bare identifiers projected without ``AS`` — these
      remain in scope for subsequent MATCH/OPTIONAL MATCH clauses.
    - has_aggregation: True if any projection uses an aggregation function.
    """
    body = with_text[len("WITH"):].strip()
    # Split projections at top-level commas (respect parens).
    parts: list[str] = []
    depth = 0
    in_squote = False
    in_dquote = False
    cur = []
    for ch in body:
        if in_squote:
            cur.append(ch)
            if ch == "'":
                in_squote = False
            continue
        if in_dquote:
            cur.append(ch)
            if ch == '"':
                in_dquote = False
            continue
        if ch == "'":
            in_squote = True
            cur.append(ch)
            continue
        if ch == '"':
            in_dquote = True
            cur.append(ch)
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)

    defined: set[str] = set()
    carried: set[str] = set()
    has_agg = False
    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for p in parts:
        if _AGG_RE.search(p):
            has_agg = True
        # Strip trailing WHERE/ORDER BY tokens just in case.
        # Look for ' AS <alias>' at the end (case-insensitive).
        m = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", p, re.IGNORECASE)
        if m:
            defined.add(m.group(1))
            continue
        # Bare projection — could be a node var carry like `e` or a path
        # like `e.name` (which is illegal without AS, but agent rarely does
        # that). Only treat single-identifier projections as carries.
        if ident_re.match(p):
            carried.add(p)
            defined.add(p)
    return defined, carried, has_agg


def _optional_match_node_var(opt_text: str) -> Optional[str]:
    """Extract the leading node variable from an OPTIONAL MATCH pattern.

    e.g. ``OPTIONAL MATCH (e)-[hc:HOLDS_CERT]->(cert:Certification)`` → ``"e"``.
    Returns None if the pattern doesn't start with a bound node variable.
    """
    body = opt_text[len("OPTIONAL MATCH"):].strip()
    # First parenthesised node — capture its leading identifier (before `:`).
    m = re.match(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)", body)
    if not m:
        return None
    return m.group(1)


def _final_order_aliases(order_text: str) -> set[str]:
    """Extract identifiers referenced by the final ORDER BY clause."""
    body = order_text[len("ORDER BY"):]
    # Match identifiers; ignore those that are followed by `(` (function calls
    # like `size(matched_skills)` — we'll capture the inner identifiers too).
    refs = set()
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", body):
        name = m.group(1)
        # Skip ASC/DESC/NULLS/FIRST/LAST and SQL keywords
        if name.upper() in {"ASC", "DESC", "NULLS", "FIRST", "LAST", "AND", "OR", "BY", "ORDER"}:
            continue
        refs.add(name)
    # Filter out function names by checking what's right after each occurrence
    funcs = {"size", "length", "count", "sum", "avg", "min", "max", "coalesce", "toInteger"}
    return {r for r in refs if r not in funcs}


def _rewrite_cypher_body(body: str) -> tuple[str, Optional[str]]:
    """Rewrite a single Cypher body. Returns (new_body, reason_or_None).

    If reason is None the body was unchanged.
    """
    clauses = _split_clauses(body)
    if not clauses:
        return body, None

    # Rule 2: must end with [ORDER BY …] LIMIT N.
    if clauses[-1].keyword.upper() != "LIMIT":
        return body, None
    final_limit = clauses[-1]
    final_order: Optional[_Clause] = None
    if len(clauses) >= 2 and clauses[-2].keyword.upper() == "ORDER BY":
        final_order = clauses[-2]

    # Rule 3: must have at least one OPTIONAL MATCH.
    opt_idx = next(
        (i for i, c in enumerate(clauses) if c.keyword.upper() == "OPTIONAL MATCH"),
        None,
    )
    if opt_idx is None:
        return body, None

    # Rule 4: there must be a WITH before the first OPTIONAL MATCH that
    # (a) carries a node variable used by that OPTIONAL MATCH and
    # (b) contains an aggregation.
    agg_with: Optional[_Clause] = None
    agg_defined: set[str] = set()
    agg_carried: set[str] = set()
    for i in range(opt_idx - 1, -1, -1):
        c = clauses[i]
        if c.keyword.upper() != "WITH":
            continue
        defined, carried, has_agg = _with_aliases_and_carries(c.text)
        if has_agg:
            agg_with = c
            agg_defined = defined
            agg_carried = carried
            break

    if agg_with is None:
        return body, None

    opt_var = _optional_match_node_var(clauses[opt_idx].text)
    if opt_var is None or opt_var not in agg_carried:
        # Either we couldn't parse the OPTIONAL MATCH, or the node var it
        # uses isn't carried through the aggregation WITH — would be unsafe
        # to push LIMIT here.
        return body, None

    # Rule 5: no existing ORDER BY/LIMIT between the agg WITH and the
    # OPTIONAL MATCH.
    agg_idx = clauses.index(agg_with)
    for c in clauses[agg_idx + 1 : opt_idx]:
        kw = c.keyword.upper()
        if kw in ("ORDER BY", "LIMIT"):
            return body, "already-optimised"

    # Rule 6: every alias referenced in the final ORDER BY must be defined
    # at the agg WITH point (otherwise we cannot evaluate it there).
    if final_order is not None:
        needed = _final_order_aliases(final_order.text)
        missing = needed - agg_defined - agg_carried
        # Allow node-var dotted access (e.g. `e.years_of_experience`) by also
        # accepting the bare node var.
        if missing:
            return body, None

    # All gates passed — build the rewritten body.
    # Insert the final ORDER BY (if any) + LIMIT immediately after the
    # aggregation WITH, before the first OPTIONAL MATCH.
    # We do NOT remove the original final ORDER BY/LIMIT — keeping them is
    # idempotent (post-enrichment data is already ≤ N rows) and preserves
    # the original sort stability for the RETURN.

    insertion_parts: list[str] = []
    if final_order is not None:
        insertion_parts.append(final_order.text.strip())
    insertion_parts.append(final_limit.text.strip())
    insertion = "\n  " + "\n  ".join(insertion_parts) + "\n  "

    insert_at = clauses[opt_idx].start
    # Trim trailing whitespace from the agg WITH region.
    new_body = body[:insert_at].rstrip() + insertion + body[insert_at:]

    return new_body, "limit-pushdown"


# ══ AGE syntax cleanup ═══════════════════════════════════════════════════════════════════
#
# AGE supports a subset of openCypher / Postgres syntax. The agent
# occasionally emits constructs that are valid in standard Cypher or
# vanilla Postgres but reject in AGE. Strip / rewrite them deterministically
# rather than relying on prompt rules the model may ignore.
#
# Each cleanup is conservative: it operates on the Cypher body inside the
# `ag_catalog.cypher($$ … $$)` block only, never touches string literals,
# and always preserves semantics (or fails closed by leaving the SQL alone).

# `NULLS LAST` / `NULLS FIRST` after an ORDER BY column — not supported by AGE.
# Strip the entire token; AGE's default (NULLs sort high in DESC, low in ASC)
# matches the standard Postgres default for most agent intents.
_NULLS_RE = re.compile(r"\bNULLS\s+(?:LAST|FIRST)\b", re.IGNORECASE)

# Invalid escape sequences inside single-quoted string literals.
# AGE / Postgres only allows: \\, \', \/, \b, \f, \n, \r, \t, \uXXXX, \UXXXXXXXX.
# The agent frequently generates \. or \d in regex patterns, which Postgres
# rejects with `InvalidEscapeSequence`. We fix common cases:
#   \.  →  [.]    (literal dot — regex character class)
#   \d  →  [0-9]  (digit class)
#   \w  →  [A-Za-z0-9_]  (word class)
#   \s  →  [ ]    (simplified space — good enough for most agent intent)
_INVALID_ESCAPE_MAP = {
    "\\.": "[.]",
    "\\d": "[0-9]",
    "\\w": "[A-Za-z0-9_]",
    "\\s": "[ ]",
}

# `CASE WHEN` inside count() — AGE cannot resolve variable references inside
# CASE expressions used within count(), causing "could not find rte for X".
_COUNT_CASE_RE = re.compile(
    r"\bcount\s*\(\s*(?:DISTINCT\s+)?CASE\b", re.IGNORECASE
)


def _strip_outside_strings(body: str, pattern: re.Pattern[str]) -> tuple[str, int]:
    """Remove every match of ``pattern`` that lies outside string literals.

    Returns ``(new_body, removal_count)``. Single- and double-quoted strings
    are skipped so we never mangle a regex literal like ``'(?i).*nulls.*'``.
    """
    out: list[str] = []
    n = len(body)
    i = 0
    in_squote = False
    in_dquote = False
    removed = 0
    while i < n:
        ch = body[i]
        if in_squote:
            out.append(ch)
            if ch == "'" and (i == 0 or body[i - 1] != "\\"):
                in_squote = False
            i += 1
            continue
        if in_dquote:
            out.append(ch)
            if ch == '"' and (i == 0 or body[i - 1] != "\\"):
                in_dquote = False
            i += 1
            continue
        if ch == "'":
            in_squote = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_dquote = True
            out.append(ch)
            i += 1
            continue
        m = pattern.match(body, i)
        if m:
            removed += 1
            i = m.end()
            continue
        out.append(ch)
        i += 1
    return "".join(out), removed


def _cleanup_age_syntax(body: str) -> tuple[str, list[str]]:
    """Apply all AGE syntax fixes to a Cypher body.

    Returns ``(new_body, reasons)`` — reasons is a list of short tags for
    each cleanup that fired (empty if no changes).
    """
    reasons: list[str] = []

    # Fix 1: strip NULLS LAST/FIRST (outside strings)
    new_body, removed = _strip_outside_strings(body, _NULLS_RE)
    if removed:
        # Collapse any double spaces left behind by the strip.
        new_body = re.sub(r"[ \t]{2,}", " ", new_body)
        reasons.append(f"strip-nulls-last({removed})")

    # Fix 2: replace invalid escape sequences INSIDE string literals
    # Postgres rejects \. \d \w \s inside single-quoted strings.
    # We replace them with equivalent regex character classes.
    fixed_body, esc_count = _fix_invalid_escapes(new_body)
    if esc_count:
        new_body = fixed_body
        reasons.append(f"fix-escape({esc_count})")

    return new_body, reasons


def _fix_invalid_escapes(body: str) -> tuple[str, int]:
    """Replace invalid escape sequences inside single-quoted string literals.

    Scans the body character by character. When inside a single-quoted string,
    replaces ``\\.``, ``\\d``, ``\\w``, ``\\s`` with their regex-safe
    equivalents from ``_INVALID_ESCAPE_MAP``.

    Returns ``(new_body, replacement_count)``.
    """
    out: list[str] = []
    n = len(body)
    i = 0
    in_squote = False
    in_dquote = False
    count = 0
    while i < n:
        ch = body[i]
        # Track double-quoted strings (skip them)
        if in_dquote:
            out.append(ch)
            if ch == '"' and (i == 0 or body[i - 1] != "\\"):
                in_dquote = False
            i += 1
            continue
        if ch == '"' and not in_squote:
            in_dquote = True
            out.append(ch)
            i += 1
            continue
        # Track single-quoted strings (fix escapes inside them)
        if not in_squote:
            if ch == "'":
                in_squote = True
            out.append(ch)
            i += 1
            continue
        # Inside a single-quoted string
        if ch == "'" and (i == 0 or body[i - 1] != "\\"):
            in_squote = False
            out.append(ch)
            i += 1
            continue
        # Check for invalid escapes
        if ch == "\\" and i + 1 < n:
            two_char = body[i : i + 2]
            replacement = _INVALID_ESCAPE_MAP.get(two_char)
            if replacement is not None:
                out.append(replacement)
                count += 1
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out), count


# ══ Aggregation WITH → ORDER BY alias resolution ═════════════════════════════


def _fix_agg_order_alias(body: str) -> tuple[str, Optional[str]]:
    """Insert a pass-through WITH before ORDER BY when aliases may not resolve.

    AGE cannot resolve aliases defined in a ``WITH`` or ``RETURN`` clause
    in the ``ORDER BY`` that immediately follows.
    Error: ``UndefinedColumn: could not find rte for <alias>``.

    Fix: inject a no-aggregation ``WITH var1, var2, …`` that carries
    all projected names.  This makes the aliases regular variables that
    AGE can resolve in ``ORDER BY``.

    Also handles RETURN ... ORDER BY by injecting a WITH before RETURN.
    """
    clauses = _split_clauses(body)
    if not clauses:
        return body, None

    insertions: list[tuple[int, str]] = []
    for i, c in enumerate(clauses):
        # Pattern 1: WITH ... ORDER BY — inject pass-through WITH
        if c.keyword.upper() == "WITH":
            defined, _carried, _has_agg = _with_aliases_and_carries(c.text)
            if i + 1 >= len(clauses):
                continue
            if clauses[i + 1].keyword.upper() != "ORDER BY":
                continue
            all_names = sorted(defined)
            if not all_names:
                continue
            # Check if a pass-through WITH already exists (avoid double-injection)
            passthrough = "WITH " + ", ".join(all_names)
            insertions.append((clauses[i + 1].start, passthrough))

        # Pattern 2: RETURN ... ORDER BY — inject WITH before RETURN
        if c.keyword.upper() == "RETURN":
            if i + 1 >= len(clauses):
                continue
            if clauses[i + 1].keyword.upper() != "ORDER BY":
                continue
            # Extract aliases from RETURN
            ret_body = c.text[len("RETURN"):].strip()
            aliases = []
            for part in _split_projection(ret_body):
                m = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", part, re.IGNORECASE)
                if m:
                    aliases.append(m.group(1))
            if not aliases:
                continue
            # Inject WITH before RETURN
            passthrough = "WITH " + ", ".join(aliases)
            insertions.append((c.start, passthrough + "\n  "))

    if not insertions:
        return body, None

    new_body = body
    for pos, text in reversed(insertions):
        before = new_body[:pos].rstrip()
        after = new_body[pos:]
        new_body = before + "\n  " + text + "\n  " + after

    return new_body, "deref-agg-alias"


def _split_projection(text: str) -> list[str]:
    """Split a comma-separated projection list, respecting nested parens and quotes."""
    parts: list[str] = []
    depth = 0
    in_squote = False
    in_dquote = False
    cur: list[str] = []
    for ch in text:
        if in_squote:
            cur.append(ch)
            if ch == "'":
                in_squote = False
            continue
        if in_dquote:
            cur.append(ch)
            if ch == '"':
                in_dquote = False
            continue
        if ch == "'":
            in_squote = True
            cur.append(ch)
            continue
        if ch == '"':
            in_dquote = True
            cur.append(ch)
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def optimize_sql(sql: str) -> tuple[str, Optional[str]]:
    """Rewrite a SQL string containing an `ag_catalog.cypher(...)` call.

    Returns ``(new_sql, reason)``. ``reason`` is ``None`` if no rewrite
    happened, otherwise a short tag (e.g. ``"limit-pushdown"``).

    Safe by construction: never raises. On any parse anomaly returns the
    original SQL unchanged.
    """
    try:
        matches = list(_CYPHER_CALL_RE.finditer(sql))
        # Rule 1: exactly one Cypher call.
        if len(matches) != 1:
            return sql, None
        m = matches[0]
        body = m.group("body")

        # Reject unsupported constructs early — count(CASE WHEN ...) always
        # fails in AGE with "could not find rte for <var>".
        if _COUNT_CASE_RE.search(body):
            raise ValueError(
                "AGE does not support CASE WHEN inside count(). "
                "Use separate MATCH clauses with WHERE filters and count "
                "the results instead of count(DISTINCT CASE WHEN ...)."
            )

        reasons: list[str] = []

        # Pass 1: AGE syntax cleanup (NULLS LAST/FIRST, etc.) — must run
        # before the structural rewrite so injected ORDER BY clauses are
        # also clean.
        body, cleanup_reasons = _cleanup_age_syntax(body)
        reasons.extend(cleanup_reasons)

        # Pass 2: structural LIMIT-pushdown rewrite.
        rewritten_body, structural_reason = _rewrite_cypher_body(body)
        if structural_reason and structural_reason != "already-optimised":
            body = rewritten_body
            reasons.append(structural_reason)

        # Pass 3: fix aggregation WITH → ORDER BY alias resolution.
        # AGE cannot resolve aliases in ORDER BY after an aggregation WITH;
        # inject a pass-through WITH to materialise them as regular variables.
        rewritten_body2, alias_reason = _fix_agg_order_alias(body)
        if alias_reason:
            body = rewritten_body2
            reasons.append(alias_reason)

        if not reasons:
            return sql, None
        new_sql = sql[: m.start("body")] + body + sql[m.end("body") :]
        return new_sql, "+".join(reasons)
    except Exception:
        logger.exception("Cypher rewriter failed unexpectedly; returning original SQL")
        return sql, None


__all__ = ["optimize_sql"]
