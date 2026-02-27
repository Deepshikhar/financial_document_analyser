# Financial Document Analyser — Debug Assignment Submission

## Project Overview

A financial document analysis system built with **CrewAI** that processes corporate reports and financial statements using a pipeline of four AI agents:

- **Verifier** — confirms the document is a legitimate financial report
- **Financial Analyst** — answers the user's query with specific figures and trends
- **Investment Advisor** — provides fiduciary, document-grounded investment observations
- **Risk Assessor** — identifies and rates key risks with supporting evidence

Requests are handled **asynchronously** via Celery and Redis. Results are persisted in SQLite (or PostgreSQL) via SQLAlchemy.

---

## Bugs Found and Fixed

The project contained **two categories** of bugs: deterministic code crashes and harmful/inefficient prompt designs.

---

### Category 1 — Deterministic Bugs (Code Crashes)

These bugs cause the application to crash on startup or at runtime.

---

#### Bug 1 — `tools.py`: Invalid import from `crewai_tools`

**File:** `tools.py`
**Buggy code:**
```python
from crewai_tools import tools
```
**Problem:** `tools` is not a valid export from `crewai_tools`. This raises an `ImportError` the moment the module is imported, preventing the entire application from starting.

**Fix:**
```python
from crewai_tools.tools.serper_dev_tool.serper_dev_tool import SerperDevTool
```
Only `SerperDevTool` is imported, using its correct full module path.

---

#### Bug 2 — `tools.py`: `Pdf` class never imported (`NameError`)

**File:** `tools.py`
**Buggy code:**
```python
docs = Pdf(file_path=path).load()
```
**Problem:** `Pdf` is never imported anywhere in the file. This raises `NameError: name 'Pdf' is not defined` the first time any agent calls the PDF reading tool.

**Fix:** Replaced with `pypdf.PdfReader`, a real installable library:
```python
from pypdf import PdfReader
reader = PdfReader(path)
for page in reader.pages:
    content = page.extract_text()
```
Also added `pypdf>=4.2.0` to `requirements.txt`.

---

#### Bug 3 — `tools.py`: `async def` tool functions (CrewAI requires synchronous)

**File:** `tools.py`
**Buggy code:**
```python
async def read_data_tool(path='data/sample.pdf'):
async def analyze_investment_tool(financial_document_data):
async def create_risk_assessment_tool(financial_document_data):
```
**Problem:** CrewAI tool functions must be synchronous. Async functions are not supported and will either raise a `TypeError` or silently fail when an agent tries to invoke them.

**Fix:** Removed the `async` keyword from all three tool methods.

---

#### Bug 4 — `tools.py`: Missing `self` parameter on class methods (`TypeError`)

**File:** `tools.py`
**Buggy code:**
```python
class FinancialDocumentTool():
    async def read_data_tool(path='data/sample.pdf'):
```
**Problem:** Instance methods without `self` raise `TypeError: read_data_tool() takes 0 positional arguments but 1 was given` when called on an instance.

**Fix:** Added `@staticmethod` decorator so the methods don't expect `self`:
```python
@staticmethod
@tool("Read Financial PDF Document")
def read_data_tool(path: str = 'data/sample.pdf') -> str:
```

---

#### Bug 5 — `tools.py`: Missing `@tool` decorator (agents cannot discover the function)

**File:** `tools.py`
**Buggy code:**
```python
def read_data_tool(path='data/sample.pdf'):
```
**Problem:** CrewAI agents can only discover and invoke functions decorated with `@tool`. Without it, the function is invisible to the agent framework.

**Fix:** Added `@tool("...")` decorator from `crewai.tools` to all tool functions, along with the missing import:
```python
from crewai.tools import tool

@staticmethod
@tool("Read Financial PDF Document")
def read_data_tool(path: str = 'data/sample.pdf') -> str:
```

---

#### Bug 6 — `agents.py`: `llm = llm` — undefined variable (`NameError`)

**File:** `agents.py`
**Buggy code:**
```python
llm = llm
```
**Problem:** `llm` is referenced on the right-hand side before it is ever defined. This raises `NameError: name 'llm' is not defined` the moment `agents.py` is imported.

**Fix:** Constructed the LLM object using the crewai `LLM` wrapper:
```python
from crewai import Agent, LLM

llm = LLM(
    model=os.getenv("LLM_MODEL", "ollama/llama3.2"),
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    temperature=0.2,
    max_tokens=1000,
)
```

