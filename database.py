## database.py
"""
Database layer using SQLAlchemy.
Supports SQLite for local dev (default) and PostgreSQL for production.

Set DATABASE_URL in .env to switch:
  SQLite  (default): sqlite:///./financial_analyser.db
  Postgres         : postgresql://user:pass@localhost:5432/financial_analyser
"""

import os
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Enum,
    Float,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./financial_analyser.db")

# connect_args only needed for SQLite (thread safety for FastAPI)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─────────────────────────────────────────────
#  ORM Models
# ─────────────────────────────────────────────

class AnalysisJob(Base):
    """
    Tracks every analysis request submitted via the API.
    One row per /analyse call.
    """
    __tablename__ = "analysis_jobs"

    id          = Column(Integer, primary_key=True, index=True)
    job_id      = Column(String(64), unique=True, index=True, nullable=False)
    query       = Column(Text, nullable=False)
    filename    = Column(String(256), nullable=True)
    status      = Column(
        Enum("queued", "running", "completed", "failed", name="job_status"),
        default="queued",
        nullable=False,
    )
    result      = Column(Text, nullable=True)   # Full analysis text on success
    error       = Column(Text, nullable=True)   # Error message on failure
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    # Duration in seconds (set on completion for quick reporting)
    duration_seconds = Column(Float, nullable=True)


class DocumentRecord(Base):
    """
    Stores metadata about every unique PDF that has been analysed.
    Deduplication is done by SHA-256 hash of the file content.
    """
    __tablename__ = "document_records"

    id          = Column(Integer, primary_key=True, index=True)
    file_hash   = Column(String(64), unique=True, index=True, nullable=False)
    filename    = Column(String(256), nullable=True)
    word_count  = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def init_db():
    """Create all tables (idempotent — safe to call on every startup)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session, always closes on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()