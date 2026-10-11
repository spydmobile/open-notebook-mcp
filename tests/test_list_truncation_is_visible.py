"""A truncated listing must never look like a complete one.

WHY (2026-10-11). `list_sources` defaults to `limit=20` and returns
`count: len(rows)`. On the Infrastructure notebook — 21 sources — one call
returned `count: 20` over twenty rows, of which **nineteen were distinct**
because one row was duplicated by the API. Three different true numbers (20
returned, 19 distinct, 21 in the corpus) and the response labelled none of them.

Synthesis built an absence proof on top of this. `verify_absence()` enumerates
rather than searches, deliberately, because measurement showed neither retrieval
path can establish absence — and the enumeration runs on `list_*`. She concluded
two sources had been DELETED, including the subject of one of her supersessions,
then found both alive via `get_source`. **The mechanism built to escape "I found
nothing versus I could not look" was answering "I could not look" in the words
of "that is everything."**

The docstring said "Get all sources". It gets twenty.

THE FIX IS NOT A BIGGER DEFAULT. A bigger default moves the cliff; it does not
label it. So:

- `returned` and `distinct` are both reported, which exposes duplicate rows.
- `has_more` is **PROBED, not inferred**. `len(rows) == limit` is a heuristic
  that is wrong exactly when the corpus size equals the limit; one extra request
  at the next offset turns the guess into a measurement.
- `truncated` plus a `warning` naming the remedy, so a caller who ignores every
  other field still cannot read the result as complete.
- `count` keeps its old meaning (rows returned) because a consumer already reads
  it — changing its semantics silently would be the same class of fault.
"""

import asyncio
from unittest.mock import patch

from open_notebook_mcp import server


def _api_with(total: int, duplicate_at: int | None = None):
    """An API holding `total` rows, optionally repeating one of them."""
    def page(limit, offset):
        rows = [{"id": f"source:{i:04d}", "title": f"src {i}"} for i in range(total)]
        if duplicate_at is not None and duplicate_at < len(rows):
            rows.insert(duplicate_at + 1, dict(rows[duplicate_at]))
        return rows[offset : offset + limit]

    calls = []

    async def fake(method, path, json_data=None, params=None):
        calls.append(dict(params or {}))
        if path == "/api/sources":
            return page(params.get("limit", 20), params.get("offset", 0))
        return []

    return fake, calls


def _run(**kwargs):
    return asyncio.get_event_loop().run_until_complete(server.list_sources(**kwargs))


def test_a_full_page_is_reported_as_truncated_with_more_available():
    fake, _ = _api_with(total=21)
    with patch.object(server, "make_request", fake):
        out = _run(limit=20)

    assert out["returned"] == 20
    assert out["truncated"] is True
    assert out["has_more"] is True
    assert "limit" in out["warning"].lower() or "offset" in out["warning"].lower()


def test_has_more_is_PROBED_not_inferred_from_a_full_page():
    """The boundary case: a corpus of exactly `limit` rows fills the page and
    has nothing after it. Inferring from `len(rows) == limit` cries wolf here."""
    fake, calls = _api_with(total=20)
    with patch.object(server, "make_request", fake):
        out = _run(limit=20)

    assert out["returned"] == 20
    assert out["has_more"] is False, "a full page with nothing after it is complete"
    assert len(calls) == 2, "the probe must actually be issued"
    assert calls[1]["offset"] == 20


def test_a_short_page_is_complete_and_issues_no_probe():
    fake, calls = _api_with(total=5)
    with patch.object(server, "make_request", fake):
        out = _run(limit=20)

    assert out["returned"] == 5
    assert out["truncated"] is False
    assert out["has_more"] is False
    assert len(calls) == 1, "a short page proves completeness; do not spend a request"


def test_duplicate_rows_are_exposed_rather_than_counted_as_distinct():
    """The real response repeated source:pdp8nfzxmy8jj7wf7pzg. A caller counting
    rows gets one answer and a caller counting ids gets another."""
    fake, _ = _api_with(total=25, duplicate_at=3)
    with patch.object(server, "make_request", fake):
        out = _run(limit=20)

    assert out["returned"] == 20
    assert out["distinct"] == 19
    assert "duplicate" in out["warning"].lower()


def test_count_keeps_its_old_meaning_so_existing_callers_do_not_shift()  :
    fake, _ = _api_with(total=21)
    with patch.object(server, "make_request", fake):
        out = _run(limit=20)
    assert out["count"] == out["returned"] == 20


def test_the_docstring_no_longer_claims_to_get_all_sources():
    """It got twenty. A docstring is a claim like any other."""
    doc = (server.list_sources.__doc__ or "").lower()
    assert "get all sources" not in doc


# --- list_notes has the IDENTICAL defect, so it gets the identical test -------
# Fixing only the instance that was reported is the fault Synthesis named on
# 2026-10-11: she found BREAK 1 in two nodes and BREAK 3 in three, by grepping
# after fixing the ones I had pointed at. A named instance is a sample.


def _run_notes(**kwargs):
    return asyncio.get_event_loop().run_until_complete(server.list_notes(**kwargs))


def _notes_api(total: int):
    async def fake(method, path, json_data=None, params=None):
        if path == "/api/notes":
            rows = [{"id": f"note:{i:04d}", "title": f"n {i}"} for i in range(total)]
            return rows[params.get("offset", 0):][: params.get("limit", 20)]
        return []
    return fake


def test_list_notes_also_reports_truncation():
    with patch.object(server, "make_request", _notes_api(total=30)):
        out = _run_notes(limit=20)
    assert out["returned"] == 20
    assert out["has_more"] is True
    assert "truncated" in out["warning"].lower()


def test_list_notes_full_page_with_nothing_after_it_is_complete():
    with patch.object(server, "make_request", _notes_api(total=20)):
        out = _run_notes(limit=20)
    assert out["returned"] == 20
    assert out["has_more"] is False