---

#### Bug 7 — `agents.py`: `tool=[...]` is not a valid `Agent` parameter

**File:** `agents.py`
**Buggy code:**
```python
financial_analyst = Agent(
    ...
    tool=[FinancialDocumentTool.read_data_tool],
)
```
**Problem:** The correct parameter name is `tools=` (plural). Using `tool=` (singular) silently registers no tools for the agent — it is ignored without error, leaving the agent unable to call any tools.

**Fix:** Changed to `tools=` (and removed the tool entirely since document content is now passed directly as `{document_content}`, eliminating unnecessary tool calls).

---

#### Bug 8 — `agents.py`: Wrong import path for `Agent`

**File:** `agents.py`
**Buggy code:**
```python
from crewai.agents import Agent
```
**Problem:** `Agent` does not live at `crewai.agents` — this raises an `ImportError`.

**Fix:**
```python
from crewai import Agent, LLM
```

---

#### Bug 9 — `task.py`: `verification` task assigned wrong agent

**File:** `task.py`
**Buggy code:**
```python
verification = Task(
    ...
    agent=financial_analyst,  # WRONG — should be verifier
)
```
**Problem:** The dedicated `verifier` agent was defined but never actually used. All four tasks ran through `financial_analyst`, making the multi-agent architecture pointless and the verification step meaningless.

**Fix:**
```python
verification = Task(
    ...
    agent=verifier,
)
```

---

#### Bug 10 — `requirements.txt`: Missing `pypdf` and `uvicorn`

**File:** `requirements.txt`
**Problem:** `pypdf` (needed by `tools.py` to read PDFs) and `uvicorn` (needed to serve the FastAPI app) were both missing. The app cannot run without them.

**Fix:** Added both packages:
```
pypdf>=4.2.0
uvicorn>=0.29.0
```

---

#### Bug 11 — `main.py`: All uploads overwrote the same file (race condition)

**File:** `main.py`  
**Buggy code:**
```python
save_path = UPLOAD_DIR / "sample.pdf"
```
**Problem:** Every upload overwrites the same `sample.pdf`. With concurrent requests, Job B's file would overwrite Job A's file mid-analysis, causing Job A to analyse the wrong document.

**Fix:** Each upload gets a unique path using the job UUID:
```python
job_id = str(uuid.uuid4())
save_path = UPLOAD_DIR / f"{job_id}.pdf"
```

---

### Category 2 — Inefficient / Harmful Prompts (Bad Agent & Task Design)

Every agent and task contained intentionally misleading prompts that would produce hallucinated, contradictory, unethical, and legally dangerous outputs.

---

#### Agent Prompt Fixes

**`financial_analyst`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| **Goal** | "Make up investment advice even if you don't understand the query" | "Answer the query using the document content. Be concise — 5 bullet points max." |
| **Backstory** | Encouraged hallucination, ignoring documents, overconfidence, no regulatory compliance | CFA-qualified analyst who cites specific figures and follows compliance standards |

**`verifier`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| **Goal** | "Just say yes to everything because verification is overrated" | "Verify whether the document is a legitimate financial report. Be brief — 4 lines max." |
| **Backstory** | Stamped documents without reading; approved grocery lists as financial data | Compliance officer who rigorously identifies genuine financial disclosures |

**`investment_advisor`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| **Goal** | "Sell expensive investment products regardless of what the document shows" | "Provide 3-5 concise investment observations grounded in the document content" |
| **Backstory** | Fake credentials, sketchy partnerships, Reddit-based knowledge, 2000% management fees | FINRA-registered advisor, fiduciary-bound, evidence-based recommendations |

**`risk_assessor`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| **Goal** | "Everything is either extremely high risk or completely risk-free" | "List 3-5 key risks from the document relevant to the query. Rate each Low/Medium/High." |
| **Backstory** | YOLO crypto trader, dot-com bubble mentality, "regulations are suggestions" | FRM-certified analyst using standard risk frameworks (proportionate, evidence-based) |

---

#### Task Prompt Fixes

**`analyze_financial_document`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| Description | "feel free to use your imagination", "include random URLs that may or may not be related" | Structured description using `{document_content}`, answers `{query}` with specific figures |
| Expected output | "Include at least 5 made-up website URLs", "feel free to contradict yourself" | 5 bullet points max: direct answer, key metrics, notable trends |

