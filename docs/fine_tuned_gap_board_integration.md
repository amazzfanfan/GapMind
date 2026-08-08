# 微调模型与研究空白棋盘接入说明

## 目标

本模块把已经微调并部署到 Ollama 的 `research-dataset-qwen3` 模型接入 GapMind，用于批量抽取论文中的核心方法、核心问题、实体和关系，并生成跨论文的“方法策略 × 问题”棋盘。

棋盘格有三种含义：

- `ADDRESSES`：已有论文明确使用该方法策略解决该问题，格子为“已覆盖”。
- `HAS_LIMITATION`：论文明确指出该方法在该问题上仍有局限，格子保持未覆盖，但拥有更强的候选信号。
- 没有上述关系：仅表示当前工作区语料没有发现覆盖证据。

**空格不是研究空白结论。** 用户必须把候选格交给现有 Discover Agent，继续执行工作区相似研究检索、外部论文搜索、反证检查和 Evidence Gate。

## 总体流程

```text
论文 PDF
  -> GapMind PDF/Markdown 解析
  -> 裁剪实验、评测、附录和参考文献等非核心章节
  -> Ollama 微调模型输出 Schema 3.0
  -> Schema + 业务规则校验
  -> 最多 N 次带错误信息的修复调用
  -> 有效标注入库 / 无效标注隔离
  -> 保守的跨论文方法与问题归一化
  -> 确定性生成方法 × 问题棋盘
  -> 用户选择候选空格
  -> Discover Agent 外部核验
  -> 可审查的研究机会
```

模型只负责单篇论文的结构化抽取。棋盘不是由在线大模型自由生成，而是根据经校验的 `ADDRESSES` 和 `HAS_LIMITATION` 关系确定性构造，因此相同数据能够得到可复现结果。

## 数据层

迁移 `0015_gap_board` 新增四张表：

- `paper_gap_annotations`：保存输入摘要、模型参数、原始响应、校验错误和有效 Schema 3.0 输出。
- `gap_canonical_concepts`：保存工作区内归一化后的方法轴与问题轴概念。
- `gap_concept_assignments`：记录每篇标注中的局部实体到规范概念的映射。
- `gap_board_snapshots`：保存每次重建的版本化棋盘快照。

归一化采用保守策略：先匹配规范化后的完全相等标签，再允许相似度不低于 `0.92` 的自动合并；不确定概念保持分离，避免误合并导致假空白或漏空白。后续可以增加在线模型或人工审核的概念合并队列。

## Ollama 配置

将 `infra/.env.example` 复制为后端 `.env`，至少确认：

```env
GAP_EXTRACTOR_BASE_URL=http://127.0.0.1:11434
GAP_EXTRACTOR_MODEL=research-dataset-qwen3:run7-q8-templatefix
GAP_EXTRACTOR_MODEL_DIGEST=
GAP_EXTRACTOR_TIMEOUT_SECONDS=600
GAP_EXTRACTOR_REPAIR_ATTEMPTS=2
GAP_EXTRACTOR_NUM_CTX=32768
GAP_EXTRACTOR_NUM_PREDICT=4096
GAP_EXTRACTOR_TEMPERATURE=0.01
GAP_EXTRACTOR_TOP_P=1
GAP_EXTRACTOR_REPEAT_PENALTY=1.05
GAP_EXTRACTOR_SEED=42
```

当 FastAPI/Celery 在 Docker 中而 Ollama 运行在宿主机时，将地址改为：

```env
GAP_EXTRACTOR_BASE_URL=http://host.docker.internal:11434
```

先验证模型可见：

```bash
curl http://127.0.0.1:11434/api/tags
```

## 启动

后端升级数据库：

```bash
cd backend
alembic upgrade head
```

启动 FastAPI 与 Celery。专项抽取由 Celery 执行，所以只启动 FastAPI 不足以运行模型调用：

```bash
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker --loglevel=info
```

启动前端后，在工作区导航中进入“研究空白”：

```bash
cd frontend
npm install
npm run dev
```

页面操作顺序：

1. 确保论文已经完成 Markdown 解析。
2. 点击“抽取已解析论文”。重复提交会按论文、输入哈希、模型名和 Prompt 版本复用有效结果。
3. 在任务页面确认批处理完成；无效结果会保留错误，但不会进入棋盘。
4. 点击“重建棋盘”。
5. 对未覆盖格点击“交给 Discover 核验”。
6. 在 Discover 页面审核相似工作、外部候选、证据与最终研究机会。

## API

- `POST /api/v1/workspaces/{workspace_id}/gap/extractions`：批量提交专项抽取。
- `GET /api/v1/workspaces/{workspace_id}/gap/annotations`：查看有效与隔离标注。
- `POST /api/v1/workspaces/{workspace_id}/gap/board/rebuild`：重建版本化棋盘。
- `GET /api/v1/workspaces/{workspace_id}/gap/board`：读取最新棋盘。
- `POST /api/v1/workspaces/{workspace_id}/gap/candidates/discover`：把候选格交给 Discover。

## 边界与后续优化

- 当前概念归一化以高阈值规则为主，宁可多轴也不冒险误合并；需要增加人工合并/拆分界面。
- Schema 3.0 不含逐字 evidence。候选结论的证据落地由 Discover 的检索和 Evidence Gate 完成。
- 当前候选分只是排序启发式，不是“研究空白概率”。明确局限、方法覆盖论文数和问题覆盖论文数只用于确定核验优先级。
- Ollama 修复调用提高结构有效率，但应持续记录“首轮有效率”和“修复后有效率”；部署质量不能只看最终修复成功率。
- 正式环境建议填写模型 digest，并在更换同名 Ollama 模型后强制重新抽取或升级模型标签，避免复用旧缓存。
