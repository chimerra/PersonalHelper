import json
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai_service import analyze_text, assign_urls, finalize_tags, resolve_title
from app.audit_service import audit_to_dict, create_audit_run
from app.memory_service import (
    build_memory_context,
    persist_memory_candidates,
    resolve_priority_from_memory,
)
from app.models import AuditRun, ItemTag, MemoryFact, Note, Tag, Task, User
from app.schemas import StructuredAIResult
from app.tag_service import get_tags_for_item, link_tags_to_item

SERVICE_USER_ID = "u_admin"

DEFAULT_USERS = [
    {
        "id": SERVICE_USER_ID,
        "name": "Администратор Системы",
        "position": "Служебный пользователь",
        "role": "service",
    },
    {
        "id": "u_1",
        "name": "Иван Петров",
        "position": "Менеджер проектов",
        "role": "user",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "created_at": user.created_at,
        "full_name": user.name,
        "position": user.position,
        "role": user.role or "user",
        "email": user.email,
    }


def is_service_user(db: Session, user_id: str) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    return user is not None and user.role == "service"


def ensure_default_users(db: Session) -> None:
    for data in DEFAULT_USERS:
        user = db.query(User).filter(User.id == data["id"]).first()
        if user:
            if data["id"] == SERVICE_USER_ID and user.role != "service":
                user.role = "service"
            if not user.name:
                user.name = data["name"]
            if not user.position:
                user.position = data["position"]
            continue
        db.add(
            User(
                id=data["id"],
                created_at=now_iso(),
                name=data["name"],
                position=data["position"],
                role=data["role"],
            )
        )
    db.flush()


def ensure_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        return user
    user = User(
        id=user_id,
        created_at=now_iso(),
        name=user_id,
        position="Сотрудник",
        role="user",
    )
    db.add(user)
    db.flush()
    return user


def list_users(db: Session, actor_id: str) -> dict:
    ensure_default_users(db)
    users = db.query(User).order_by(User.created_at).all()
    actor = db.query(User).filter(User.id == actor_id).first()
    return {
        "users": [user_to_dict(u) for u in users],
        "can_edit": is_service_user(db, actor_id),
        "current_user": user_to_dict(actor) if actor else None,
    }


def get_user(db: Session, user_id: str) -> dict | None:
    user = db.query(User).filter(User.id == user_id).first()
    return user_to_dict(user) if user else None


def create_user_record(
    db: Session,
    actor_id: str,
    user_id: str,
    full_name: str,
    position: str,
) -> dict:
    if not is_service_user(db, actor_id):
        raise PermissionError("Only service user can create users")
    if db.query(User).filter(User.id == user_id).first():
        raise ValueError("User already exists")
    user = User(
        id=user_id,
        created_at=now_iso(),
        name=full_name,
        position=position,
        role="user",
    )
    db.add(user)
    db.flush()
    return user_to_dict(user)


def update_user_record(
    db: Session,
    actor_id: str,
    user_id: str,
    updates: dict,
) -> dict | None:
    if not is_service_user(db, actor_id):
        raise PermissionError("Only service user can edit users")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    if user.role == "service" and user_id != actor_id:
        raise PermissionError("Cannot edit other service users")
    if "full_name" in updates and updates["full_name"] is not None:
        user.name = updates["full_name"]
    if "position" in updates and updates["position"] is not None:
        user.position = updates["position"]
    return user_to_dict(user)


def _apply_review_flags(result: StructuredAIResult) -> tuple[StructuredAIResult, str | None]:
    """Ensure needs_review and review_reason are set consistently."""
    reason = result.review_reason
    if result.confidence == "low":
        result.needs_review = True
        reason = reason or "LOW_CONFIDENCE"
    if not result.title or not result.title.strip():
        result.needs_review = True
        reason = reason or "SCHEMA_MISMATCH"
    return result, reason


def _append_urls(body: str, urls: list[str]) -> str:
    """Append URLs that are missing from the body, preserving them verbatim."""
    body = (body or "").strip()
    for url in urls:
        if url and url not in body:
            body = f"{body}\n{url}".strip()
    return body


def _captured_item_view(db: Session, item_type: str, item_id: str, user_id: str) -> dict | None:
    if item_type == "task":
        task = db.query(Task).filter(Task.id == item_id, Task.user_id == user_id).first()
        if not task:
            return None
        return {
            "item_id": task.id,
            "item_type": "task",
            "title": task.title,
            "needs_review": task.needs_review,
        }
    if item_type == "note":
        note = db.query(Note).filter(Note.id == item_id, Note.user_id == user_id).first()
        if not note:
            return None
        return {
            "item_id": note.id,
            "item_type": "note",
            "title": note.title,
            "needs_review": note.needs_review,
        }
    return None


def find_existing_capture(db: Session, text: str, user_id: str) -> dict | None:
    """Return previously created items if the same text was already captured."""
    audits = (
        db.query(AuditRun)
        .filter(
            AuditRun.action == "capture",
            AuditRun.user_id == user_id,
            AuditRun.status == "ok",
        )
        .order_by(AuditRun.created_at.desc())
        .all()
    )
    for audit in audits:
        try:
            inp = json.loads(audit.input)
        except (json.JSONDecodeError, TypeError):
            continue
        if inp.get("text") != text or inp.get("user_id") != user_id:
            continue

        item_refs: list[tuple[str, str]] = []
        try:
            out = json.loads(audit.output) if audit.output else {}
        except (json.JSONDecodeError, TypeError):
            out = {}
        for it in out.get("items", []) if isinstance(out, dict) else []:
            if it.get("item_type") and it.get("item_id"):
                item_refs.append((it["item_type"], it["item_id"]))
        if not item_refs and audit.item_type and audit.item_id:
            item_refs.append((audit.item_type, audit.item_id))

        views = []
        for item_type, item_id in item_refs:
            view = _captured_item_view(db, item_type, item_id, user_id)
            if view:
                views.append(view)
        if views:
            return {
                "status": "ok",
                "items": views,
                "ignored": out.get("ignored") if isinstance(out, dict) else None,
                "duplicate": True,
                "count": len(views),
            }
    return None


async def capture_text(db: Session, text: str, user_id: str) -> dict:
    start = time.perf_counter()
    ensure_user(db, user_id)

    existing = find_existing_capture(db, text, user_id)
    if existing:
        structured_result = {
            "items": existing.get("items") or [],
            "ignored": existing.get("ignored"),
            "count": existing.get("count", len(existing.get("items") or [])),
        }
        first_item_id = (
            (existing.get("items") or [{}])[0].get("item_id") if existing.get("items") else None
        )
        memory_stats = persist_memory_candidates(
            db,
            user_id,
            text,
            structured_result,
            source_type="capture",
            source_id=first_item_id,
        )
        existing["memory"] = {
            "created": memory_stats["created"],
            "needs_review": memory_stats["needs_review"],
            "skipped": memory_stats["skipped"],
        }
        duration_ms = int((time.perf_counter() - start) * 1000)
        first = (existing.get("items") or [{}])[0]
        create_audit_run(
            db,
            action="capture",
            input_data={"text": text, "user_id": user_id},
            output_data=existing,
            status="ok",
            error="DUPLICATE",
            duration_ms=duration_ms,
            user_id=user_id,
            item_type=first.get("item_type"),
            item_id=first.get("item_id"),
        )
        if memory_stats["candidates"]:
            create_audit_run(
                db,
                action="MEMORY_EXTRACT",
                input_data={"text": text, "structured_result": structured_result, "duplicate": True},
                output_data={
                    "created": memory_stats["created"],
                    "needs_review": memory_stats["needs_review"],
                    "skipped": memory_stats["skipped"],
                    "candidates": memory_stats["candidates"],
                },
                duration_ms=0,
                user_id=user_id,
                item_type=first.get("item_type"),
                item_id=first.get("item_id"),
            )
        db.commit()
        existing["duplicate"] = True
        return existing

    memory_context = build_memory_context(user_id, db)
    ai_error: str | None = None
    ignored: str | None = None
    items: list[StructuredAIResult] = []
    known_tags = [t["normalized_name"] for t in get_user_tags(db, user_id)]

    try:
        analysis = await analyze_text(text, known_tags=known_tags, memory_context=memory_context)
        ignored = analysis.ignored
        for item in analysis.items:
            item, _ = _apply_review_flags(item)
            items.append(item)
    except Exception as exc:
        ai_error = str(exc)

    if not items:
        items = [
            StructuredAIResult(
                item_type="note",
                title=(text[:60] + "...") if len(text) > 60 else text,
                description="",
                priority="medium",
                tags=[],
                confidence="low",
                needs_review=True,
                review_reason="INVALID_JSON" if ai_error else "UNSTRUCTURED",
            )
        ]

    created: list[dict] = []
    review_reasons: list[str] = []
    url_assignment = assign_urls(items, text)

    for idx, structured in enumerate(items):
        needs_review = structured.needs_review
        raw_for_review = text.strip() if needs_review else None
        if structured.review_reason:
            review_reasons.append(structured.review_reason)
        extra_urls = url_assignment.get(idx, [])

        tag_source = " ".join(
            p for p in (structured.title, structured.description) if p
        ) or text
        final_tags = finalize_tags(structured.tags, tag_source)

        if structured.item_type == "task":
            item_id = f"task_{uuid.uuid4().hex[:12]}"
            description = _append_urls(structured.description or "", extra_urls) or None
            task_priority = resolve_priority_from_memory(
                structured.priority, final_tags, user_id, db
            )
            db.add(
                Task(
                    id=item_id,
                    user_id=user_id,
                    created_at=now_iso(),
                    title=resolve_title("task", structured.title, structured.description or text),
                    description=description,
                    source_text=raw_for_review,
                    due_date=structured.due_date,
                    priority=task_priority,
                    status="open",
                    needs_review=needs_review,
                )
            )
        else:
            item_id = f"note_{uuid.uuid4().hex[:12]}"
            note_body = _append_urls(structured.description or structured.title, extra_urls)
            db.add(
                Note(
                    id=item_id,
                    user_id=user_id,
                    created_at=now_iso(),
                    title=resolve_title("note", structured.title, structured.description or text),
                    text=note_body,
                    source_text=raw_for_review,
                    needs_review=needs_review,
                )
            )

        db.flush()
        link_tags_to_item(db, final_tags, user_id, structured.item_type, item_id)
        created.append(
            {
                "item_id": item_id,
                "item_type": structured.item_type,
                "title": structured.title,
                "needs_review": needs_review,
            }
        )

    duration_ms = int((time.perf_counter() - start) * 1000)
    structured_result = {
        "items": created,
        "ignored": ignored,
        "count": len(created),
    }
    first_item_id = created[0]["item_id"] if created else None
    memory_stats = persist_memory_candidates(
        db,
        user_id,
        text,
        structured_result,
        source_type="capture",
        source_id=first_item_id,
    )
    memory_block = {
        "created": memory_stats["created"],
        "needs_review": memory_stats["needs_review"],
        "skipped": memory_stats["skipped"],
    }
    response = {
        "status": "ok",
        "items": created,
        "ignored": ignored,
        "duplicate": False,
        "count": len(created),
        "memory": memory_block,
    }

    audit_error = review_reasons[0] if review_reasons else None
    if ai_error and not audit_error:
        audit_error = "INVALID_JSON"

    first = created[0]
    create_audit_run(
        db,
        action="capture",
        input_data={"text": text, "user_id": user_id},
        output_data=response,
        status="ok",
        error=audit_error,
        duration_ms=duration_ms,
        user_id=user_id,
        item_type=first["item_type"],
        item_id=first["item_id"],
    )
    create_audit_run(
        db,
        action="MEMORY_EXTRACT",
        input_data={"text": text, "structured_result": structured_result},
        output_data={
            "created": memory_stats["created"],
            "needs_review": memory_stats["needs_review"],
            "skipped": memory_stats["skipped"],
            "candidates": memory_stats["candidates"],
        },
        duration_ms=0,
        user_id=user_id,
        item_type=first["item_type"],
        item_id=first["item_id"],
    )

    db.commit()
    return response


def get_tasks(
    db: Session,
    user_id: str,
    status: str | None = None,
    needs_review: bool | None = None,
) -> list[dict]:
    q = db.query(Task).filter(Task.user_id == user_id)
    if status:
        q = q.filter(Task.status == status)
    if needs_review is not None:
        q = q.filter(Task.needs_review == needs_review)
    tasks = q.order_by(Task.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "created_at": t.created_at,
            "user_id": t.user_id,
            "title": t.title,
            "description": t.description,
            "source_text": t.source_text,
            "preview": _task_preview(t),
            "due_date": t.due_date,
            "priority": t.priority,
            "status": t.status,
            "needs_review": t.needs_review,
            "tags": get_tags_for_item(db, "task", t.id),
        }
        for t in tasks
    ]