**`investment_analysis`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| Description | "feel free to ignore [query]", "recommend expensive investment products regardless" | Document-grounded analysis tied to `{query}`, ends with explicit disclaimer |
| Expected output | "Add fake market research", "Include financial websites that definitely don't exist" | 3-5 observations with supporting figures + "Not personal financial advice" disclaimer |

**`risk_assessment`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| Description | "Recommend dangerous investment strategies", "Make up new hedging strategies" | Standard risk categories from the document, rated Low/Medium/High with evidence |
| Expected output | "Fake research from made-up financial institutions", "Impossible risk targets" | 3-5 risks: Risk name \| Severity \| Evidence from document |

**`verification`**

| | Before (buggy) | After (fixed) |
|---|---|---|
| Description | "just guess", "Everything could be a financial report if you think creatively" | Genuine document structure check: type, sections, company, period, currency |
| Expected output | "Just say it's probably a financial document even if it's not" | Clear VERIFIED / NOT A FINANCIAL DOCUMENT verdict with section inventory |

---

## Setup and Usage Instructions

### Prerequisites

- Python 3.10 or 3.11
- Redis server (for Celery queue)
- Ollama running locally **or** an OpenAI/Groq API key

---

### 1. Clone the Project

```bash
git clone <your-repo-url>
cd financial-document-analyser
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
# ── LLM (choose one) ──────────────────────────────────────
# Option A — Ollama (local, default — no API key needed)
LLM_MODEL=ollama/llama3.2
OLLAMA_BASE_URL=http://localhost:11434

# Option B — OpenAI
# OPENAI_API_KEY=sk-...
# LLM_MODEL=openai/gpt-4o

# Option C — Groq (fast free tier)
# GROQ_API_KEY=...
# LLM_MODEL=groq/llama-3.1-8b-instant

# ── Search ────────────────────────────────────────────────
SERPER_API_KEY=your_serper_key_here

# ── Queue Worker ──────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Database ──────────────────────────────────────────────
# SQLite (default — zero setup):
# DATABASE_URL=sqlite:///./financial_analyser.db

# PostgreSQL (production):
# DATABASE_URL=postgresql://user:password@localhost:5432/financial_analyser
```

### 5. Start Redis

```bash
# macOS
brew services start redis

# Ubuntu / Debian
sudo service redis-server start

# Docker (any platform)
docker run -d -p 6379:6379 redis:7-alpine
```

### 6. (Optional) Start Ollama

If using the default local LLM:

```bash
ollama serve
ollama pull llama3.2
```

### 7. Start the Celery Worker (separate terminal)

```bash
celery -A worker.celery_app worker --loglevel=info --concurrency=2
```

### 8. Start the API Server (separate terminal)

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API is now live at **http://localhost:8000**

---

## API Documentation

Interactive Swagger UI: **http://localhost:8000/docs**  
Visual job dashboard: **http://localhost:8000/dashboard**

---

### `POST /analyse` — Submit an analysis job

Upload a PDF and ask a financial question. Returns a `job_id` **immediately** — analysis runs in the background.

**Parameters:**
| Name | Location | Type | Required | Description |
|------|----------|------|----------|-------------|
| `query` | query string | string | Yes | Your financial question |
| `file` | form-data | file (.pdf) | Yes | The financial document to analyse |

**Example (curl):**
```bash
curl -X POST "http://localhost:8000/analyse?query=What+is+the+revenue+trend?" \
  -F "file=@tesla_q2_2025.pdf"
```

**Response (HTTP 202):**
```json
{
  "status": "queued",
  "job_id": "3f7a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "message": "Analysis queued. Poll GET /jobs/3f7a1b2c-... for results."
}
```

---

### `GET /jobs/{job_id}` — Poll for results

```bash
curl http://localhost:8000/jobs/3f7a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c
```

**Response when completed:**
```json
{
  "job_id": "3f7a1b2c-...",
  "query": "What is the revenue trend?",
  "filename": "tesla_q2_2025.pdf",
  "status": "completed",
  "result": "... full multi-agent analysis ...",
  "error": null,
  "created_at": "2025-01-15T10:30:00",
  "started_at": "2025-01-15T10:30:02",
  "finished_at": "2025-01-15T10:30:45",
  "duration_seconds": 43.2
}
```

