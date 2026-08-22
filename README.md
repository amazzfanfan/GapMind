# GapMind

Evidence-grounded, Human-in-the-Loop AI Research Workspace.

## Tech Stack

| Layer | Technology |
|------|------|
| Backend | FastAPI + Python 3.11+ |
| Database | PostgreSQL 15 |
| Vector DB | Milvus 2.x (standalone) |
| Queue | Redis 7 + Celery |
| LLM | Deepseek (`deepseek-v4-flash`) |
| Embedding | SiliconFlow (`BAAI/bge-m3`) |
| Frontend | React 18 + TypeScript + Vite |
| UI | Ant Design 5.x |
| State | Zustand |
| Graph viz | Cytoscape.js (planned) |

## Repository Layout

```
GapMind/
├── backend/        # FastAPI + Celery workers
├── frontend/       # React + Vite
├── infra/          # Docker Compose for local infra
└── docs/           # Architecture and planning docs
```

## Quick Start (Phase 0)

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker + Docker Compose

### 1. Start infrastructure

```bash
cd infra
docker compose --env-file ../.env up -d   # or plain `up -d` to use built-in defaults
```

This starts PostgreSQL (5432), Redis (6379), and Milvus (19530).

### 2. Backend setup

```bash
cd backend
python -m venv .venv
# or uv venv --python 3.11.15 --seed --managed-python
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
# from the repo root: copy .env.example .env  (then edit .env with your keys)
alembic upgrade head
uvicorn app.main:app --reload
```

Backend: http://localhost:8000
Swagger: http://localhost:8000/docs

### 3. Celery worker (separate terminal)

```bash
cd backend
.venv\Scripts\activate
celery -A app.workers.celery_app worker --loglevel=info
```

**Windows note**: Celery's default prefork pool crashes on Windows with
`WinError 5: 拒绝访问` (billiard's SemLock blocked by OS security policy).
`app/workers/celery_app.py` auto-switches to `--pool=solo` on Windows, so the
plain command above works out of the box. For I/O-bound concurrency later,
switch to `--pool=gevent` (after `pip install gevent`).

### 4. Frontend setup

```bash
cd frontend
# npm install
npm install --allow-remote=all
npm run gen:api
npm run dev
```

Frontend: http://localhost:5173

### Workspace Agents

The workspace AI assistant supports evidence-grounded Q&A, research-plan generation, and code-project generation. Agent runs are processed by the Celery worker, so Redis and the worker must be running. After pulling migrations that add Agent support, run `alembic upgrade head` and restart both FastAPI and Celery.

Generated code is previewed and downloaded by default; it is never executed automatically. Quality signals come from the pipeline itself: a pure-Python static review (syntax gate, dependency consistency, scaffolding) and a plan-coverage rubric that reports covered/partial/missing items and known gaps honestly.

### Fine-tuned Research Gap Board

GapMind can call the fine-tuned Qwen3 Schema 3.0 extractor through Ollama, build a deterministic method-by-problem board, and hand unverified cells to Discover for external novelty and counter-evidence checks. See [`docs/fine_tuned_gap_board_integration.md`](docs/fine_tuned_gap_board_integration.md) for configuration, migration, workflow, and safety boundaries.

## Environment Variables

A single `.env` at the repo root is shared by all three runtimes — copy `.env.example` (repo root) to `.env` and fill in:

- `DEEPSEEK_API_KEY` - Deepseek API key
- `SILICONFLOW_API_KEY` - SiliconFlow API key (for BGE-m3 embedding)
- `SEMANTIC_SCHOLAR_API_KEY` - (optional) for higher rate limits
- `DEEPSEEK_BACKUP_*` - (optional) backup OpenAI-compatible endpoint; automatic failover when the primary LLM fails (all three fields must be set)
- `GAP_EXTRACTOR_*` - fine-tuned gap-board model via Ollama (defaults usually suffice)
- `VITE_API_BASE_URL` - frontend API base (vite reads `VITE_*` from the same file)
- `POSTGRES_*`, `REDIS_*`, `MILVUS_*` - infra connection settings (also used by `docker compose --env-file ../.env` from `infra/`)
