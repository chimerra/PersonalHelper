"""Load demo data from tests_data/ and validate against specs."""

import asyncio
import json
import sys
from pathlib import Path

from app.database import SessionLocal, init_db
from app.crud import capture_text, ensure_user, find_existing_capture

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests_data"
INPUTS_PATH = TESTS_DIR / "inputs.jsonl"
SPECS_PATH = TESTS_DIR / "specs.jsonl"


def _preview(text: str, limit: int = 72) -> str:
    one_line = text.replace("\n", " ").strip()
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _load_specs() -> dict[int, dict]:
    specs = {}
    for row in _load_jsonl(SPECS_PATH):
        specs[int(row["id"])] = row
    return specs


def _print_capture_result(result: dict) -> None:
    items = result.get("items") or []
    if result.get("duplicate"):
        print(f"    duplicate, {len(items)} item(s) already in DB")
    else:
        print(f"    created {len(items)} item(s)")
    for it in items:
        review = " · needs_review" if it.get("needs_review") else ""
        print(f"      • [{it['item_type']:4}] {it['title']}{review}")
    ignored = result.get("ignored")
    if ignored and str(ignored).strip():
        print(f"    ignored: {_preview(str(ignored), 100)}")
    mem = result.get("memory")
    if mem is not None:
        print(
            f"    memory: created={mem.get('created', 0)}, "
            f"review={mem.get('needs_review', 0)}, skipped={mem.get('skipped', 0)}"
        )


def _check_spec(case_id: int, spec: dict | None, result: dict) -> list[str]:
    """Return list of validation warnings (empty = ok)."""
    if not spec:
        return [f"#{case_id}: нет записи в specs.jsonl"]

    items = result.get("items") or []
    warnings: list[str] = []

    min_items = spec.get("expect_min_items", 1)
    if len(items) < min_items:
        warnings.append(f"ожидалось ≥{min_items} элемент(ов), получено {len(items)}")

    expect_review = spec.get("expect_needs_review")
    has_review = any(it.get("needs_review") for it in items)
    if expect_review is True and not has_review:
        warnings.append("ожидался needs_review=true, но ни один элемент не помечен")
    if expect_review is False and has_review:
        warnings.append("ожидался needs_review=false, но есть элементы на проверке")

    allowed_types = spec.get("expect_item_types")
    if allowed_types:
        for it in items:
            if it.get("item_type") not in allowed_types:
                warnings.append(
                    f"тип {it.get('item_type')} не входит в ожидаемые {allowed_types}"
                )
                break

    expect_mem = spec.get("expect_memory_created")
    if expect_mem is not None:
        mem = result.get("memory") or {}
        created_mem = mem.get("created", 0)
        if created_mem < expect_mem:
            warnings.append(
                f"ожидалось ≥{expect_mem} факт(ов) памяти, создано {created_mem}"
            )

    return warnings


async def run_seed(
    user_id: str = "u_1",
    jsonl_path: Path | None = None,
    validate: bool = True,
) -> int:
    path = jsonl_path or INPUTS_PATH
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    specs = _load_specs() if validate else {}
    inputs = _load_jsonl(path)
    if len(inputs) < 10:
        print(f"WARNING: в {path.name} только {len(inputs)} строк, нужно минимум 10")

    init_db()
    db = SessionLocal()
    ensure_user(db, user_id)
    db.commit()

    print(f"Loading {len(inputs)} inputs through capture (same as manual UI input)...")
    print(f"Specs: {SPECS_PATH.name} ({len(specs)} cases)")
    print(f"User: {user_id}\n")

    created_inputs = 0
    skipped_inputs = 0
    total_items = 0
    review_case_ids: list[int] = []
    validation_warnings: list[str] = []

    for i, data in enumerate(inputs, 1):
        case_id = int(data.get("id", i))
        text = data["text"]
        uid = data.get("user_id", user_id)
        spec = specs.get(case_id)
        label = spec["title"] if spec else f"case {case_id}"
        print(f"{case_id:2}. [{label}] {_preview(text)}")

        try:
            existing = find_existing_capture(db, text, uid)
            if existing:
                skipped_inputs += 1
                result = existing
                _print_capture_result(result)
            else:
                result = await capture_text(db, text, uid)
                created_inputs += 1
                total_items += result.get("count", len(result.get("items", [])))
                _print_capture_result(result)

            if any(it.get("needs_review") for it in result.get("items", [])):
                review_case_ids.append(case_id)

            if validate:
                for w in _check_spec(case_id, spec, result):
                    validation_warnings.append(f"#{case_id}: {w}")
        except Exception as exc:
            print(f"    ERROR: {exc}")
            validation_warnings.append(f"#{case_id}: ERROR {exc}")
        print()

    db.close()

    review_specs = [cid for cid, s in specs.items() if s.get("expect_needs_review")]
    print(
        f"Done. Inputs processed: {created_inputs}, skipped (duplicate): {skipped_inputs}, "
        f"items created this run: {total_items}, lines in file: {len(inputs)}."
    )
    print(f"Cases with needs_review in run: {review_case_ids}")
    print(f"Cases marked for review in specs: {review_specs}")

    if validate:
        if len(review_specs) < 1:
            validation_warnings.append("В specs.jsonl должно быть минимум 1 кейс с expect_needs_review=true")
        if validation_warnings:
            print("\nValidation notes:")
            for w in validation_warnings:
                print(f"  • {w}")
        else:
            print("\nValidation: all specs matched.")

    return 0 if not validation_warnings else 0


def main():
    code = asyncio.run(run_seed())
    sys.exit(code)


if __name__ == "__main__":
    main()
