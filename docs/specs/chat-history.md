# Chat History Spec — Current → Production

**Author:** Kane (Backend Dev)  
**Date:** 2026-05-10  
**Status:** Living document  
**Source:** [talent_backend/talent_backend/chat_history.py](../../talent_backend/talent_backend/chat_history.py)

---

## 1. Current State

### Implementation: ChatHistoryStore

**File:** `talent_backend/talent_backend/chat_history.py`

Synchronous Cosmos DB SDK (`azure-cosmos`) with in-memory fallback.

```python
class ChatHistoryStore:
    def add_message(session_id, role, text) -> str
    def get_history(session_id, limit=20) -> list[dict]
    def list_sessions() -> list[dict]
    def delete_session(session_id) -> bool
```

### What Works

| Feature | Status |
|---------|--------|
| Cosmos DB backend | Working — `DefaultAzureCredential` auth |
| Partition key: `/session_id` | Working — efficient single-partition reads |
| In-memory fallback | Working — auto-activates when Cosmos unavailable |
| Message storage | Working — user + assistant messages stored |
| History retrieval | Working — ordered by timestamp, capped at 20 |
| Session listing | Working — cross-partition query with counts |
| Session deletion | Working — deletes all messages in partition |
| Container auto-creation | Working — `create_container_if_not_exists()` |

### Container Config

| Setting | Value |
|---------|-------|
| Cosmos endpoint | `COSMOS_CHAT_ENDPOINT` |
| Database | `COSMOS_CHAT_DATABASE` (default: `talent_db`) |
| Container | `COSMOS_CHAT_CONTAINER` (default: `chat_history_db`) |
| Partition key | `/session_id` |

### Document Schema

```json
{
    "id": "a1b2c3d4e5f6g7h8i9j0k1l2",
    "session_id": "abc123def456",
    "role": "user",
    "text": "Find Python developers in Madrid",
    "timestamp": "2026-05-10T10:00:00+00:00",
    "type": "message"
}
```

### API Integration

```python
# api.py
_history = ChatHistoryStore()

def _build_chat_history(session_id, user_message):
    _history.add_message(session_id, "user", user_message)
    history = _history.get_history(session_id, limit=20)
    messages = [Message(role=m["role"], contents=[m["text"]]) for m in history]
    return messages, session_id

def _record_response(session_id, text):
    _history.add_message(session_id, "assistant", text)
```

---

## 2. What Needs Production Hardening

### 2.1 Thread/Conversation Management

**Current:** Sessions are implicitly created when the first message is stored. No thread metadata (title, user info). Sessions can't be renamed.

**Target:**

| Operation | Current | Target |
|-----------|---------|--------|
| Create thread | Implicit (first message) | Explicit with metadata |
| Rename thread | Not supported | `PATCH /api/threads/{id}` |
| Delete thread | Hard delete | Soft delete with retention |
| List threads | Cross-partition query | Indexed query with pagination |
| Thread metadata | None | Title, created_at, message_count, last_active |

### 2.2 Message Pagination

**Current:** `OFFSET 0 LIMIT @limit` — returns most recent N messages. No cursor-based pagination.

**Target:** Cursor-based pagination using `timestamp` as the cursor.

```python
# Cursor-based pagination
query = """
    SELECT c.id, c.role, c.text, c.timestamp FROM c
    WHERE c.session_id = @sid AND c.type = 'message'
    AND c.timestamp < @cursor
    ORDER BY c.timestamp DESC
    OFFSET 0 LIMIT @page_size
"""
```

Response format:
```json
{
    "messages": [...],
    "next_cursor": "2026-05-10T09:55:00Z",
    "has_more": true
}
```

### 2.3 Message Search

**Current:** No search capability.

**Target:** Search within a thread's messages.

```python
query = """
    SELECT c.id, c.role, c.text, c.timestamp FROM c
    WHERE c.session_id = @sid AND c.type = 'message'
    AND CONTAINS(c.text, @search_text, true)
    ORDER BY c.timestamp DESC
"""
```

### 2.4 Thread Metadata

**Current:** No session metadata document.

**Target:** Add a `session_meta` document per thread:

```json
{
    "id": "meta_abc123",
    "session_id": "abc123",
    "type": "session_meta",
    "user_id": "oid-from-entra",
    "title": "Python developers in Madrid",
    "created_at": "2026-05-10T10:00:00Z",
    "last_active_at": "2026-05-10T10:15:00Z",
    "message_count": 12,
    "is_deleted": false,
    "deleted_at": null
}
```

Title auto-generated from first user message (first 50 characters), renamable via API.

### 2.5 Soft Delete with Retention

**Current:** `delete_session()` hard-deletes all documents.

**Target:**
1. Mark `session_meta.is_deleted = true`, set `deleted_at`
2. Messages remain for retention period (30 days default)
3. Background cleanup job purges expired soft-deleted threads
4. UI hides deleted threads from listing

### 2.6 Export Conversation History

**Target:** `GET /api/threads/{id}/export` returns full conversation as JSON or Markdown.

```json
{
    "thread_id": "abc123",
    "title": "Python developers in Madrid",
    "exported_at": "2026-05-10T10:20:00Z",
    "messages": [
        {"role": "user", "text": "...", "timestamp": "..."},
        {"role": "assistant", "text": "...", "timestamp": "..."}
    ]
}
```

---

## 3. API Endpoints

