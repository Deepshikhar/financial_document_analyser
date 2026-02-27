## main.py
"""
Financial Document Analyser — FastAPI application

Architecture (with bonus features):
  POST /analyse  →  saves PDF to disk  →  enqueues Celery job  →  returns job_id
  GET  /jobs/{job_id}  →  poll job status + result from DB
  GET  /jobs            →  list all jobs (paginated)
  GET  /documents       →  list unique documents analysed
  GET  /health          →  liveness probe
  GET  /dashboard       →  browser-viewable job dashboard
"""

import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, HTMLResponse
from pypdf import PdfReader
from sqlalchemy.orm import Session

from database import init_db, get_db, AnalysisJob, DocumentRecord
from tools import _clean_and_truncate
from worker import run_analysis  # Celery task

# ─────────────────────────────────────────────
#  App setup
# ─────────────────────────────────────────────

app = FastAPI(
    title="Financial Document Analyser",
    description=(
        "AI-powered financial document analysis using CrewAI agents.\n\n"
        "Requests are processed **asynchronously** via a Celery/Redis queue.\n"
        "Submit a job with POST /analyse, then poll GET /jobs/{job_id} for results."
    ),
    version="2.0.0",
)

UPLOAD_DIR = Path("data")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.on_event("startup")
def on_startup():
    """Create DB tables on first run (idempotent)."""
    init_db()


# ─────────────────────────────────────────────
#  PDF helpers
# ─────────────────────────────────────────────

def extract_pdf_text(path: Path) -> str:
    """Read PDF once, clean, truncate, and escape curly braces for CrewAI."""
    reader = PdfReader(str(path))
    raw = ""
    for page in reader.pages:
        content = page.extract_text()
        if content:
            raw += content + "\n"

    if not raw.strip():
        raise ValueError("No text could be extracted (PDF may be image-based).")

    truncated = _clean_and_truncate(raw)

    # BUG FIX: Escape curly braces so CrewAI's str.format() doesn't crash
    truncated = truncated.replace("{", "{{").replace("}", "}}")
    return truncated


# ─────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────

@app.post(
    "/analyse",
    summary="Upload a PDF and enqueue a full financial analysis",
    response_description="Job ID to poll for results",
    status_code=202,
)
async def analyse_document(
    query: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Submit a financial document for analysis.

    - Saves the uploaded PDF to disk.
    - Creates a DB record with status **queued**.
    - Enqueues the 4-agent CrewAI pipeline as a background Celery task.
    - Returns a `job_id` immediately — poll **GET /jobs/{job_id}** for results.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # BUG FIX: Save PDF with a unique name so concurrent uploads don't overwrite
    # each other. Old code used a hardcoded "sample.pdf" causing race conditions.
    job_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{job_id}.pdf"

    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Validate the PDF is readable before queuing
    try:
        extract_pdf_text(save_path)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

    # Persist job record in DB
    job = AnalysisJob(
        job_id=job_id,
        query=query,
        filename=file.filename,
        status="queued",
    )
    db.add(job)
    db.commit()

    # Enqueue Celery task (non-blocking — returns immediately)
    run_analysis.apply_async(
        kwargs={
            "job_id": job_id,
            "query": query,
            "file_path": str(save_path.resolve()),
            "filename": file.filename,
        },
        task_id=job_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "queued",
            "job_id": job_id,
            "message": f"Analysis queued. Poll GET /jobs/{job_id} for results.",
        },
    )


@app.get("/jobs/{job_id}", summary="Get status and result of an analysis job")
def get_job(job_id: str, db: Session = Depends(get_db)):
    """
    Poll this endpoint after submitting a job.

    - **queued** / **running** → check back in a few seconds.
    - **completed** → `result` field contains the full analysis.
    - **failed** → `error` field describes what went wrong.
    """
    job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return {
        "job_id": job.job_id,
        "query": job.query,
        "filename": job.filename,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_seconds": job.duration_seconds,
    }


@app.get("/jobs", summary="List all analysis jobs (paginated)")
def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter: queued/running/completed/failed"),
    db: Session = Depends(get_db),
):
    """Returns a paginated list of all analysis jobs, newest first."""
    q = db.query(AnalysisJob).order_by(AnalysisJob.created_at.desc())
    if status:
        q = q.filter(AnalysisJob.status == status)

    total = q.count()
    jobs = q.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "jobs": [
            {
                "job_id": j.job_id,
                "query": j.query,
                "filename": j.filename,
                "status": j.status,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "duration_seconds": j.duration_seconds,
            }
            for j in jobs
        ],
    }


@app.get("/documents", summary="List all unique documents analysed")
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Returns metadata for every unique PDF processed (deduplicated by SHA-256)."""
    total = db.query(DocumentRecord).count()
    docs = (
        db.query(DocumentRecord)
        .order_by(DocumentRecord.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "file_hash": d.file_hash,
                "word_count": d.word_count,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            }
            for d in docs
        ],
    }


@app.delete("/jobs/{job_id}", summary="Delete a job record", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Remove a job record from the database (does not cancel a running task)."""
    job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    db.delete(job)
    db.commit()
    return