def _task_preview(task: Task) -> str:
    body = (task.description or task.source_text or task.title or "").strip()
    if len(body) <= 120:
        return body
    return body[:117] + "..."


def get_notes(
    db: Session,
    user_id: str,
    needs_review: bool | None = None,
) -> list[dict]:
    q = db.query(Note).filter(Note.user_id == user_id)
    if needs_review is not None:
        q = q.filter(Note.needs_review == needs_review)
    notes = q.order_by(Note.created_at.desc()).all()
    return [
        {
            "id": n.id,
            "created_at": n.created_at,
            "user_id": n.user_id,
            "title": n.title,
            "text": n.text,
            "preview": n.text if len(n.text) <= 120 else n.text[:117] + "...",
            "needs_review": n.needs_review,
            "tags": get_tags_for_item(db, "note", n.id),
        }
        for n in notes
    ]


def mark_task_done(db: Session, task_id: str, user_id: str) -> str:
    """Returns: ok | not_found | needs_review"""
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        return "not_found"
    if task.needs_review:
        return "needs_review"
    if task.status != "done":
        task.status = "done"
    return "ok"


def get_inbox(
    db: Session,
    user_id: str,
    needs_review: bool | None = None,
    limit: int = 50,
) -> list[dict]:
    tasks_q = db.query(Task).filter(Task.user_id == user_id)
    notes_q = db.query(Note).filter(Note.user_id == user_id)
    if needs_review is not None:
        tasks_q = tasks_q.filter(Task.needs_review == needs_review)
        notes_q = notes_q.filter(Note.needs_review == needs_review)

    items: list[dict] = []
    for t in tasks_q.all():
        preview = _task_preview(t)
        items.append(
            {
                "id": t.id,
                "item_type": "task",
                "created_at": t.created_at,
                "title": t.title,
                "preview": preview,
                "priority": t.priority,
                "status": t.status,
                "needs_review": t.needs_review,
                "tags": get_tags_for_item(db, "task", t.id),
            }
        )
    for n in notes_q.all():
        preview = n.text if len(n.text) <= 100 else n.text[:97] + "..."
        items.append(
            {
                "id": n.id,
                "item_type": "note",
                "created_at": n.created_at,
                "title": n.title,
                "preview": preview,
                "priority": None,
                "status": None,
                "needs_review": n.needs_review,
                "tags": get_tags_for_item(db, "note", n.id),
            }
        )

    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:limit]


