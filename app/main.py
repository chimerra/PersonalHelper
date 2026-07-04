import json
import logging
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai_service import analyze_text
from app.audit_service import create_audit_run
from app.crud import (
    capture_text,
    create_user_record,
    delete_note,
    delete_task,
    ensure_user,
    get_audit_runs,
    get_inbox,
    get_item_detail,
    get_notes,
    get_tasks,
    get_user,
    get_user_tags,
    list_users,
    mark_task_done,
    patch_note,
    patch_task,
    reclassify_item,
    reset_database,
    update_user_record,
)
from app.memory_service import (
    create_memory_fact,
    deactivate_memory_fact,
    delete_memory_fact,
    get_user_memory,
    memory_fact_to_dict,
    patch_memory_fact,
)
from app.database import get_db, init_db
from app.export_service import audit_to_csv, audit_to_json, inbox_to_csv, inbox_to_json
from app.schemas import (
    AnalysisResult,
    CaptureRequest,
    CaptureResponse,
    ItemDeleteRequest,
    ItemDeleteResponse,
    ItemReclassifyRequest,
    ItemReclassifyResponse,
    NotePatchRequest,
    StructureRequest,
    TaskDoneRequest,
    TaskDoneResponse,
    TaskPatchRequest,
    MemoryCreateRequest,
    MemoryCreateResponse,
    MemoryFactResponse,
    MemoryPatchRequest,
    MemoryStatusResponse,
    MemoryUserRequest,
    ResetResponse,
    UserCreateRequest,
    UserPatchRequest,
    UsersListResponse,
    UserResponse,
)

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Персональный помощник", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


@app.on_event("startup")
def on_startup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:     %(message)s",
    )
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/capture", response_model=CaptureResponse)
async def api_capture(body: CaptureRequest, db: Session = Depends(get_db)):
    result = await capture_text(db, body.text, body.user_id)
    return result


def _structure_review(item: AnalysisResult) -> AnalysisResult:
    for it in item.items:
        if it.confidence == "low" or not (it.title or "").strip():
            it.needs_review = True
            it.review_reason = it.review_reason or "LOW_CONFIDENCE"
    return item


@app.post("/reset", response_model=ResetResponse)
def api_reset(db: Session = Depends(get_db)):
    start = time.perf_counter()
    result = reset_database(db)
    duration_ms = int((time.perf_counter() - start) * 1000)
    create_audit_run(
        db,
        action="reset_database",
        input_data={},
        output_data=result,
        duration_ms=duration_ms,
    )
    db.commit()
    return result


