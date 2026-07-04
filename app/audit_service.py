import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuditRun


def create_audit_run(
    db: Session,
    *,
    action: str,
    input_data: dict | str,
    output_data: dict | str | None = None,
    status: str = "ok",
    error: str | None = None,
    duration_ms: int = 0,
    user_id: str | None = None,
    item_type: str | None = None,
    item_id: str | None = None,
) -> AuditRun:
    if isinstance(input_data, dict):
        input_str = json.dumps(input_data, ensure_ascii=False)
    else:
        input_str = input_data

    if output_data is None:
        output_str = None
    elif isinstance(output_data, dict):
        output_str = json.dumps(output_data, ensure_ascii=False)
    else:
        output_str = output_data

    audit = AuditRun(
        id=f"audit_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        action=action,
        input=input_str,
        output=output_str,
        status=status,
        error=error,
        duration_ms=duration_ms,
        item_type=item_type,
        item_id=item_id,
    )
    db.add(audit)
    db.flush()
    return audit


def audit_to_dict(audit: AuditRun) -> dict:
    return {
        "id": audit.id,
        "user_id": audit.user_id,
        "created_at": audit.created_at,
        "action": audit.action,
        "input": audit.input,
        "output": audit.output,
        "status": audit.status,
        "error": audit.error,
        "duration_ms": audit.duration_ms,
        "item_type": audit.item_type,
        "item_id": audit.item_id,
    }