def get_item_detail(db: Session, item_type: str, item_id: str, user_id: str) -> dict | None:
    if item_type == "task":
        task = (
            db.query(Task)
            .filter(Task.id == item_id, Task.user_id == user_id)
            .first()
        )
        if not task:
            return None
        item_data = {
            "id": task.id,
            "created_at": task.created_at,
            "user_id": task.user_id,
            "title": task.title,
            "description": task.description,
            "source_text": task.source_text,
            "due_date": task.due_date,
            "priority": task.priority,
            "status": task.status,
            "needs_review": task.needs_review,
        }
    elif item_type == "note":
        note = (
            db.query(Note)
            .filter(Note.id == item_id, Note.user_id == user_id)
            .first()
        )
        if not note:
            return None
        item_data = {
            "id": note.id,
            "created_at": note.created_at,
            "user_id": note.user_id,
            "title": note.title,
            "text": note.text,
            "source_text": note.source_text,
            "needs_review": note.needs_review,
        }
    else:
        return None

    audits = (
        db.query(AuditRun)
        .filter(AuditRun.item_type == item_type, AuditRun.item_id == item_id)
        .order_by(AuditRun.created_at.desc())
        .all()
    )

    return {
        "item_type": item_type,
        "item": item_data,
        "tags": get_tags_for_item(db, item_type, item_id),
        "audit_runs": [audit_to_dict(a) for a in audits],
    }


