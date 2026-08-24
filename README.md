# GapMind

Evidence-grounded, Human-in-the-Loop research innovation assistant for graph machine learning and graph neural network research.

GapMind 当前聚焦计算机科学—图机器学习/图神经网络科研场景，面向研究生/科研助理与导师/教师，支持三类核心任务：有证据的论文问答、研究机会核验、研究计划和代码草稿辅助。系统将论文证据、相似工作、反证、外部核验、Critic 收窄和人工确认组织成一个研究流程。

正式产品入口是 `frontend/` 中的 React/Vite 应用；请按下方启动命令访问 `http://localhost:5173`。仓库根目录可能存在未跟踪的历史静态原型文件，不属于 GapMind 正式入口或比赛交付物。

部署到 staging/production 时必须配置 `APP_ENV`、`AUTH_TOKENS`（格式为 `token:user_id`，多个用逗号分隔）和 `VITE_API_TOKEN`；此时 API 只接受 Bearer token，不能用可伪造的 `X-User-ID` 代替身份。

AI 输出默认是候选或草稿，不自动成为科学事实；资料不足时会保留不确定性，代码生成默认只做静态检查和预览/下载，不自动执行。当前版本不将 GraphRAG、成熟多模态、最终生成模型 SFT、多租户规模化和真实用户效果宣称为已完成能力，详细边界见 [`docs/0824_scope_and_claims.md`](docs/0824_scope_and_claims.md)。

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
| Graph viz | Cytoscape.js (knowledge graph page) |

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

The workspace AI assistant is scoped to the graph machine learning / GNN research workflow. It supports evidence-grounded Q&A, research-opportunity discovery, research-plan generation, and code-project generation. Agent runs are processed by the Celery worker, so Redis and the worker must be running. After pulling migrations that add Agent support, run `alembic upgrade head` and restart both FastAPI and Celery.

Generated code is previewed and downloaded by default; it is never executed automatically. Quality signals come from the pipeline itself: a pure-Python static review (syntax gate, dependency consistency, scaffolding) and a plan-coverage rubric that reports covered/partial/missing items and known gaps honestly.

### Research Gap Board

GapMind can use a fine-tuned Qwen3 Schema 3.0 extractor through Ollama to build a deterministic method-by-problem board, then hand unverified cells to Discover for external novelty and counter-evidence checks. In the current product boundary, this is an extraction/annotation component rather than a claim that the final generation model has completed domain SFT. See [`docs/0824_scope_and_claims.md`](docs/0824_scope_and_claims.md) for the current safety and claim boundaries.

## Environment Variables

A single `.env` at the repo root is shared by all three runtimes — copy `.env.example` (repo root) to `.env` and fill in:

- `DEEPSEEK_API_KEY` - Deepseek API key
- `SILICONFLOW_API_KEY` - SiliconFlow API key (for BGE-m3 embedding)
- `SEMANTIC_SCHOLAR_API_KEY` - (optional) for higher rate limits
- `DEEPSEEK_BACKUP_*` - (optional) backup OpenAI-compatible endpoint; automatic failover when the primary LLM fails (all three fields must be set)
- `GAP_EXTRACTOR_*` - fine-tuned gap-board model via Ollama (defaults usually suffice)
- `VITE_API_BASE_URL` - frontend API base (vite reads `VITE_*` from the same file)
- `POSTGRES_*`, `REDIS_*`, `MILVUS_*` - infra connection settings (also used by `docker compose --env-file ../.env` from `infra/`)
