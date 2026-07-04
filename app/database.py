import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_users_table()
    _migrate_notes_table()
    _migrate_tasks_table()
    _migrate_memory_facts_table()
    _seed_default_users()


def _migrate_notes_table():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "notes" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("notes")}
    with engine.begin() as conn:
        if "title" not in cols:
            conn.execute(text("ALTER TABLE notes ADD COLUMN title TEXT"))
            conn.execute(
                text(
                    "UPDATE notes SET title = substr(text, 1, 80) WHERE title IS NULL OR title = ''"
                )
            )
        if "source_text" not in cols:
            conn.execute(text("ALTER TABLE notes ADD COLUMN source_text TEXT"))


def _migrate_tasks_table():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "tasks" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("tasks")}
    with engine.begin() as conn:
        if "source_text" not in cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN source_text TEXT"))
        if "description" not in cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN description TEXT"))


def _migrate_users_table():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    with engine.begin() as conn:
        if "position" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN position TEXT"))
        if "role" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"))


def _migrate_memory_facts_table():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "memory_facts" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("memory_facts")}
    with engine.begin() as conn:
        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE memory_facts ADD COLUMN updated_at TEXT"))
        if "category" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE memory_facts ADD COLUMN category TEXT NOT NULL DEFAULT 'other'"
                )
            )
        if "source_type" not in cols:
            conn.execute(text("ALTER TABLE memory_facts ADD COLUMN source_type TEXT"))
        if "source_id" not in cols:
            conn.execute(text("ALTER TABLE memory_facts ADD COLUMN source_id TEXT"))
        if "confidence" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE memory_facts ADD COLUMN confidence TEXT NOT NULL DEFAULT 'medium'"
                )
            )
        if "needs_review" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE memory_facts ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "is_active" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE memory_facts ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
                )
            )


def _seed_default_users():
    from app.crud import ensure_default_users

    db = SessionLocal()
    try:
        ensure_default_users(db)
        db.commit()
    finally:
        db.close()