@app.get("/tasks")
def api_get_tasks(
    user_id: str = Query(...),
    status: str | None = Query(None),
    needs_review: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    ensure_user(db, user_id)
    tasks = get_tasks(db, user_id, status=status, needs_review=needs_review)
    return tasks


@app.get("/notes")
def api_get_notes(
    user_id: str = Query(...),
    needs_review: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    ensure_user(db, user_id)
    notes = get_notes(db, user_id, needs_review=needs_review)
    return notes


@app.post("/tasks/{task_id}/done", response_model=TaskDoneResponse)
def api_task_done(
    task_id: str,
    body: TaskDoneRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    result = mark_task_done(db, task_id, body.user_id)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if result == "not_found":
        create_audit_run(
            db,
            action="task_done",
            input_data={"task_id": task_id, "user_id": body.user_id},
            output_data={"error": "not_found"},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="task",
            item_id=task_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Task not found")

    if result == "needs_review":
        create_audit_run(
            db,
            action="task_done",
            input_data={"task_id": task_id, "user_id": body.user_id},
            output_data={"error": "needs_review"},
            status="error",
            error="NEEDS_REVIEW",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="task",
            item_id=task_id,
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Нельзя выполнить задачу, пока она требует проверки",
        )

    response = {"status": "ok"}
    create_audit_run(
        db,
        action="task_done",
        input_data={"task_id": task_id, "user_id": body.user_id},
        output_data=response,
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_type="task",
        item_id=task_id,
    )
    db.commit()
    return response


@app.post("/ai/structure", response_model=AnalysisResult)
async def api_structure(body: StructureRequest, db: Session = Depends(get_db)):
    start = time.perf_counter()
    try:
        result = _structure_review(await analyze_text(body.text))
        duration_ms = int((time.perf_counter() - start) * 1000)
        create_audit_run(
            db,
            action="ai_structure",
            input_data={"text": body.text},
            output_data={"count": len(result.items), "ignored": result.ignored},
            duration_ms=duration_ms,
        )
        db.commit()
        return result
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        create_audit_run(
            db,
            action="ai_structure",
            input_data={"text": body.text},
            status="error",
            error=str(exc),
            duration_ms=duration_ms,
        )
        db.commit()
        raise HTTPException(status_code=500, detail="AI structuring failed") from exc


@app.get("/inbox")
def api_inbox(
    user_id: str = Query(...),
    needs_review: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    ensure_user(db, user_id)
    items = get_inbox(db, user_id, needs_review=needs_review)
    return items


@app.get("/items/{item_type}/{item_id}")
def api_item_detail(
    item_type: str,
    item_id: str,
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    detail = get_item_detail(db, item_type, item_id, user_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Item not found")
    return detail


@app.post("/items/{item_type}/{item_id}/reclassify", response_model=ItemReclassifyResponse)
def api_reclassify_item(
    item_type: str,
    item_id: str,
    body: ItemReclassifyRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    updates = body.model_dump(exclude={"user_id", "target_type"}, exclude_none=True)
    result, error = reclassify_item(
        db, item_type, item_id, body.user_id, body.target_type, updates
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    if error == "NOT_FOUND":
        create_audit_run(
            db,
            action="reclassify_item",
            input_data={"item_type": item_type, "item_id": item_id, **body.model_dump()},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type=item_type,
            item_id=item_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Item not found")
    if error == "NOT_REVIEW":
        create_audit_run(
            db,
            action="reclassify_item",
            input_data={"item_type": item_type, "item_id": item_id, **body.model_dump()},
            status="error",
            error="NOT_REVIEW",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type=item_type,
            item_id=item_id,
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Тип можно менять только у элементов, требующих проверки",
        )
    if error:
        raise HTTPException(status_code=400, detail=error)

    create_audit_run(
        db,
        action="reclassify_item",
        input_data={
            "from_type": item_type,
            "from_id": item_id,
            "target_type": body.target_type,
            **body.model_dump(),
        },
        output_data=result,
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_type=result["item_type"],
        item_id=result["item_id"],
    )
    db.commit()
    return {"status": "ok", **result}


@app.patch("/tasks/{task_id}")
def api_patch_task(
    task_id: str,
    body: TaskPatchRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    updates = body.model_dump(exclude={"user_id"}, exclude_none=True)
    task = patch_task(db, task_id, body.user_id, updates)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not task:
        create_audit_run(
            db,
            action="patch_task",
            input_data={"task_id": task_id, **body.model_dump()},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="task",
            item_id=task_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Task not found")

    output = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "source_text": task.source_text,
        "priority": task.priority,
        "due_date": task.due_date,
        "needs_review": task.needs_review,
    }
    create_audit_run(
        db,
        action="patch_task",
        input_data={"task_id": task_id, **body.model_dump()},
        output_data=output,
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_type="task",
        item_id=task_id,
    )
    db.commit()
    return output


@app.patch("/notes/{note_id}")
def api_patch_note(
    note_id: str,
    body: NotePatchRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    updates = body.model_dump(exclude={"user_id"}, exclude_none=True)
    note = patch_note(db, note_id, body.user_id, updates)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not note:
        create_audit_run(
            db,
            action="patch_note",
            input_data={"note_id": note_id, **body.model_dump()},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="note",
            item_id=note_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Note not found")

    output = {"id": note.id, "title": note.title, "text": note.text, "needs_review": note.needs_review}
    create_audit_run(
        db,
        action="patch_note",
        input_data={"note_id": note_id, **body.model_dump()},
        output_data=output,
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_type="note",
        item_id=note_id,
    )
    db.commit()
    return output


@app.delete("/tasks/{task_id}", response_model=ItemDeleteResponse)
def api_delete_task(
    task_id: str,
    body: ItemDeleteRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    result, snapshot = delete_task(db, task_id, body.user_id)
    duration_ms = int((time.perf_counter() - start) * 1000)
    audit_input = {"user_id": body.user_id, **(snapshot or {"task_id": task_id})}
    if result == "not_found":
        create_audit_run(
            db,
            action="delete_task",
            input_data=audit_input,
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="task",
            item_id=task_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Task not found")
    if result == "done":
        create_audit_run(
            db,
            action="delete_task",
            input_data=audit_input,
            status="error",
            error="TASK_DONE",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="task",
            item_id=task_id,
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить выполненную задачу",
        )
    create_audit_run(
        db,
        action="delete_task",
        input_data=audit_input,
        output_data={"status": "ok", "deleted": snapshot},
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_type="task",
        item_id=task_id,
    )
    db.commit()
    return {"status": "ok"}


@app.delete("/notes/{note_id}", response_model=ItemDeleteResponse)
def api_delete_note(
    note_id: str,
    body: ItemDeleteRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    result, snapshot = delete_note(db, note_id, body.user_id)
    duration_ms = int((time.perf_counter() - start) * 1000)
    audit_input = {"user_id": body.user_id, **(snapshot or {"note_id": note_id})}
    if result == "not_found":
        create_audit_run(
            db,
            action="delete_note",
            input_data=audit_input,
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="note",
            item_id=note_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Note not found")
    if result == "needs_review":
        create_audit_run(
            db,
            action="delete_note",
            input_data=audit_input,
            status="error",
            error="NEEDS_REVIEW",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_type="note",
            item_id=note_id,
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить заметку, пока она требует проверки",
        )
    create_audit_run(
        db,
        action="delete_note",
        input_data=audit_input,
        output_data={"status": "ok", "deleted": snapshot},
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_type="note",
        item_id=note_id,
    )
    db.commit()
    return {"status": "ok"}


@app.get("/audit")
def api_audit(
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    only_errors: bool = Query(False),
    actions_only: bool = Query(True),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    runs = get_audit_runs(
        db,
        user_id=user_id,
        status=status,
        only_errors=only_errors,
        actions_only=actions_only,
        limit=limit,
    )
    return runs


@app.get("/audit/export")
def api_audit_export(
    user_id: str = Query(...),
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    status: str | None = Query(None),
    only_errors: bool = Query(False),
    actions_only: bool = Query(True),
    limit: int = Query(500, le=500),
    db: Session = Depends(get_db),
):
    runs = get_audit_runs(
        db,
        user_id=user_id,
        status=status,
        only_errors=only_errors,
        actions_only=actions_only,
        limit=limit,
    )
    filename = f"audit_{user_id}.{fmt}"
    if fmt == "csv":
        content = audit_to_csv(runs)
        media_type = "text/csv; charset=utf-8"
    else:
        content = audit_to_json(runs)
        media_type = "application/json; charset=utf-8"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/inbox")
def api_export_inbox(
    user_id: str = Query(...),
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    needs_review: bool | None = Query(None),
    limit: int = Query(500, le=500),
    db: Session = Depends(get_db),
):
    ensure_user(db, user_id)
    items = get_inbox(db, user_id, needs_review=needs_review, limit=limit)
    filename = f"inbox_{user_id}.{fmt}"
    if fmt == "csv":
        content = inbox_to_csv(items)
        media_type = "text/csv; charset=utf-8"
    else:
        content = inbox_to_json(items)
        media_type = "application/json; charset=utf-8"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/tags")
def api_tags(user_id: str = Query(...), db: Session = Depends(get_db)):
    ensure_user(db, user_id)
    tags = get_user_tags(db, user_id)
    return tags


@app.get("/users", response_model=UsersListResponse)
def api_list_users(actor_id: str = Query(...), db: Session = Depends(get_db)):
    result = list_users(db, actor_id)
    return result


@app.get("/users/{user_id}", response_model=UserResponse)
def api_get_user(user_id: str, db: Session = Depends(get_db)):
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/users", response_model=UserResponse)
def api_create_user(body: UserCreateRequest, db: Session = Depends(get_db)):
    start = time.perf_counter()
    try:
        user = create_user_record(
            db, body.actor_id, body.id, body.full_name, body.position
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    duration_ms = int((time.perf_counter() - start) * 1000)
    create_audit_run(
        db,
        action="create_user",
        input_data=body.model_dump(),
        output_data=user,
        duration_ms=duration_ms,
        user_id=body.actor_id,
    )
    db.commit()
    return user


@app.patch("/users/{user_id}", response_model=UserResponse)
def api_patch_user(
    user_id: str,
    body: UserPatchRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    try:
        user = update_user_record(
            db,
            body.actor_id,
            user_id,
            body.model_dump(exclude={"actor_id"}, exclude_none=True),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not user:
        create_audit_run(
            db,
            action="patch_user",
            input_data={"user_id": user_id, **body.model_dump()},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.actor_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="User not found")
    create_audit_run(
        db,
        action="patch_user",
        input_data={"user_id": user_id, **body.model_dump()},
        output_data=user,
        duration_ms=duration_ms,
        user_id=body.actor_id,
    )
    db.commit()
    return user


@app.get("/memory", response_model=list[MemoryFactResponse])
def api_get_memory(
    user_id: str = Query(...),
    include_inactive: bool = Query(False),
    needs_review: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    ensure_user(db, user_id)
    facts = get_user_memory(
        db,
        user_id,
        include_inactive=include_inactive,
        needs_review=needs_review,
    )
    result = [memory_fact_to_dict(f) for f in facts]
    duration_ms = int((time.perf_counter() - start) * 1000)
    create_audit_run(
        db,
        action="GET /memory",
        input_data={
            "user_id": user_id,
            "include_inactive": include_inactive,
            "needs_review": needs_review,
        },
        output_data={"count": len(result)},
        duration_ms=duration_ms,
        user_id=user_id,
    )
    db.commit()
    return result


@app.post("/memory", response_model=MemoryCreateResponse)
def api_create_memory(body: MemoryCreateRequest, db: Session = Depends(get_db)):
    start = time.perf_counter()
    ensure_user(db, body.user_id)
    fact = create_memory_fact(
        db,
        user_id=body.user_id,
        key=body.key,
        value=body.value,
        category=body.category,
        confidence=body.confidence,
        source_type="manual",
        source_id=None,
        needs_review=body.needs_review,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    create_audit_run(
        db,
        action="POST /memory",
        input_data=body.model_dump(),
        output_data={"memory_id": fact.id},
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_id=fact.id,
    )
    db.commit()
    return {"status": "ok", "memory_id": fact.id}


@app.patch("/memory/{memory_id}", response_model=MemoryFactResponse)
def api_patch_memory(
    memory_id: str,
    body: MemoryPatchRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    updates = body.model_dump(exclude={"user_id"}, exclude_none=True)
    fact = patch_memory_fact(db, memory_id, body.user_id, updates)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not fact:
        create_audit_run(
            db,
            action="PATCH /memory/{id}",
            input_data={"memory_id": memory_id, **body.model_dump()},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_id=memory_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Memory fact not found")
    output = memory_fact_to_dict(fact)
    create_audit_run(
        db,
        action="PATCH /memory/{id}",
        input_data={"memory_id": memory_id, **body.model_dump()},
        output_data=output,
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_id=memory_id,
    )
    db.commit()
    return output


@app.post("/memory/{memory_id}/deactivate", response_model=MemoryStatusResponse)
def api_deactivate_memory(
    memory_id: str,
    body: MemoryUserRequest,
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    fact = deactivate_memory_fact(db, memory_id, body.user_id)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not fact:
        create_audit_run(
            db,
            action="POST /memory/{id}/deactivate",
            input_data={"memory_id": memory_id, **body.model_dump()},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=body.user_id,
            item_id=memory_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Memory fact not found")
    create_audit_run(
        db,
        action="POST /memory/{id}/deactivate",
        input_data={"memory_id": memory_id, **body.model_dump()},
        output_data={"status": "ok", "is_active": False},
        duration_ms=duration_ms,
        user_id=body.user_id,
        item_id=memory_id,
    )
    db.commit()
    return {"status": "ok"}


@app.delete("/memory/{memory_id}", response_model=MemoryStatusResponse)
def api_delete_memory(
    memory_id: str,
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    ok = delete_memory_fact(db, memory_id, user_id)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if not ok:
        create_audit_run(
            db,
            action="DELETE /memory/{id}",
            input_data={"memory_id": memory_id, "user_id": user_id},
            status="error",
            error="NOT_FOUND",
            duration_ms=duration_ms,
            user_id=user_id,
            item_id=memory_id,
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Memory fact not found")
    create_audit_run(
        db,
        action="DELETE /memory/{id}",
        input_data={"memory_id": memory_id, "user_id": user_id},
        output_data={"status": "ok"},
        duration_ms=duration_ms,
        user_id=user_id,
        item_id=memory_id,
    )
    db.commit()
    return {"status": "ok"}