@app.get("/health", summary="Liveness probe")
def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────
#  Visual Dashboard  →  http://localhost:8000/dashboard
# ─────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(db: Session = Depends(get_db)):
    """
    Browser-viewable dashboard showing all jobs and their results.
    Auto-refreshes every 10 seconds while any job is queued/running.
    """
    jobs = db.query(AnalysisJob).order_by(AnalysisJob.created_at.desc()).limit(50).all()
    any_active = any(j.status in ("queued", "running") for j in jobs)
    refresh_meta = '<meta http-equiv="refresh" content="10">' if any_active else ""

    rows = ""
    for j in jobs:
        status_color = {
            "queued": "#f59e0b", "running": "#3b82f6",
            "completed": "#10b981", "failed": "#ef4444",
        }.get(j.status, "#6b7280")

        result_html = ""
        if j.status == "completed" and j.result:
            escaped = j.result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            result_html = f'<details><summary style="cursor:pointer;color:#3b82f6">View Report</summary><pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px;font-size:12px;margin-top:8px">{escaped}</pre></details>'
        elif j.status == "failed" and j.error:
            escaped_err = j.error.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            result_html = f'<details><summary style="cursor:pointer;color:#ef4444">View Error</summary><pre style="white-space:pre-wrap;background:#fef2f2;padding:12px;border-radius:6px;font-size:12px;margin-top:8px">{escaped_err}</pre></details>'

        duration = f"{j.duration_seconds:.1f}s" if j.duration_seconds else "—"
        created = j.created_at.strftime("%Y-%m-%d %H:%M:%S") if j.created_at else "—"

        rows += f"""
        <tr>
          <td style="padding:12px;font-family:monospace;font-size:12px;color:#6b7280">{j.job_id[:8]}…</td>
          <td style="padding:12px;max-width:250px;word-break:break-word">{j.query}</td>
          <td style="padding:12px;color:#6b7280">{j.filename or "—"}</td>
          <td style="padding:12px">
            <span style="background:{status_color};color:white;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600">{j.status.upper()}</span>
          </td>
          <td style="padding:12px;color:#6b7280">{created}</td>
          <td style="padding:12px;color:#6b7280">{duration}</td>
          <td style="padding:12px">{result_html}</td>
        </tr>"""

    total = db.query(AnalysisJob).count()
    completed = db.query(AnalysisJob).filter(AnalysisJob.status == "completed").count()
    failed = db.query(AnalysisJob).filter(AnalysisJob.status == "failed").count()
    running = db.query(AnalysisJob).filter(AnalysisJob.status.in_(["queued", "running"])).count()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  {refresh_meta}
  <title>Financial Analyser — Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}
    .header {{ background: linear-gradient(135deg, #1e3a5f, #2563eb); color: white; padding: 24px 32px; }}
    .header h1 {{ font-size: 22px; font-weight: 700; }}
    .header p {{ font-size: 13px; opacity: 0.8; margin-top: 4px; }}
    .stats {{ display: flex; gap: 16px; padding: 20px 32px; flex-wrap: wrap; }}
    .stat {{ background: white; border-radius: 10px; padding: 16px 24px; min-width: 130px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .stat .val {{ font-size: 28px; font-weight: 700; }}
    .stat .lbl {{ font-size: 12px; color: #94a3b8; margin-top: 2px; }}
    .card {{ margin: 0 32px 32px; background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }}
    .card-header {{ padding: 16px 20px; border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; }}
    .card-header h2 {{ font-size: 15px; font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ padding: 10px 12px; text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; background: #f8fafc; }}
    tr:hover {{ background: #f8fafc; }}
    .empty {{ text-align: center; padding: 48px; color: #94a3b8; }}
    .links {{ padding: 0 32px 16px; font-size: 13px; color: #64748b; }}
    .links a {{ color: #2563eb; text-decoration: none; margin-right: 16px; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📊 Financial Document Analyser</h1>
    <p>{"⟳ Auto-refreshing every 10s" if any_active else "All jobs settled — manual refresh to update"}</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="val">{total}</div><div class="lbl">Total Jobs</div></div>
    <div class="stat"><div class="val" style="color:#10b981">{completed}</div><div class="lbl">Completed</div></div>
    <div class="stat"><div class="val" style="color:#3b82f6">{running}</div><div class="lbl">Active</div></div>
    <div class="stat"><div class="val" style="color:#ef4444">{failed}</div><div class="lbl">Failed</div></div>
  </div>
  <div class="links">
    <a href="/docs" target="_blank">📖 Swagger Docs</a>
    <a href="/jobs" target="_blank">📋 Jobs JSON</a>
    <a href="/documents" target="_blank">📁 Documents JSON</a>
    <a href="/health" target="_blank">❤️ Health</a>
  </div>
  <div class="card">
    <div class="card-header"><h2>Analysis Jobs (last 50)</h2></div>
    <table>
      <thead><tr><th>Job ID</th><th>Query</th><th>File</th><th>Status</th><th>Submitted</th><th>Duration</th><th>Report</th></tr></thead>
      <tbody>{"".join(rows) if rows else '<tr><td colspan="7" class="empty">No jobs yet — upload a PDF via POST /analyse</td></tr>'}</tbody>
    </table>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)