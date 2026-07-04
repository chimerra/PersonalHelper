from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CaptureRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1500)
    user_id: str


class CapturedItem(BaseModel):
    item_id: str
    item_type: Literal["task", "note"]
    title: str
    needs_review: bool


class MemorySummary(BaseModel):
    created: int = 0
    needs_review: int = 0
    skipped: int = 0


class CaptureResponse(BaseModel):
    status: Literal["ok"] = "ok"
    items: list[CapturedItem] = Field(default_factory=list)
    ignored: str | None = None
    duplicate: bool = False
    count: int = 0
    memory: MemorySummary | None = None


class ResetResponse(BaseModel):
    status: Literal["ok"] = "ok"
    message: str


class StructuredAIResult(BaseModel):
    item_type: Literal["task", "note"]
    title: str
    description: str = ""
    due_date: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    tags: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    needs_review: bool = False
    review_reason: str | None = Field(default=None, exclude=True)
    processed_by_ai: bool = Field(default=False, exclude=True)


class AnalysisResult(BaseModel):
    items: list[StructuredAIResult] = Field(default_factory=list)
    ignored: str | None = None
    processed_by_ai: bool = False


class StructureRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1500)


class TaskDoneRequest(BaseModel):
    user_id: str


class TaskDoneResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ItemDeleteRequest(BaseModel):
    user_id: str


class ItemDeleteResponse(BaseModel):
    status: Literal["ok"] = "ok"


class TaskResponse(BaseModel):
    id: str
    created_at: str
    user_id: str
    title: str
    description: str | None = None
    source_text: str | None = None
    due_date: str | None
    priority: str
    status: str
    needs_review: bool
    tags: list[str] = Field(default_factory=list)


class NoteResponse(BaseModel):
    id: str
    created_at: str
    user_id: str
    title: str
    text: str
    needs_review: bool
    tags: list[str] = Field(default_factory=list)


class InboxItem(BaseModel):
    id: str
    item_type: Literal["task", "note"]
    created_at: str
    title: str
    preview: str
    priority: str | None = None
    status: str | None = None
    needs_review: bool
    tags: list[str] = Field(default_factory=list)


class AuditRunResponse(BaseModel):
    id: str
    user_id: str | None
    created_at: str
    action: str
    input: str
    output: str | None
    status: str
    error: str | None
    duration_ms: int
    item_type: str | None
    item_id: str | None


class TagResponse(BaseModel):
    id: str
    name: str
    normalized_name: str
    user_id: str | None
    created_at: str
    is_active: bool


class TaskPatchRequest(BaseModel):
    user_id: str
    title: str | None = None
    description: str | None = None
    source_text: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_date: str | None = None
    needs_review: bool | None = None


class NotePatchRequest(BaseModel):
    user_id: str
    title: str | None = None
    text: str | None = None
    source_text: str | None = None
    needs_review: bool | None = None


class ItemReclassifyRequest(BaseModel):
    user_id: str
    target_type: Literal["task", "note"]
    title: str | None = None
    description: str | None = None
    text: str | None = None
    source_text: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_date: str | None = None
    needs_review: bool | None = None


class ItemReclassifyResponse(BaseModel):
    status: Literal["ok"] = "ok"
    item_id: str
    item_type: Literal["task", "note"]
    title: str
    needs_review: bool


class ItemDetailResponse(BaseModel):
    item_type: Literal["task", "note"]
    item: dict
    tags: list[str]
    audit_runs: list[AuditRunResponse]


class UserResponse(BaseModel):
    id: str
    created_at: str
    full_name: str | None = None
    position: str | None = None
    role: str = "user"
    email: str | None = None


class UsersListResponse(BaseModel):
    users: list[UserResponse]
    can_edit: bool
    current_user: UserResponse | None = None


class UserCreateRequest(BaseModel):
    actor_id: str
    id: str = Field(..., min_length=1, max_length=50)
    full_name: str = Field(..., min_length=1, max_length=200)
    position: str = Field(..., min_length=1, max_length=200)


class UserPatchRequest(BaseModel):
    actor_id: str
    full_name: str | None = None
    position: str | None = None


class MemoryFactResponse(BaseModel):
    id: str
    user_id: str
    created_at: str
    updated_at: str | None = None
    key: str
    value: str
    category: str
    confidence: str
    needs_review: bool
    is_active: bool
    source_type: str | None = None
    source_id: str | None = None


class MemoryCreateRequest(BaseModel):
    user_id: str
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=3, max_length=500)
    category: Literal["preference", "context", "habit", "project", "person", "other"] = "preference"
    confidence: Literal["high", "medium", "low"] = "high"
    needs_review: bool = False


class MemoryCreateResponse(BaseModel):
    status: Literal["ok"] = "ok"
    memory_id: str


class MemoryPatchRequest(BaseModel):
    user_id: str
    key: str | None = None
    value: str | None = None
    category: Literal["preference", "context", "habit", "project", "person", "other"] | None = None
    needs_review: bool | None = None
    is_active: bool | None = None


class MemoryUserRequest(BaseModel):
    user_id: str


class MemoryStatusResponse(BaseModel):
    status: Literal["ok"] = "ok"