def _move_item_tags(db: Session, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
    db.query(ItemTag).filter(
        ItemTag.item_type == from_type,
        ItemTag.item_id == from_id,
    ).update(
        {"item_type": to_type, "item_id": to_id},
        synchronize_session=False,
    )


def _move_audit_item_refs(
    db: Session, from_type: str, from_id: str, to_type: str, to_id: str
) -> None:
    db.query(AuditRun).filter(
        AuditRun.item_type == from_type,
        AuditRun.item_id == from_id,
    ).update(
        {"item_type": to_type, "item_id": to_id},
        synchronize_session=False,
    )


def reclassify_item(
    db: Session,
    from_type: str,
    item_id: str,
    user_id: str,
    target_type: str,
    updates: dict,
) -> tuple[dict | None, str | None]:
    """Convert task<->note for items that need review. Returns (result, error_code)."""
    if from_type == target_type:
        return None, "SAME_TYPE"
    if from_type not in ("task", "note") or target_type not in ("task", "note"):
        return None, "INVALID_TYPE"

    if from_type == "task":
        task = db.query(Task).filter(Task.id == item_id, Task.user_id == user_id).first()
        if not task:
            return None, "NOT_FOUND"
        if not task.needs_review:
            return None, "NOT_REVIEW"

        title = updates.get("title") or task.title
        description = updates.get("description") if "description" in updates else task.description
        text = updates.get("text") or description or task.source_text or title
        source_text = updates.get("source_text") if "source_text" in updates else task.source_text
        needs_review = (
            updates["needs_review"] if updates.get("needs_review") is not None else task.needs_review
        )

        new_id = f"note_{uuid.uuid4().hex[:12]}"
        db.add(
            Note(
                id=new_id,
                user_id=user_id,
                created_at=now_iso(),
                title=title,
                text=text,
                source_text=source_text,
                needs_review=needs_review,
            )
        )
        _move_item_tags(db, "task", item_id, "note", new_id)
        _move_audit_item_refs(db, "task", item_id, "note", new_id)
        db.delete(task)
        db.flush()
        return {
            "item_id": new_id,
            "item_type": "note",
            "title": title,
            "needs_review": needs_review,
        }, None

    note = db.query(Note).filter(Note.id == item_id, Note.user_id == user_id).first()
    if not note:
        return None, "NOT_FOUND"
    if not note.needs_review:
        return None, "NOT_REVIEW"

    title = updates.get("title") or note.title
    description = updates.get("description") or note.text
    text = updates.get("text") or note.text
    source_text = updates.get("source_text") if "source_text" in updates else note.source_text
    needs_review = (
        updates["needs_review"] if updates.get("needs_review") is not None else note.needs_review
    )
    priority = updates.get("priority") or "medium"
    due_date = updates.get("due_date") if "due_date" in updates else None

    new_id = f"task_{uuid.uuid4().hex[:12]}"
    db.add(
        Task(
            id=new_id,
            user_id=user_id,
            created_at=now_iso(),
            title=title,
            description=description,
            source_text=source_text,
            due_date=due_date,
            priority=priority,
            status="open",
            needs_review=needs_review,
        )
    )
    _move_item_tags(db, "note", item_id, "task", new_id)
    _move_audit_item_refs(db, "note", item_id, "task", new_id)
    db.delete(note)
    db.flush()
    return {
        "item_id": new_id,
        "item_type": "task",
        "title": title,
        "needs_review": needs_review,
    }, None


def patch_task(
    db: Session,
    task_id: str,
    user_id: str,
    updates: dict,
) -> Task | None:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        return None
    for field in ("title", "description", "source_text", "priority", "due_date", "needs_review"):
        if field in updates and updates[field] is not None:
            setattr(task, field, updates[field])
    return task


def patch_note(
    db: Session,
    note_id: str,
    user_id: str,
    updates: dict,
) -> Note | None:
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user_id).first()
    if not note:
        return None
    for field in ("title", "text", "source_text", "needs_review"):
        if field in updates and updates[field] is not None:
            setattr(note, field, updates[field])
    return note


