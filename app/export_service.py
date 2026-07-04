"""Serialize audit and inbox data for JSON/CSV download."""

import csv
import io
import json

AUDIT_CSV_FIELDS = [
    "id",
    "user_id",
    "created_at",
    "action",
    "status",
    "error",
    "duration_ms",
    "item_type",
    "item_id",
    "input",
    "output",
]

INBOX_CSV_FIELDS = [
    "id",
    "item_type",
    "created_at",
    "title",
    "preview",
    "priority",
    "status",
    "needs_review",
    "tags",
]


def audit_to_json(runs: list[dict]) -> str:
    return json.dumps(runs, ensure_ascii=False, indent=2)


def audit_to_csv(runs: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=AUDIT_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for run in runs:
        writer.writerow({field: run.get(field, "") or "" for field in AUDIT_CSV_FIELDS})
    return output.getvalue()


def inbox_to_json(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2)


def inbox_to_csv(items: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=INBOX_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        row = {field: item.get(field, "") or "" for field in INBOX_CSV_FIELDS}
        tags = item.get("tags") or []
        row["tags"] = ", ".join(tags) if isinstance(tags, list) else str(tags)
        writer.writerow(row)
    return output.getvalue()
