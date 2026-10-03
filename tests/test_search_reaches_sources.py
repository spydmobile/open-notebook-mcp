"""Search must be able to return SOURCES, not just notes.

Why (2026-10-03): upstream open-notebook's `fn::vector_search` ends with a
GROUP BY followed by ORDER BY ... LIMIT. SurrealDB returns grouped rows in
GROUP-KEY order, so the ORDER BY has no effect; LIMIT then truncates an
id-ordered list, and `note:` sorts before `source:` and `source_insight:`.

Consequence on a real instance: 234 embedded notes meant ANY limit <= 234
returned notes only. A source scoring 0.6111 — higher than every note returned —
was silently dropped. A whole family's documents were unreachable through search
while appearing perfectly healthy in the database.

Filed upstream as lfnovo/open-notebook#1431. Until it is fixed there, this fork
works around it the same way it already works around #574: over-fetch well past
the note count, re-sort by score, then truncate.

The old code capped `request_limit` at 50, which is below the note count and so
could never reach a source no matter what the caller asked for.
"""

import asyncio
from unittest.mock import patch

from open_notebook_mcp import server


def _fake_api(notes: int, sources: int):
    """An API whose ordering is broken exactly like the real one: notes first,
    ordered by id rather than by similarity."""
    rows = [{"id": f"note:{i:04d}", "title": f"note {i}", "similarity": 0.50 + i * 0.0001}
            for i in range(notes)]
    rows += [{"id": f"source:{i:04d}", "title": f"source {i}", "similarity": 0.90 - i * 0.001}
             for i in range(sources)]

    async def fake(method, path, json_data=None, params=None):
        if path == "/api/search":
            return {"results": rows[: json_data["limit"]]}
        return []
    return fake


def test_over_fetches_past_the_note_count():
    """The request to the API must be large enough to reach sources."""
    seen = {}

    async def fake(method, path, json_data=None, params=None):
        if path == "/api/search":
            seen["limit"] = json_data["limit"]
            return {"results": []}
        return []

    with patch.object(server, "make_request", fake):
        asyncio.run(server.search(query="q", limit=10))

    assert seen["limit"] > 234, (
        f"requested only {seen.get('limit')} — below the embedded-note count, so "
        "sources remain unreachable. This is the whole bug."
    )


def test_returns_sources_when_they_outscore_notes():
    with patch.object(server, "make_request", _fake_api(notes=300, sources=5)):
        out = asyncio.run(server.search(query="q", limit=10))

    ids = [r["id"] for r in out["results"]]
    assert any(i.startswith("source:") for i in ids), (
        f"no source returned despite sources outscoring every note: {ids[:5]}"
    )


def test_results_are_sorted_by_score_descending():
    with patch.object(server, "make_request", _fake_api(notes=300, sources=5)):
        out = asyncio.run(server.search(query="q", limit=10))

    scores = [r.get("similarity") for r in out["results"] if r.get("similarity") is not None]
    assert scores == sorted(scores, reverse=True), f"not descending: {scores}"


def test_honours_the_caller_limit():
    with patch.object(server, "make_request", _fake_api(notes=300, sources=5)):
        out = asyncio.run(server.search(query="q", limit=7))
    assert len(out["results"]) == 7


def test_text_search_sorts_on_relevance_including_negatives():
    """Text search scores are raw BM25 and can be negative (upstream #1402).
    Descending order must still be correct."""
    rows = [{"id": "note:a", "relevance": -7.06},
            {"id": "source:b", "relevance": 9.12},
            {"id": "source:c", "relevance": 2.83}]

    async def fake(method, path, json_data=None, params=None):
        if path == "/api/search":
            return {"results": rows}
        return []

    with patch.object(server, "make_request", fake):
        out = asyncio.run(server.search(query="q", type="text", limit=3))

    rel = [r["relevance"] for r in out["results"]]
    assert rel == sorted(rel, reverse=True), f"not descending: {rel}"