def _delete_item_tags(db: Session, item_type: str, item_id: str) -> None:
    db.query(ItemTag).filter(
        ItemTag.item_type == item_type,
        ItemTag.item_id == item_id,
    ).delete(synchronize_session=False)


def delete_task(db: Session, task_id: str, user_id: str) -> tuple[str, dict | None]:
    """Returns: (status, snapshot) where status is ok | not_found | done."""
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        return "not_found", None
    snapshot = {
        "task_id": task.id,
        "title": task.title,
        "source_text": task.source_text,
        "priority": task.priority,
        "due_date": task.due_date,
        "status": task.status,
        "needs_review": task.needs_review,
    }
    if task.status == "done":
        return "done", snapshot
    _delete_item_tags(db, "task", task_id)
    db.delete(task)
    return "ok", snapshot


def delete_note(db: Session, note_id: str, user_id: str) -> tuple[str, dict | None]:
    """Returns: (status, snapshot) where status is ok | not_found | needs_review."""
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user_id).first()
    if not note:
        return "not_found", None
    snapshot = {
        "note_id": note.id,
        "title": note.title,
        "text": note.text,
        "needs_review": note.needs_review,
    }
    if note.needs_review:
        return "needs_review", snapshot
    _delete_item_tags(db, "note", note_id)
    db.delete(note)
    return "ok", snapshot


