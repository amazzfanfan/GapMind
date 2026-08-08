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

归一化采用保守策略：先使用可审计的图神经网络解释 taxonomy，把有明确术语依据的标签投影为稳定的方法族或问题族，并把论文原始标签保存在 `aliases`；未命中 taxonomy 时，先匹配规范化后的完全相等标签，再允许相似度不低于 `0.92` 的自动合并。不确定概念保持分离，避免误合并导致假空白或漏空白。修改 taxonomy 后只需重建棋盘即可重新投影已有有效标注，不需要重新调用模型。后续可以增加在线模型或人工审核的概念合并队列。

### 候选分层与核验优先级

棋盘保留全部未覆盖格用于观察和审计，但只把以下有证据基础的格子列为“推荐核验候选”：

- 论文明确报告该方法族在该问题上的剩余局限；
- 方法族与问题族在同一论文中共现，但没有形成 `ADDRESSES`；
- 方法族与问题族分别都获得至少两篇论文支持，构成跨论文迁移假设。

其余仅由“方法 × 问题”笛卡尔积产生的空格标记为低证据。它们不会进入推荐候选计数，但用户可以显式选择“探索性核验”；该路径会要求 Discover 先验证机制兼容性与相似工作，证据不足时只能返回 `needs_more_evidence`。`candidate_score` 是“外部核验优先级”，综合显式局限、同篇共现、跨论文支持、语料频率和已有覆盖度；它不是研究成功概率，也不是真实研究空白概率。

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

# Discover 查询扩展、工作区语义检索与机会综合；真实值只写 backend/.env，禁止提交
DEEPSEEK_API_KEY=
SILICONFLOW_API_KEY=
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
5. 对有证据基础的推荐候选格点击“交给 Discover 核验”；低证据格如确有探索价值，可在风险确认后点击“探索性核验”。
6. 在 Discover 页面审核相似工作、外部候选、证据与最终研究机会。

Discover 的外部检索按查询隔离失败：单个 Semantic Scholar 查询出现 `429/502/504` 时，已经成功返回的论文会被保留，阶段标记为 `succeeded_partial`；只有全部查询失败才标记为 `failed`。前端阶段条会显示每个阶段的真实状态及失败/部分成功原因。

外部论文核验支持在 `waiting_for_user / external_selection` 阶段勾选多篇候选并一次提交。提交后任务立即进入全文核验阶段，其他候选操作会被锁定；任务完成或保存后也不能在旧运行上继续导入。批量任务允许部分候选下载或解析失败，只要至少一篇论文完成全文解析、知识抽取和向量索引，Discover 就会携带成功全文继续综合，并保留失败候选的状态供人工查看。

## API

- `POST /api/v1/workspaces/{workspace_id}/gap/extractions`：批量提交专项抽取。
- `GET /api/v1/workspaces/{workspace_id}/gap/annotations`：查看有效与隔离标注。
- `POST /api/v1/workspaces/{workspace_id}/gap/board/rebuild`：重建版本化棋盘。
- `GET /api/v1/workspaces/{workspace_id}/gap/board`：读取最新棋盘。
- `POST /api/v1/workspaces/{workspace_id}/gap/candidates/discover`：把候选格交给 Discover。低证据格必须显式传入 `exploratory: true`。

## 边界与后续优化

- 当前概念归一化采用受控 taxonomy 与高阈值规则，宁可多轴也不冒险误合并；仍需要增加人工合并/拆分界面。
- Schema 3.0 不含逐字 evidence。候选结论的证据落地由 Discover 的检索和 Evidence Gate 完成。
- 当前候选分只是排序启发式，不是“研究空白概率”。明确局限、同篇共现、跨论文支持、方法/问题覆盖论文数和覆盖度只用于确定核验优先级。
- Ollama 修复调用提高结构有效率，但应持续记录“首轮有效率”和“修复后有效率”；部署质量不能只看最终修复成功率。
- 正式环境建议填写模型 digest，并在更换同名 Ollama 模型后强制重新抽取或升级模型标签，避免复用旧缓存。