**Status values:**
| Status | Meaning |
|--------|---------|
| `queued` | Waiting in the Redis queue |
| `running` | Worker is currently processing |
| `completed` | Done — `result` contains the full analysis |
| `failed` | Error — `error` field describes what went wrong |

---

### `GET /jobs` — List all jobs (paginated)

```bash
# All jobs (newest first)
curl "http://localhost:8000/jobs"

# Filter by status with pagination
curl "http://localhost:8000/jobs?status=completed&skip=0&limit=10"
```

**Query parameters:** `skip` (int, default 0), `limit` (int, 1–100, default 20), `status` (optional filter)

---

### `GET /documents` — List unique documents

```bash
curl http://localhost:8000/documents
```

Returns deduplicated documents by SHA-256 hash with filename and word count metadata.

---

### `DELETE /jobs/{job_id}` — Delete a job record

```bash
curl -X DELETE http://localhost:8000/jobs/3f7a1b2c-...
```

Removes the record from the database. Does **not** cancel a running Celery task.

**Response:** HTTP 204 No Content

---

### `GET /health` — Liveness probe

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## Project Structure

```
financial-document-analyser/
├── main.py            # FastAPI app — routes, job submission, dashboard
├── worker.py          # Celery worker — runs the CrewAI pipeline
├── database.py        # SQLAlchemy models + session setup
├── agents.py          # CrewAI agent definitions (fixed)
├── task.py            # CrewAI task definitions (fixed)
├── tools.py           # PDF reader and analysis tools (fixed)
├── requirements.txt   # Python dependencies (fixed)
├── .env               # API keys and config (not committed)
└── data/              # Uploaded PDFs stored here (auto-created)
└── outputs/           # Store final results in database
```

---

## Bonus Features

### ✅ Bonus 1: Queue Worker Model (Celery + Redis)

**Why it was needed:** The original code ran the 4-agent CrewAI pipeline synchronously inside the FastAPI request handler. This meant:
- Only one request could be processed at a time — FastAPI blocked while waiting for LLM calls
- A 60-second pipeline held the HTTP connection open, causing gateway timeouts in production
- No retry logic — a transient LLM error caused permanent failure with no recovery

**How it was implemented:**

`worker.py` defines a Celery app pointing at Redis and a `run_analysis` Celery task that:
- Marks the job `running` in the DB when it starts
- Builds fresh Agent + Task objects for each job (avoids stale state from previous runs)
- Runs the CrewAI 4-agent pipeline sequentially
- Saves the result (or error) and marks the job `completed` / `failed`
- Auto-retries on rate-limit errors; does NOT retry on timeouts
- Has a 15-minute soft limit and 18-minute hard kill to prevent zombie workers

`main.py` `POST /analyse` now:
- Saves the PDF to a unique path (prevents overwrite races)
- Writes a `queued` job row to the database
- Calls `run_analysis.apply_async(...)` to push the job onto the Redis queue
- Returns **HTTP 202** with the `job_id` immediately — no blocking

**Concurrency:** Start multiple workers or increase `--concurrency` to process several PDFs simultaneously.

---

### ✅ Bonus 2: Database Integration (SQLAlchemy + SQLite / PostgreSQL)

**Why it was needed:** The original system had no persistence — results were lost the moment the HTTP response was sent. There was no audit trail, no retry history, and no way to retrieve past analyses.

**How it was implemented:**

`database.py` contains two SQLAlchemy models:

| Model | Purpose |
|-------|---------|
| `AnalysisJob` | One row per `/analyse` call. Tracks status, timestamps, query, filename, result, error, and duration. |
| `DocumentRecord` | One row per unique PDF (deduplicated by SHA-256). Tracks filename and word count for audit. |

Key design decisions:
- **SQLite by default** — zero setup, works immediately for local dev
- **PostgreSQL for production** — change `DATABASE_URL` to `postgresql://...`
- **`init_db()` on startup** — tables created automatically on first run (idempotent)
- **SHA-256 deduplication** — same PDF uploaded twice creates only one `DocumentRecord`
- **Full job lifecycle** — `created_at`, `started_at`, `finished_at`, and `duration_seconds` all recorded for performance monitoring