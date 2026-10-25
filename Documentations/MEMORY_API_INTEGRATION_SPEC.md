# CortexStone Memory Subsystem — FastAPI Integration Specification

**Document Version:** 1.0
**Target Audience:** Bhavya Fonseca (Backend & Infrastructure Lead), Archis Samanta (ML/DL Lead), Himanshu (Agents Core), Raghav (Security)
**Author:** Apurva (Database & Memory Subsystem Lead)
**Status:** Implemented API contract; see the source and development guide for runtime configuration.
**Date:** October 2026

---

## 1. Purpose and Scope

This document specifies the REST API contracts, security boundaries, and dependency injection patterns for exposing the memory subsystem within the CortexStone FastAPI application (`src/cortexstone/api/`). Authenticated routes are implemented in `src/cortexstone/api/v1/memories.py` and `src/cortexstone/api/dependencies.py`.

### 1.1. Context & Invariants
- **Domain Status:** All underlying schemas, models, repositories, application memory services, retrieval engines, prompt formatters, and offline benchmarks are fully implemented and verified with 90 passing automated tests.
- **Implementation Note:** This began as a contract proposal. The memory routes now use OIDC bearer-token verification and owner scoping. The `X-User-ID` example formerly shown below was unsafe and must not be used; identity is derived only from the verified token subject.
- **Teammate Ownership:**
  - **Apurva (Database & Memory):** Owns schemas, models, repositories, lifecycle service, retrieval, context formatting, and evaluation harness.
  - **Bhavya (Backend & Infrastructure):** Owns FastAPI composition, routing (`src/cortexstone/api/v1/`), dependency injection, and server configuration.
  - **Himanshu (Agentic AI):** Owns agent orchestration loop and runtime retrieval invocation.
  - **Raghav (Cyber Security):** Owns authentication boundary and central secret redaction pipeline.

---

## 2. Existing Service Interfaces & Contracts

The proposed API routes directly delegate to existing, testable service interfaces in `src/cortexstone/`. No new business logic or repository queries should be implemented directly in FastAPI route handlers.

### 2.1. Memory Lifecycle Service
**File:** `src/cortexstone/application/memory/service.py`
**Class:** `MemoryService(repository: MemoryRepositoryInterface, audit_logger: Optional[AuditLoggerInterface] = None)`

| Method | Signature | Description |
| :--- | :--- | :--- |
| `create_memory` | `async def create_memory(owner_id: str, item: MemoryItemCreate) -> MemoryItemRead` | Creates and persists a new memory item for the authenticated owner. Records a non-sensitive audit event. |
| `get_memory` | `async def get_memory(owner_id: str, memory_id: UUID) -> Optional[MemoryItemRead]` | Retrieves an active memory record by ID. Returns `None` if missing, soft-deleted, or owned by another tenant. |
| `list_memories` | `async def list_memories(owner_id: str, filter_params: Optional[MemoryFilter] = None) -> List[MemoryItemRead]` | Lists active memories matching filters (kind, sensitivity, approval, temporal bounds) ordered deterministically. |
| `update_memory` | `async def update_memory(owner_id: str, memory_id: UUID, update_data: MemoryItemUpdate, allow_approval_change: bool = False) -> Optional[MemoryItemRead]` | Modifies memory attributes. Approval toggling is guarded by `allow_approval_change`. |
| `forget_memory` | `async def forget_memory(owner_id: str, memory_id: UUID) -> DeletionReceipt` | Executes verifiable soft deletion, asserts ordinary queries return `None`, and returns a content-free receipt. |

### 2.2. Memory Retrieval Service
**File:** `src/cortexstone/memory/retrieval/retriever.py`
**Class:** `MemoryRetrievalService(repository: MemoryRepositoryInterface, embedding_provider: Optional[EmbeddingProvider], ranking_config: Optional[RankingConfig])`

| Method | Signature | Description |
| :--- | :--- | :--- |
| `retrieve` | `async def retrieve(owner_id: str, request: RetrievalRequest, reference_time: Optional[datetime] = None) -> RetrievalResult` | Generates query vector, fetches active candidate records, computes composite ranking (similarity, recency, confidence), and returns ranked top-$k$ results. |