### Target API Surface

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| `GET` | `/api/threads` | List user's threads | Required — filtered by `user_id` |
| `GET` | `/api/threads/{id}/messages` | Paginated messages | Required — user must own thread |
| `DELETE` | `/api/threads/{id}` | Soft delete thread | Required — user must own thread |
| `PATCH` | `/api/threads/{id}` | Rename thread | Required — user must own thread |
| `GET` | `/api/threads/{id}/export` | Export thread | Required — user must own thread |

### Endpoint Details

#### `GET /api/threads`

```
Query params:
  - page_size: int (default 20, max 100)
  - cursor: ISO timestamp (optional, for pagination)
  - include_deleted: bool (default false)

Response:
{
    "threads": [
        {
            "session_id": "abc123",
            "title": "Python developers in Madrid",
            "created_at": "2026-05-10T10:00:00Z",
            "last_active_at": "2026-05-10T10:15:00Z",
            "message_count": 12
        }
    ],
    "next_cursor": "2026-05-10T09:00:00Z",
    "has_more": true
}
```

**Cosmos query:** Cross-partition query filtered by `user_id` and `type = 'session_meta'`.

#### `GET /api/threads/{id}/messages`

```
Query params:
  - page_size: int (default 50, max 200)
  - cursor: ISO timestamp (optional)
  - direction: "older" | "newer" (default "older")

Response:
{
    "messages": [
        {"id": "...", "role": "user", "text": "...", "timestamp": "..."},
        {"id": "...", "role": "assistant", "text": "...", "timestamp": "..."}
    ],
    "next_cursor": "2026-05-10T09:55:00Z",
    "has_more": true
}
```

**Cosmos query:** Single-partition query (efficient, no cross-partition scan).

#### `DELETE /api/threads/{id}`

```
Response: {"status": "deleted", "session_id": "abc123"}
```

Soft delete — sets `is_deleted = true` on `session_meta` document. Does NOT delete messages.

#### `PATCH /api/threads/{id}`

```
Body: {"title": "New thread title"}

Response: {"session_id": "abc123", "title": "New thread title"}
```

---

## 4. Cosmos DB Indexing Strategy

### Current Indexing

Default Cosmos DB indexing (all paths indexed). Works but not optimized.

### Target Indexing Policy

```json
{
    "indexingMode": "consistent",
    "automatic": true,
    "includedPaths": [
        {"path": "/session_id/?"},
        {"path": "/type/?"},
        {"path": "/user_id/?"},
        {"path": "/timestamp/?"},
        {"path": "/is_deleted/?"},
        {"path": "/text/?"}
    ],
    "excludedPaths": [
        {"path": "/*"}
    ],
    "compositeIndexes": [
        [
            {"path": "/session_id", "order": "ascending"},
            {"path": "/timestamp", "order": "ascending"}
        ],
        [
            {"path": "/user_id", "order": "ascending"},
            {"path": "/last_active_at", "order": "descending"}
        ]
    ]
}
```

### Query Pattern Coverage

| Query | Index Used |
|-------|-----------|
| Messages by session_id + timestamp | Composite: session_id ASC, timestamp ASC |
| Threads by user_id + last_active | Composite: user_id ASC, last_active_at DESC |
| Filter by type | Single: type |
| Filter by is_deleted | Single: is_deleted |
| Text search (CONTAINS) | Single: text |

---

## 5. Cost Optimization

### Projection Queries

**Current:** `SELECT c.role, c.text, c.timestamp` — already projecting only needed fields.

**Target:** Maintain projection discipline on all new queries. Never `SELECT *`.

### Composite Indexes

Adding composite indexes reduces RU cost for sorted queries by 5-10x compared to single-field indexes.

### Document Size

Keep message documents small. Store only `text` — no embedding, no metadata beyond essentials. Target: <2KB per message document.

### Partition Strategy

`/session_id` is a good partition key:
- High cardinality (unique per conversation)
- All messages for a conversation co-located
- Single-partition queries for message retrieval (cheapest reads)
- Thread listing requires cross-partition query (more expensive, but infrequent)

---

## 6. Integration with Session Management

| Concept | Chat History | Session Management |
|---------|-------------|-------------------|
| Container | `chat_history_db` | `sessions` |
| Shared key | `session_id` | `session_id` |
| Relationship | Thread ↔ Session (1:1) |

The `session_id` value is shared between chat history and session management. When a thread is deleted:
1. Chat history: soft-delete the thread metadata
2. Session management: TTL expires naturally (or force cleanup)

When a session expires (TTL):
1. Session management: agent history auto-deleted by Cosmos TTL
2. Chat history: thread remains (permanent record), no longer resumable

---

## 7. Migration Path

| Phase | Change |
|-------|--------|
| 1 (Current) | `ChatHistoryStore` with basic CRUD |
| 2 | Add `session_meta` documents, thread listing with metadata |
| 3 | Cursor-based pagination, soft delete |
| 4 | Search within threads, export, custom indexing policy |
| 5 | Switch to async Cosmos SDK (`azure-cosmos-aio`) for consistency with rest of async stack |

### Breaking Changes

- `list_sessions()` return format will change when metadata documents are added
- `delete_session()` will become soft delete (behavior change)
- Frontend must handle pagination responses (cursor-based)

### Async SDK Migration

Current `ChatHistoryStore` uses the **synchronous** Cosmos SDK. The rest of the backend is async (FastAPI, psycopg, agent_framework). Target: migrate to `azure-cosmos` async client or `azure-cosmos-aio`:

```python
# Current (sync)
from azure.cosmos import CosmosClient
client = CosmosClient(url=..., credential=credential)

# Target (async)
from azure.cosmos.aio import CosmosClient
client = CosmosClient(url=..., credential=credential)
async with client:
    ...
```

This eliminates blocking I/O on the event loop and is required for production performance.
