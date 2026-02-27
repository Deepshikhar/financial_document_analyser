## worker.py
"""
Celery worker — processes financial analysis jobs asynchronously.

Start the worker with:
    celery -A worker.celery_app worker --loglevel=info --concurrency=2

The worker picks up jobs from the Redis queue, runs the CrewAI pipeline,
and stores results + status updates in the SQLite/Postgres database.
"""

import os
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from agents import *
from task import *
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  Celery app configuration
# ─────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "financial_analyser",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Reliability
    task_acks_late=True,           # ACK only after task completes (no lost jobs on crash)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # One task at a time per worker process
    # Result expiry (keep results for 24 hours)
    result_expires=86_400,
    # Timezone
    timezone="UTC",
    enable_utc=True,
)


# ─────────────────────────────────────────────
#  Helper: compute file SHA-256
# ─────────────────────────────────────────────

def _file_hash(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ─────────────────────────────────────────────
#  Celery Task
# ─────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="worker.run_analysis",
    max_retries=1,
    default_retry_delay=30,
    # ── TIME LIMITS ────────────────────────────────────────────────────────
    # Ollama runs locally and is slow — each LLM call can take 60-90 seconds.
    # 4 agents × ~90s each = ~360s minimum. Add overhead → set limits high.
    # soft_time_limit raises SoftTimeLimitExceeded (catchable) as a warning.
    # time_limit is the absolute hard kill — set it well above soft limit.
    soft_time_limit=900,      # 15 min soft limit
    time_limit=1080,           # 18 min hard kill
)
def run_analysis(self, job_id: str, query: str, file_path: str, filename: str):
    """
    Execute the full 4-agent CrewAI pipeline for a single analysis request.

    Parameters
    ----------
    job_id    : Unique job identifier (UUID).
    query     : User's natural-language financial question.
    file_path : Absolute path to the saved PDF on disk.
    filename  : Original filename supplied by the user (for display).
    """
    from billiard.exceptions import SoftTimeLimitExceeded

    # ── BUG FIX: Import agent/task OBJECTS fresh inside the worker ──────────
    # CrewAI Task objects are stateful — they store previous execution results
    # on the object itself. If you import module-level task objects, the SECOND
    # job re-uses the same dirty object from the first run, causing state leaks.
    # Fix: rebuild Agent + Task objects from scratch inside each task invocation.
    from crewai import Crew, Process
    from database import SessionLocal, AnalysisJob, DocumentRecord
    from main import extract_pdf_text
    import os

    db = SessionLocal()
    start_time = datetime.utcnow()

    try:
        # ── 1. Mark job as RUNNING ──────────────────────────────────────────
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if not job:
            return

        job.status = "running"
        job.started_at = start_time
        db.commit()

        # ── 2. Upsert DocumentRecord ────────────────────────────────────────
        path = Path(file_path)
        file_hash = _file_hash(path)
        doc = db.query(DocumentRecord).filter(
            DocumentRecord.file_hash == file_hash
        ).first()

        if not doc:
            doc = DocumentRecord(file_hash=file_hash, filename=filename)
            db.add(doc)
            db.commit()

        # ── 3. Extract PDF text ─────────────────────────────────────────────
        document_content = extract_pdf_text(path)
        doc.word_count = len(document_content.split())
        db.commit()

        # ── 4. Build fresh LLM + Agents + Tasks for this job ───────────────
        # (avoids stale state from previous job executions)

        

        llm = LLM(
            model=os.getenv("LLM_MODEL", "ollama/llama3.2"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0.2,
            max_tokens=1000,
        )
        
        # Agents
        verifier = verifier_agent(llm)
        financial_analyst = financial_analyst_agent(llm)
        investment_advisor = investment_advisor_agent(llm)
        risk_assessor = risk_assessor_agent(llm)

        # Tasks
        verification = verification_task(verifier)
        analyze_financial_document = analyze_financial_document_task(financial_analyst)
        investment_analysis  = investment_task(investment_advisor)
        risk_assessment = risk_assessment_task(risk_assessor)

        # ── 5. Run CrewAI pipeline ──────────────────────────────────────────
        crew = Crew(
            agents=[verifier, financial_analyst, investment_advisor, risk_assessor],
            tasks=[verification, analyze_financial_document, investment_analysis, risk_assessment],
            process=Process.sequential,
            verbose=True,
        )

        result = crew.kickoff(inputs={
            "query": query,
            "file_path": file_path,
            "document_content": document_content,
        })

        # ── 6. Store result ─────────────────────────────────────────────────
        finish_time = datetime.utcnow()
        duration = (finish_time - start_time).total_seconds()

        job.status = "completed"
        job.result = str(result)
        job.finished_at = finish_time
        job.duration_seconds = duration
        db.commit()

        return {"status": "completed", "job_id": job_id}

    except SoftTimeLimitExceeded:
        # ── Soft timeout — LLM is taking too long ──────────────────────────
        finish_time = datetime.utcnow()
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.status = "failed"
            job.error = (
                "Analysis timed out after 15 minutes. "
                "Ollama may be overloaded or the document is too large. "
                "Try again or reduce MAX_WORDS in tools.py."
            )
            job.finished_at = finish_time
            job.duration_seconds = (finish_time - start_time).total_seconds()
            db.commit()
        # Do NOT retry timeouts — it would just time out again
        return

    except Exception as exc:
        # ── 7. Handle failure ───────────────────────────────────────────────
        finish_time = datetime.utcnow()
        duration = (finish_time - start_time).total_seconds()

        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = finish_time
            job.duration_seconds = duration
            db.commit()

        # Only retry on rate-limit errors, NOT timeouts or connection drops
        error_str = str(exc).lower()
        if "rate_limit" in error_str:
            raise self.retry(exc=exc)

        raise

    finally:
        db.close()