### 2.3. Prompt Context Formatter
**File:** `src/cortexstone/memory/retrieval/formatter.py`
**Function:** `format_memory_context(results: List[MemorySearchResult], max_items: Optional[int] = None) -> str`
- Formats retrieved results into `<memory_context>` XML blocks.
- Emits citations: `[Source: <type>:<ref>, <timestamp> | Conf: <conf>]`.
- Distinguishes inferences with `[INFERRED]`.
- Emits `<memory_context>\nNo relevant memories found.\n</memory_context>` when empty.

---

## 3. Historical Endpoint Proposal — Superseded

This section and its examples predate the frontend API contract draft v2. They are retained only as historical service-integration notes and are not the public HTTP contract. For public endpoints and fields, use the frontend contract draft v2 and the route schemas in `src/cortexstone/api/v1/`. The public MVP exposes only `GET/POST /api/v1/memories`, `GET/DELETE /api/v1/memories/{memory_id}`, and `GET /api/v1/me`; it does not expose memory search, export, or update.

### 3.1. Create Memory Record
- **Method / Path:** `POST /api/v1/memories`
- **Purpose:** Store a newly observed fact, episode, or draft skill for the authenticated user.
- **Service Invocation:** `await memory_service.create_memory(owner_id=current_user_id, item=payload)`
- **Authentication:** Mandatory. `owner_id` is supplied by the verified authentication token, **never** accepted from the JSON body.
- **Request Body:** `MemoryItemCreate` (Pydantic schema from `cortexstone.memory.schemas`):
  - `kind` (string, required): `"fact"`, `"episode"`, or `"skill"`.
  - `content` (string, required): Non-empty text content.
  - `title` (string, optional): Short descriptive title.
  - `occurred_at` (datetime, optional): Timezone-aware UTC datetime.
  - `sensitivity` (string, optional, default `"normal"`): `"normal"`, `"sensitive"`, or `"internal"`.
  - `source_type` (string, optional): Origin category (e.g., `"user_direct"`, `"github"`, `"calendar"`, `"notes"`).
  - `source_ref` (string, optional): Document or entity reference (e.g., `"issue_42"`, `"profile_setup"`).
  - `confidence` (float, optional, 0.0 to 1.0): Confidence score.
  - `is_inferred` (bool, optional, default `false`): True if derived by model inference; False if user-stated.
  - `approved` (bool, optional, default `false`): Initial approval status.
  - `metadata` (object, optional, default `{}`): Structured auxiliary attributes.
- **Success Response:** `201 Created`
  - Body: `MemoryItemRead`
- **Error Cases:**
  - `400 Bad Request`: Blank content, unparsable datetime, or invalid enum.
  - `401 Unauthorized`: Missing, expired, or invalid authorization credentials.
  - `422 Unprocessable Entity`: Request body validation error.

### 3.2. List Memories
- **Method / Path:** `GET /api/v1/memories`
- **Purpose:** List active memories belonging to the authenticated user with optional filtering.
- **Service Invocation:** `await memory_service.list_memories(owner_id=current_user_id, filter_params=filters)`
- **Authentication:** Mandatory. Scoped strictly to `current_user_id`.
- **Query Parameters:**
  - `kind` (optional): Filter by `"fact"`, `"episode"`, or `"skill"`.
  - `sensitivity` (optional): Filter by `"normal"`, `"sensitive"`, or `"internal"`.
  - `approved_only` (bool, optional): Filter for approved items (e.g., skills).
  - `occurred_after` (datetime, optional): Events on or after this UTC timestamp.
  - `occurred_before` (datetime, optional): Events on or before this UTC timestamp.
  - `limit` (int, optional, default 50, max 100): Page limit.
  - `offset` (int, optional, default 0): Page offset.
- **Success Response:** `200 OK`
  - Body: JSON array `List[MemoryItemRead]` (or paginated envelope `{"items": [...], "total": int, "limit": int, "offset": int}`).
- **Security Rule:** `include_deleted` parameter is **not exposed** to client queries. Soft-deleted items are never listed.

