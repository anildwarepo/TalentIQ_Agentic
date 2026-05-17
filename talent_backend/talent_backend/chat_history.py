"""Chat history persistence via Azure Cosmos DB.

Container: talent_db / chat_history_db
Partition key: /session_id

Document schema:
  {
    "id": "<message_id>",
    "session_id": "<session_id>",
    "role": "user" | "assistant",
    "text": "...",
    "timestamp": "2026-05-09T17:30:00Z",
    "type": "message"
  }

Graceful degradation: if Cosmos is unavailable, falls back to in-memory.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from talent_backend.config import (
    COSMOS_CHAT_ENDPOINT,
    COSMOS_CHAT_DATABASE,
    COSMOS_CHAT_CONTAINER,
    get_azure_credential,
)

logger = logging.getLogger("talent_backend.chat_history")

# Suppress noisy Cosmos SDK health-check tracebacks when credentials are
# unavailable. These run on a background thread and can't be caught per-request.
logging.getLogger("azure.cosmos._GlobalEndpointManager").setLevel(logging.CRITICAL)
logging.getLogger("azure.cosmos._global_endpoint_manager").setLevel(logging.CRITICAL)

# Circuit breaker: after this many consecutive Cosmos failures, stop trying
# until the next process restart.  Avoids 10s+ timeouts on every request.
_CIRCUIT_BREAKER_THRESHOLD = 3

# In-memory fallback when Cosmos is unavailable
_fallback: dict[str, list[dict]] = {}
_fallback_meta: dict[str, dict] = {}  # session_id → session_meta doc


class ChatHistoryStore:
    """Cosmos DB-backed chat history with in-memory fallback."""

    def __init__(self):
        self._container = None
        self._available = False
        self._consecutive_failures = 0

        if not COSMOS_CHAT_ENDPOINT:
            logger.warning("COSMOS_CHAT_ENDPOINT not set — chat history is in-memory only")
            return

        try:
            credential = get_azure_credential()
            client = CosmosClient(url=COSMOS_CHAT_ENDPOINT, credential=credential)
            db = client.get_database_client(COSMOS_CHAT_DATABASE)
            # Create container if it doesn't exist (partition key: /session_id)
            db.create_container_if_not_exists(
                id=COSMOS_CHAT_CONTAINER,
                partition_key=PartitionKey(path="/session_id"),
            )
            self._container = db.get_container_client(COSMOS_CHAT_CONTAINER)
            self._available = True
            logger.info(
                "Cosmos chat history: %s/%s",
                COSMOS_CHAT_DATABASE,
                COSMOS_CHAT_CONTAINER,
            )
        except Exception as e:
            logger.warning("Cosmos DB unavailable — falling back to in-memory: %s", e)

    def add_message(self, session_id: str, role: str, text: str, *, user_id: str | None = None) -> str:
        """Store a message and return its ID. Updates session_meta automatically."""
        message_id = uuid.uuid4().hex[:24]
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "text": text,
            "timestamp": now,
            "type": "message",
        }

        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                self._container.upsert_item(doc)
                self._update_session_meta(session_id, role, text, now, user_id=user_id)
                self._consecutive_failures = 0  # reset on success
                return message_id
            except Exception as e:
                self._consecutive_failures += 1
                if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                    logger.warning(
                        "Cosmos circuit breaker open after %d failures — using in-memory fallback until restart",
                        self._consecutive_failures,
                    )
                else:
                    logger.warning("Cosmos write failed (%d/%d), using fallback: %s",
                                   self._consecutive_failures, _CIRCUIT_BREAKER_THRESHOLD, e)

        # Fallback
        _fallback.setdefault(session_id, []).append(doc)
        self._update_session_meta_fallback(session_id, role, text, now, user_id=user_id)
        return message_id

    # ── Session meta helpers ─────────────────────────────────

    def _update_session_meta(
        self, session_id: str, role: str, text: str, timestamp: str, *, user_id: str | None = None
    ):
        """Create or update the session_meta document in Cosmos."""
        meta_id = f"meta_{session_id}"
        try:
            meta = self._container.read_item(item=meta_id, partition_key=session_id)
            meta["last_active_at"] = timestamp
            meta["message_count"] = meta.get("message_count", 0) + 1
            if user_id and not meta.get("user_id"):
                meta["user_id"] = user_id
            self._container.upsert_item(meta)
        except CosmosResourceNotFoundError:
            title = text[:50] if role == "user" else ""
            meta = {
                "id": meta_id,
                "session_id": session_id,
                "type": "session_meta",
                "user_id": user_id or "",
                "title": title,
                "created_at": timestamp,
                "last_active_at": timestamp,
                "message_count": 1,
                "is_deleted": False,
                "deleted_at": None,
            }
            self._container.upsert_item(meta)
        except Exception as e:
            logger.warning("session_meta update failed: %s", e)

    def _update_session_meta_fallback(
        self, session_id: str, role: str, text: str, timestamp: str, *, user_id: str | None = None
    ):
        """Create or update in-memory session_meta."""
        if session_id in _fallback_meta:
            meta = _fallback_meta[session_id]
            meta["last_active_at"] = timestamp
            meta["message_count"] = meta.get("message_count", 0) + 1
            if user_id and not meta.get("user_id"):
                meta["user_id"] = user_id
        else:
            title = text[:50] if role == "user" else ""
            _fallback_meta[session_id] = {
                "id": f"meta_{session_id}",
                "session_id": session_id,
                "type": "session_meta",
                "user_id": user_id or "",
                "title": title,
                "created_at": timestamp,
                "last_active_at": timestamp,
                "message_count": 1,
                "is_deleted": False,
                "deleted_at": None,
            }

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        """Retrieve recent messages for a session, ordered by timestamp."""
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                query = (
                    "SELECT c.role, c.text, c.timestamp FROM c "
                    "WHERE c.session_id = @sid AND c.type = 'message' "
                    "ORDER BY c.timestamp ASC OFFSET 0 LIMIT @limit"
                )
                items = self._container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@sid", "value": session_id},
                        {"name": "@limit", "value": limit},
                    ],
                    partition_key=session_id,
                )
                return list(items)
            except Exception as e:
                logger.warning("Cosmos read failed, using fallback: %s", e)

        # Fallback
        return _fallback.get(session_id, [])[-limit:]

    def list_sessions(self) -> list[dict]:
        """List all sessions with their latest message timestamp."""
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                query = (
                    "SELECT c.session_id, MAX(c.timestamp) AS last_active, "
                    "COUNT(1) AS message_count "
                    "FROM c WHERE c.type = 'message' "
                    "GROUP BY c.session_id"
                )
                items = self._container.query_items(
                    query=query,
                    enable_cross_partition_query=True,
                )
                return list(items)
            except Exception as e:
                logger.warning("Cosmos list sessions failed: %s", e)

        # Fallback
        return [
            {"session_id": sid, "message_count": len(msgs)}
            for sid, msgs in _fallback.items()
        ]

    def delete_session(self, session_id: str) -> bool:
        """Delete all messages for a session."""
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                query = "SELECT c.id FROM c WHERE c.session_id = @sid"
                items = self._container.query_items(
                    query=query,
                    parameters=[{"name": "@sid", "value": session_id}],
                    partition_key=session_id,
                )
                for item in items:
                    self._container.delete_item(item=item["id"], partition_key=session_id)
                return True
            except Exception as e:
                logger.warning("Cosmos delete failed: %s", e)

        # Fallback
        _fallback.pop(session_id, None)
        _fallback_meta.pop(session_id, None)
        return True

    # ── Thread management ────────────────────────────────────

    def list_threads(self, user_id: str, limit: int = 20) -> list[dict]:
        """List session_meta documents for a user, ordered by last_active_at DESC."""
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                query = (
                    "SELECT c.session_id, c.title, c.created_at, c.last_active_at, "
                    "c.message_count FROM c "
                    "WHERE c.type = 'session_meta' AND c.user_id = @uid "
                    "AND (c.is_deleted = false OR NOT IS_DEFINED(c.is_deleted)) "
                    "ORDER BY c.last_active_at DESC "
                    "OFFSET 0 LIMIT @limit"
                )
                items = self._container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@uid", "value": user_id},
                        {"name": "@limit", "value": limit},
                    ],
                    enable_cross_partition_query=True,
                )
                return list(items)
            except Exception as e:
                logger.warning("Cosmos list_threads failed: %s", e)

        # Fallback
        threads = [
            meta for meta in _fallback_meta.values()
            if meta.get("user_id") == user_id and not meta.get("is_deleted")
        ]
        threads.sort(key=lambda t: t.get("last_active_at", ""), reverse=True)
        return threads[:limit]

    def get_thread_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get messages for a thread, ordered by timestamp ASC."""
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                query = (
                    "SELECT c.role, c.text, c.timestamp FROM c "
                    "WHERE c.session_id = @sid AND c.type = 'message' "
                    "ORDER BY c.timestamp ASC OFFSET 0 LIMIT @limit"
                )
                items = self._container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@sid", "value": session_id},
                        {"name": "@limit", "value": limit},
                    ],
                    partition_key=session_id,
                )
                return list(items)
            except Exception as e:
                logger.warning("Cosmos get_thread_messages failed: %s", e)

        # Fallback
        return _fallback.get(session_id, [])[-limit:]

    def get_thread_meta(self, session_id: str) -> dict | None:
        """Get the session_meta document for a thread."""
        meta_id = f"meta_{session_id}"
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            try:
                return self._container.read_item(item=meta_id, partition_key=session_id)
            except CosmosResourceNotFoundError:
                return None
            except Exception as e:
                logger.warning("Cosmos get_thread_meta failed: %s", e)

        # Fallback
        return _fallback_meta.get(session_id)

    def soft_delete_thread(self, session_id: str) -> bool:
        """Soft-delete a thread by setting is_deleted on its session_meta."""
        now = datetime.now(timezone.utc).isoformat()
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            meta_id = f"meta_{session_id}"
            try:
                meta = self._container.read_item(item=meta_id, partition_key=session_id)
                meta["is_deleted"] = True
                meta["deleted_at"] = now
                self._container.upsert_item(meta)
                return True
            except CosmosResourceNotFoundError:
                return False
            except Exception as e:
                logger.warning("Cosmos soft_delete failed: %s", e)

        # Fallback
        if session_id in _fallback_meta:
            _fallback_meta[session_id]["is_deleted"] = True
            _fallback_meta[session_id]["deleted_at"] = now
            return True
        return False

    def rename_thread(self, session_id: str, title: str) -> bool:
        """Rename a thread by updating the title on its session_meta."""
        if self._available and self._consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
            meta_id = f"meta_{session_id}"
            try:
                meta = self._container.read_item(item=meta_id, partition_key=session_id)
                meta["title"] = title
                self._container.upsert_item(meta)
                return True
            except CosmosResourceNotFoundError:
                return False
            except Exception as e:
                logger.warning("Cosmos rename_thread failed: %s", e)

        # Fallback
        if session_id in _fallback_meta:
            _fallback_meta[session_id]["title"] = title
            return True
        return False
