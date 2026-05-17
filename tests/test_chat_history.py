"""Unit tests for chat history thread management.

Tests the ChatHistoryStore in-memory fallback path and the
thread-management API endpoints (GET/DELETE/PATCH /api/threads).

References: docs/specs/chat-history.md §2.1–2.5, §3
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from talent_backend.chat_history import ChatHistoryStore, _fallback, _fallback_meta


# ── Helpers ──────────────────────────────────────────────────

TEST_USER = {"oid": "user-aaa-111", "name": "Test User", "email": "test@example.com"}
OTHER_USER = {"oid": "user-bbb-222", "name": "Other User", "email": "other@example.com"}


@pytest.fixture(autouse=True)
def _clear_fallback():
    """Ensure the in-memory store is empty before and after each test."""
    _fallback.clear()
    _fallback_meta.clear()
    yield
    _fallback.clear()
    _fallback_meta.clear()


@pytest.fixture()
def store() -> ChatHistoryStore:
    """Create a ChatHistoryStore that uses in-memory fallback (no Cosmos)."""
    with patch("talent_backend.chat_history.COSMOS_CHAT_ENDPOINT", ""):
        return ChatHistoryStore()


@pytest.fixture()
def client():
    """FastAPI TestClient with auth mocked to return TEST_USER."""
    from talent_backend.api import app, get_current_user as _dep_unused
    from talent_backend.auth import get_current_user

    async def _mock_user():
        return TEST_USER

    app.dependency_overrides[get_current_user] = _mock_user
    # Reset the global _history to a fresh in-memory store
    with patch("talent_backend.chat_history.COSMOS_CHAT_ENDPOINT", ""):
        import talent_backend.api as api_mod
        api_mod._history = ChatHistoryStore()
        yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _seed_thread(store: ChatHistoryStore, session_id: str, user_id: str, messages: list[str]):
    """Helper: add multiple user messages to a session."""
    for text in messages:
        store.add_message(session_id, "user", text, user_id=user_id)


# ═════════════════════════════════════════════════════════════
# ChatHistoryStore unit tests
# ═════════════════════════════════════════════════════════════


class TestAddMessageMeta:
    """Tests for session_meta creation/update when messages are added."""

    def test_add_message_creates_session_meta(self, store: ChatHistoryStore):
        """First message in a session should create a session_meta document."""
        store.add_message("sess-1", "user", "Hello world", user_id=TEST_USER["oid"])

        threads = store.list_threads(TEST_USER["oid"])
        assert len(threads) == 1
        meta = threads[0]
        assert meta["session_id"] == "sess-1"
        assert meta["user_id"] == TEST_USER["oid"]
        assert meta["message_count"] >= 1
        assert "last_active_at" in meta
        assert "title" in meta

    def test_add_message_updates_session_meta(self, store: ChatHistoryStore):
        """Subsequent messages should bump message_count and last_active_at."""
        store.add_message("sess-1", "user", "First message", user_id=TEST_USER["oid"])
        threads_before = store.list_threads(TEST_USER["oid"])
        first_active = threads_before[0]["last_active_at"]
        first_count = threads_before[0]["message_count"]

        # Small delay to ensure timestamp differs
        time.sleep(0.01)
        store.add_message("sess-1", "assistant", "Reply", user_id=TEST_USER["oid"])

        threads_after = store.list_threads(TEST_USER["oid"])
        assert len(threads_after) == 1
        assert threads_after[0]["message_count"] > first_count
        assert threads_after[0]["last_active_at"] >= first_active


class TestListThreads:
    """Tests for listing threads per user."""

    def test_list_threads_returns_user_threads(self, store: ChatHistoryStore):
        """list_threads should only return threads belonging to the given user."""
        store.add_message("sess-a", "user", "User A msg", user_id="user-aaa-111")
        store.add_message("sess-b", "user", "User B msg", user_id="user-bbb-222")
        store.add_message("sess-c", "user", "User A again", user_id="user-aaa-111")

        threads = store.list_threads("user-aaa-111")
        session_ids = {t["session_id"] for t in threads}
        assert session_ids == {"sess-a", "sess-c"}

    def test_list_threads_excludes_deleted(self, store: ChatHistoryStore):
        """Soft-deleted threads should not appear in list_threads results."""
        store.add_message("sess-1", "user", "Keep me", user_id=TEST_USER["oid"])
        store.add_message("sess-2", "user", "Delete me", user_id=TEST_USER["oid"])

        store.soft_delete_thread("sess-2")

        threads = store.list_threads(TEST_USER["oid"])
        session_ids = {t["session_id"] for t in threads}
        assert "sess-1" in session_ids
        assert "sess-2" not in session_ids


class TestGetThreadMessages:
    """Tests for retrieving messages from a specific thread."""

    def test_get_thread_messages(self, store: ChatHistoryStore):
        """Messages should be returned in chronological order."""
        store.add_message("sess-1", "user", "Hello", user_id=TEST_USER["oid"])
        store.add_message("sess-1", "assistant", "Hi there", user_id=TEST_USER["oid"])
        store.add_message("sess-1", "user", "How are you?", user_id=TEST_USER["oid"])

        messages = store.get_thread_messages("sess-1")
        assert len(messages) == 3
        texts = [m["text"] for m in messages]
        assert texts == ["Hello", "Hi there", "How are you?"]
        # Verify chronological order
        timestamps = [m["timestamp"] for m in messages]
        assert timestamps == sorted(timestamps)


class TestSoftDelete:
    """Tests for soft-deleting threads."""

    def test_soft_delete_thread(self, store: ChatHistoryStore):
        """Soft delete marks the thread as deleted but keeps it in storage."""
        store.add_message("sess-1", "user", "Message", user_id=TEST_USER["oid"])

        result = store.soft_delete_thread("sess-1")
        assert result is True

        # Thread should not appear in listing
        threads = store.list_threads(TEST_USER["oid"])
        assert all(t["session_id"] != "sess-1" for t in threads)

        # But messages should still exist in storage
        messages = store.get_thread_messages("sess-1")
        assert len(messages) >= 1


class TestRenameThread:
    """Tests for renaming threads."""

    def test_rename_thread(self, store: ChatHistoryStore):
        """rename_thread should update the thread's title."""
        store.add_message("sess-1", "user", "Original message", user_id=TEST_USER["oid"])

        result = store.rename_thread("sess-1", "New Title")
        assert result is True

        threads = store.list_threads(TEST_USER["oid"])
        assert len(threads) == 1
        assert threads[0]["title"] == "New Title"