### 3.3. Retrieve Memory by ID
- **Method / Path:** `GET /api/v1/memories/{memory_id}`
- **Purpose:** Fetch a single memory item by its UUID.
- **Service Invocation:** `await memory_service.get_memory(owner_id=current_user_id, memory_id=memory_id)`
- **Authentication:** Mandatory.
- **Path Parameters:** `memory_id` (UUID).
- **Success Response:** `200 OK` with `MemoryItemRead`.
- **Error Cases:**
  - `401 Unauthorized`: Missing or invalid credentials.
  - `404 Not Found`: Memory does not exist, belongs to another user, or has been soft-deleted.
  - *(Invariant: Return 404 rather than 403 for other users' IDs to prevent cross-tenant enumeration attacks).*

### 3.4. Semantic Search & Memory Retrieval
- **Method / Path:** `POST /api/v1/memories/search`
- **Purpose:** Search and rank memories relevant to a natural language query for agent prompt context.
- **Service Invocation:** `await retrieval_service.retrieve(owner_id=current_user_id, request=payload)`
- **Authentication:** Mandatory.
- **Request Body:** `RetrievalRequest` (from `cortexstone.memory.retrieval.retriever`):
  - `query` (string, required): Non-empty search query text.
  - `top_k` (int, optional, default 5, min 1, max 50): Number of results to return.
  - `kind` (string, optional): Filter by memory kind.
  - `sensitivity` (string, optional): Filter by sensitivity level.
  - `approved_only` (bool, optional): Only retrieve approved items.
  - `occurred_after` / `occurred_before` (datetime, optional): Temporal filter bounds.
  - `format_context` (bool, optional query parameter, default `false`): If true, response includes prompt-ready `<memory_context>` XML string.
- **Success Response:** `200 OK`
  - Body: `RetrievalResult` (with `owner_id`, `query`, `total_eligible`, `returned_count`, and `items` array).
- **Error Cases:**
  - `400 Bad Request`: Empty or whitespace-only query string.
  - `401 Unauthorized`: Missing or invalid credentials.
  - `503 Service Unavailable`: Embedding provider not configured or temporarily unreachable.

### 3.5. Verifiably Forget a Memory
- **Method / Path:** `DELETE /api/v1/memories/{memory_id}`
- **Purpose:** Permanently erase/forget a memory with verifiable non-retrievability guarantee.
- **Service Invocation:** `await memory_service.forget_memory(owner_id=current_user_id, memory_id=memory_id)`
- **Authentication:** Mandatory.
- **Path Parameters:** `memory_id` (UUID).
- **Success Response:** `200 OK`
  - Body: `DeletionReceipt` (contains `memory_id`, `owner_id`, `deleted_at`, `verified_excluded: true`, and `status: "forgotten"` or `"already_forgotten"`).
  - *(Invariant: The receipt contains **zero memory content**, plaintext, or secrets).*
- **Error Cases:**
  - `401 Unauthorized`: Missing or invalid credentials.
  - `500 Internal Server Error`: Verification failure (soft delete was executed, but post-delete assertion query still returned the item).

---

## 4. Historical Request & Response Examples — Superseded

The examples below show earlier proposed API shapes and must not be used for frontend implementation. They are retained as historical reference only; current request and response shapes are defined by frontend API contract draft v2 and the live OpenAPI schema.

### 4.1. `POST /api/v1/memories`

**Request:**
```http
POST /api/v1/memories HTTP/1.1
Host: localhost:8000
Authorization: Bearer <valid_token>
Content-Type: application/json

{
  "kind": "fact",
  "title": "Preferred Database",
  "content": "CortexStone uses PostgreSQL 16 with pgvector extension.",
  "occurred_at": "2026-10-15T10:00:00Z",
  "sensitivity": "normal",
  "source_type": "github",
  "source_ref": "issue_db_01",
  "confidence": 0.98,
  "is_inferred": false,
  "approved": true
}
```

**Response (`201 Created`):**
```json
{
  "id": "11111111-1111-1111-1111-111111111102",
  "owner_id": "user_apurva",
  "kind": "fact",
  "title": "Preferred Database",
  "content": "CortexStone uses PostgreSQL 16 with pgvector extension.",
  "occurred_at": "2026-10-15T10:00:00Z",
  "sensitivity": "normal",
  "source_type": "github",
  "source_ref": "issue_db_01",
  "confidence": 0.98,
  "approved": true,
  "metadata": {},
  "deleted_at": null,
  "created_at": "2026-10-15T10:00:00Z",
  "updated_at": "2026-10-15T10:00:00Z"
}
```

---

### 4.2. `POST /api/v1/memories/search`

**Request:**
```http
POST /api/v1/memories/search HTTP/1.1
Host: localhost:8000
Authorization: Bearer <valid_token>
Content-Type: application/json

{
  "query": "Which database engine does CortexStone use?",
  "top_k": 3
}
```

**Response (`200 OK`):**
```json
{
  "owner_id": "user_apurva",
  "query": "Which database engine does CortexStone use?",
  "total_eligible": 12,
  "returned_count": 1,
  "items": [
    {
      "item": {
        "id": "11111111-1111-1111-1111-111111111102",
        "owner_id": "user_apurva",
        "kind": "fact",
        "title": "Preferred Database",
        "content": "CortexStone uses PostgreSQL 16 with pgvector extension.",
        "occurred_at": "2026-10-15T10:00:00Z",
        "sensitivity": "normal",
        "source_type": "github",
        "source_ref": "issue_db_01",
        "confidence": 0.98,
        "approved": true,
        "metadata": {},
        "deleted_at": null,
        "created_at": "2026-10-15T10:00:00Z",
        "updated_at": "2026-10-15T10:00:00Z"
      },
      "relevance_score": 0.8842,
      "semantic_distance": 0.1523
    }
  ]
}
```

---

### 4.3. `DELETE /api/v1/memories/{memory_id}`

**Request:**
```http
DELETE /api/v1/memories/11111111-1111-1111-1111-111111111109 HTTP/1.1
Host: localhost:8000
Authorization: Bearer <valid_token>
```

**Response (`200 OK`):**
```json
{
  "memory_id": "11111111-1111-1111-1111-111111111109",
  "owner_id": "user_apurva",
  "deleted_at": "2026-10-22T09:30:00Z",
  "verified_excluded": true,
  "status": "forgotten"
}
```

---

## 5. Security Boundaries & Invariants

1. **Mandatory Authenticated Identity:**
   - The authenticated principal must inject `current_user_id`.
   - Never trust caller-supplied `owner_id` parameters or allow clients to assert ownership.
2. **Strict Multi-Tenant Isolation:**
   - Every database query and mutation must enforce `WHERE owner_id = :owner_id`.
   - An attempt to fetch, update, or delete a memory belonging to another tenant must return `404 Not Found` (never `403 Forbidden`) to prevent UUID enumeration.
3. **Guaranteed Exclusion of Deleted Memories:**
   - Queries must always exclude records where `deleted_at IS NOT NULL`.
   - Forgetting a memory immediately marks `deleted_at = UTC NOW()` and verifies non-retrievability before completing the request.
4. **Zero-Knowledge Receipts and Logs:**
   - `DeletionReceipt` and audit logs must never echo the deleted memory content or embedding vectors.
   - Audit events store SHA-256 hashes of erased content, not plaintext.
5. **Prompt Injection Containment:**
   - Memory content retrieved for agent prompts is unescaped and untrusted. When passed to the agent, it must be contained strictly inside `<memory_context>` tags with formatted provenance citations to satisfy `MEMORY_RECALL_PROMPT_V1`.
6. **Redaction Responsibility:**
   - Sensitive credential/token redaction before memory persistence belongs to Raghav's central security pipeline (`src/cortexstone/security/redaction/sanitizer.py`).

---

## 6. Shared Error Handling Envelope

Bhavya's FastAPI app entry point (`src/cortexstone/api/main.py`) already defines standard error middleware and response wrappers. All memory endpoint errors must conform to this envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "The requested memory item was not found."
  },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Current Status Codes for the Public Memory API:
- `201 Created`: Memory created.
- `204 No Content`: Memory forgotten.
- `401 Unauthorized` (`code: "unauthorized"`): Missing, expired, or invalid bearer token.
- `404 Not Found` (`code: "not_found"`): Item missing, deleted, malformed, or belongs to another owner.
- `422 Unprocessable Entity` (`code: "invalid_request"`): Request validation failure.
- `500 Internal Server Error` (`code: "internal_server_error"`): Unexpected internal error, including a forget-verification failure.
- `503 Service Unavailable` (`code: "service_unavailable"`): Authentication is not configured, identity keys are unavailable, or the database is unavailable.

---

## 7. Dependency Injection Specification for Bhavya

To wire the memory routes into FastAPI cleanly without tight coupling:

### 7.1. FastAPI Dependencies

`src/cortexstone/api/dependencies.py` provides the request-scoped database session, `get_authenticated_user`, and `get_memory_service`. Authentication validates an RS256 bearer token against the configured OIDC issuer, audience, and JWKS URL (`CORTEXSTONE_AUTH_ISSUER`, `CORTEXSTONE_AUTH_AUDIENCE`, and `CORTEXSTONE_AUTH_JWKS_URL`). All three HTTPS-backed settings are required together. Missing or invalid credentials receive `401`; when identity configuration is absent, protected routes fail closed with `503`.

