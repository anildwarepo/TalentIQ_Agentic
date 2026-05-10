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
from azure.identity import DefaultAzureCredential

from talent_backend.config import (
    COSMOS_CHAT_ENDPOINT,
    COSMOS_CHAT_DATABASE,
    COSMOS_CHAT_CONTAINER,
)

logger = logging.getLogger("talent_backend.chat_history")

# In-memory fallback when Cosmos is unavailable
_fallback: dict[str, list[dict]] = {}


class ChatHistoryStore:
    """Cosmos DB-backed chat history with in-memory fallback."""

    def __init__(self):
        self._container = None
        self._available = False

        if not COSMOS_CHAT_ENDPOINT:
            logger.warning("COSMOS_CHAT_ENDPOINT not set — chat history is in-memory only")
            return

        try:
            credential = DefaultAzureCredential()
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

    def add_message(self, session_id: str, role: str, text: str) -> str:
        """Store a message and return its ID."""
        message_id = uuid.uuid4().hex[:24]
        doc = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "message",
        }

        if self._available:
            try:
                self._container.upsert_item(doc)
                return message_id
            except Exception as e:
                logger.warning("Cosmos write failed, using fallback: %s", e)

        # Fallback
        _fallback.setdefault(session_id, []).append(doc)
        return message_id

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        """Retrieve recent messages for a session, ordered by timestamp."""
        if self._available:
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
        if self._available:
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
        if self._available:
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
        return True