class TestAutoTitle:
    """Tests for auto-generated thread titles."""

    def test_auto_title_from_first_message(self, store: ChatHistoryStore):
        """Title should be auto-generated from the first user message (first 50 chars)."""
        long_message = "Find me all Python developers in Madrid who have experience with FastAPI and async programming"
        store.add_message("sess-1", "user", long_message, user_id=TEST_USER["oid"])

        threads = store.list_threads(TEST_USER["oid"])
        assert len(threads) == 1
        title = threads[0]["title"]
        assert len(title) <= 50
        assert title == long_message[:50]


class TestBackwardCompatibility:
    """Existing methods must still work after the thread management additions."""

    def test_get_history_still_works(self, store: ChatHistoryStore):
        """The existing get_history method must remain functional."""
        store.add_message("sess-1", "user", "Hello", user_id=TEST_USER["oid"])
        store.add_message("sess-1", "assistant", "Hi", user_id=TEST_USER["oid"])

        history = store.get_history("sess-1", limit=20)
        assert len(history) >= 2
        roles = [m["role"] for m in history]
        assert "user" in roles
        assert "assistant" in roles

    def test_delete_session_still_works(self, store: ChatHistoryStore):
        """The existing hard delete (delete_session) must still work."""
        store.add_message("sess-1", "user", "Temp message", user_id=TEST_USER["oid"])

        result = store.delete_session("sess-1")
        assert result is True

        # Hard delete means messages are gone
        history = store.get_history("sess-1")
        assert len(history) == 0


# ═════════════════════════════════════════════════════════════
# API endpoint tests
# ═════════════════════════════════════════════════════════════


class TestThreadEndpoints:
    """Tests for the /api/threads REST endpoints."""

    def test_get_threads_endpoint(self, client: TestClient):
        """GET /api/threads returns 200 with a list of threads."""
        import talent_backend.api as api_mod

        api_mod._history.add_message("sess-1", "user", "Hello", user_id=TEST_USER["oid"])
        api_mod._history.add_message("sess-2", "user", "World", user_id=TEST_USER["oid"])

        resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert "threads" in data
        assert len(data["threads"]) == 2

    def test_get_thread_endpoint(self, client: TestClient):
        """GET /api/threads/{id} returns 200 with messages."""
        import talent_backend.api as api_mod

        api_mod._history.add_message("sess-1", "user", "Hello", user_id=TEST_USER["oid"])
        api_mod._history.add_message("sess-1", "assistant", "Hi", user_id=TEST_USER["oid"])

        resp = client.get("/api/threads/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert len(data["messages"]) == 2

    def test_get_thread_not_found(self, client: TestClient):
        """GET /api/threads/{id} returns 404 for a non-existent thread."""
        resp = client.get("/api/threads/nonexistent-session")
        assert resp.status_code == 404

    def test_delete_thread_endpoint(self, client: TestClient):
        """DELETE /api/threads/{id} soft-deletes and excludes from listing."""
        import talent_backend.api as api_mod

        api_mod._history.add_message("sess-1", "user", "Delete me", user_id=TEST_USER["oid"])

        resp = client.delete("/api/threads/sess-1")
        assert resp.status_code == 200

        # Should no longer appear in listing
        listing = client.get("/api/threads")
        assert listing.status_code == 200
        session_ids = {t["session_id"] for t in listing.json()["threads"]}
        assert "sess-1" not in session_ids

    def test_patch_thread_rename(self, client: TestClient):
        """PATCH /api/threads/{id} renames the thread."""
        import talent_backend.api as api_mod

        api_mod._history.add_message("sess-1", "user", "Original title msg", user_id=TEST_USER["oid"])

        resp = client.patch("/api/threads/sess-1", json={"title": "Renamed Thread"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("title") == "Renamed Thread"

    def test_thread_ownership_check(self, client: TestClient):
        """Accessing another user's thread returns 404 (not 403, to avoid enumeration)."""
        import talent_backend.api as api_mod

        # Create thread owned by OTHER_USER
        api_mod._history.add_message("sess-other", "user", "Not yours", user_id=OTHER_USER["oid"])

        # TEST_USER tries to access it — should get 404
        resp = client.get("/api/threads/sess-other")
        assert resp.status_code == 404