The authenticated identity is the token's non-empty `sub` claim. Do not use `X-User-ID` or accept `owner_id` in request payloads. Each memory operation passes the verified subject to the service, whose repository filters reads and writes by that owner. Mutating routes commit their request-scoped transaction.

```python
from typing import Annotated

from fastapi import Depends

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.v1.schemas import MemoryCreateRequest, MemoryResponse
from cortexstone.application.memory.service import MemoryService
from cortexstone.api.dependencies import get_authenticated_user, get_memory_service


async def create_memory_endpoint(
    payload: MemoryCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryResponse:
    memory = await memory_service.create_memory(
        owner_id=user.subject,
        item=payload.to_domain(),
    )
    return MemoryResponse.from_memory(memory)
```

### 7.2. Route Handler Signature Pattern
```python
@router.post("/memories", status_code=status.HTTP_201_CREATED, response_model=MemoryResponse)
async def create_memory_endpoint(
    payload: MemoryCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    memory_service: MemoryService = Depends(get_memory_service),
) -> MemoryResponse:
    memory = await memory_service.create_memory(
        owner_id=user.subject,
        item=payload.to_domain(),
    )
    return MemoryResponse.from_memory(memory)
```

---

## 8. Division of Responsibilities

| Teammate | Assigned Responsibility | Deliverable / Integration Target |
| :--- | :--- | :--- |
| **Apurva** (DB & Memory) | Database models, schemas, repositories, lifecycle service, retrieval ranking, prompt formatting, evaluation. | `src/cortexstone/db/`, `src/cortexstone/memory/`, `src/cortexstone/application/memory/` (All Complete & Tested). |
| **Bhavya** (Backend/Infra) | FastAPI routes, settings, dependency injection, application startup, Docker deployment. | The memory API routes, OIDC settings, and dependency injection are implemented in `src/cortexstone/api/`. |
| **Himanshu** (Agents Core) | Agent orchestration loop and runtime integration. | When `route.intent == IntentCategory.MEMORY_RECALL`, call `retrieval_service.retrieve` and wrap prompt in `format_memory_context`. |
| **Raghav** (Cyber Security) | Auth token verification and central secret redaction pipeline. | OIDC token verification is implemented; secret sanitization before memory writes remains a separate integration task. |

---

## 9. Historical Open Questions — Superseded

These questions predate frontend API contract draft v2 and are retained as historical notes only. Authentication now uses OIDC RS256 bearer tokens; BGE-small at 384 dimensions is configured; memory listing uses `{items, total, limit, offset}` with a default limit of 20 and maximum of 100. Public memory search, edit, and export are deferred and must not be added without an agreed frontend contract. Chat, connectors, and notes are outside this memory API implementation.

1. **Authentication Token Protocol:**
   - *Question for Raghav & Bhavya:* Will the frontend send standard JWT Bearer tokens, or will local development use mock header authentication (`X-User-ID: <id>`)?
2. **Embedding Model & Vector Dimension Freeze:**
   - *Question for Archis & Team:* What is the final approved embedding model (e.g., Nebius `Qwen/Qwen3-Embedding-8B` at 4096 dimensions vs FastEmbed at 384 dimensions)? Once chosen, Apurva will generate the PostgreSQL `VECTOR(D)` migration.
3. **Prompt Context in Search Response:**
   - *Question for Himanshu:* Should `POST /api/v1/memories/search` return only raw `RetrievalResult` objects, or should an optional query parameter (`?format=context`) include the pre-rendered `<memory_context>` string directly?
4. **Pagination Envelope Structure:**
   - *Question for Bhavya & Sahaj (Frontend):* Does the frontend require a paginated wrapper (e.g., `{"items": [...], "total": int, "has_more": bool}`) or a flat array `List[MemoryItemRead]` with response pagination headers?