READ_AUDIT_ACTIONS = frozenset(
    {
        "get_tasks",
        "get_notes",
        "get_inbox",
        "get_item",
        "get_audit",
        "get_tags",
        "list_users",
        "GET /memory",
        "get_memory",
    }
)


def get_audit_runs(
    db: Session,
    user_id: str | None = None,
    status: str | None = None,
    only_errors: bool = False,
    actions_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    q = db.query(AuditRun)
    if user_id:
        q = q.filter(AuditRun.user_id == user_id)
    if status:
        q = q.filter(AuditRun.status == status)
    if only_errors:
        q = q.filter(AuditRun.error.isnot(None))
    if actions_only:
        q = q.filter(~AuditRun.action.in_(READ_AUDIT_ACTIONS))
    audits = q.order_by(AuditRun.created_at.desc()).limit(limit).all()
    return [audit_to_dict(a) for a in audits]


def get_user_tags(db: Session, user_id: str) -> list[dict]:
    tags = (
        db.query(Tag)
        .filter((Tag.user_id == user_id) | (Tag.user_id.is_(None)))
        .order_by(Tag.normalized_name)
        .all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "normalized_name": t.normalized_name,
            "user_id": t.user_id,
            "created_at": t.created_at,
            "is_active": t.is_active,
        }
        for t in tags
    ]


def reset_database(db: Session) -> dict:
    """Delete all user data and start with empty tables."""
    db.query(ItemTag).delete()
    db.query(AuditRun).delete()
    db.query(MemoryFact).delete()
    db.query(Task).delete()
    db.query(Note).delete()
    db.query(Tag).delete()
    db.query(User).delete()
    db.commit()
    ensure_default_users(db)
    db.commit()
    return {"status": "ok", "message": "Все данные удалены"}
