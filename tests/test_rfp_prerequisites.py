"""Tests for RFP prerequisite guards."""

from __future__ import annotations

import talent_backend.api as api_mod
from talent_backend.api import ChatRequest, FileContext


class _FakeHistory:
    def __init__(self, messages: list[dict]):
        self._messages = messages

    def get_history(self, session_id: str, limit: int = 20):
        return self._messages


def test_rfp_match_without_context_is_blocked(monkeypatch):
    monkeypatch.setattr(api_mod, "_history", None)

    req = ChatRequest(input="Match candidates to this RFP's requirements")

    assert api_mod._missing_rfp_context(req) is True


def test_direct_candidate_search_does_not_require_rfp(monkeypatch):
    monkeypatch.setattr(api_mod, "_history", None)

    req = ChatRequest(input="Find Python developers in India")

    assert api_mod._missing_rfp_context(req) is False


def test_rfp_match_with_uploaded_file_context_can_continue(monkeypatch):
    monkeypatch.setattr(api_mod, "_history", None)

    req = ChatRequest(
        input="Match candidates to this RFP's requirements",
        file_context=FileContext(filename="rfp.txt", content="Need Python engineers", matches=[]),
    )

    assert api_mod._missing_rfp_context(req) is False


def test_rfp_match_with_historical_document_context_can_continue(monkeypatch):
    monkeypatch.setattr(
        api_mod,
        "_history",
        _FakeHistory([
            {
                "role": "user",
                "text": "[Document context from 'rfp.txt']\n---BEGIN DOCUMENT---\nNeed Python engineers\n---END DOCUMENT---",
            }
        ]),
    )

    req = ChatRequest(input="Match candidates to this RFP's requirements", session_id="sess-1")

    assert api_mod._missing_rfp_context(req) is False