# RG-1 三篇论文人工抽取质量审查 — 操作手册

> 更新日期：2026-08-04
> 关联：`docs/phase3_smoke_validation_and_next_plan.md` §6 V1
> 目标：人工核对三篇真实论文的知识抽取质量，产出五分类记录表
> 前置：后端已启动（`uvicorn app.main:app --reload --port 8000`），/docs 可用

---

## 〇、准备（10 分钟）

### 需要的东西
1. 后端跑起来，`/docs` 可用
2. 三篇论文的 workspace_id 和 paper_id
3. 一份空记录表（见 §四 模板）

### 三篇论文定位

| # | 论文 | Workspace | 说明 |
|---|---|---|---|
| 1 | **Prototype-based Graph Information Bottleneck (PGIB)** | `123100ea-e75b-4110-9048-1f5b92668c32` | 主 Demo Case 的源论文，最重点 |
| 2 | **Self-Interpretable Graph Learning with Sufficient and Necessary Explanations** | 同上 | 与 PGIB 同 workspace，可对比方法间差异 |
| 3 | **RAG vs. GraphRAG: A Systematic Evaluation and Key Insights** | `533c89cd-625f-45e7-8a44-cc737244273c` | 另一领域，验证抽取不被领域偏置 |

> 建议先查每个 workspace 的 paper 列表拿到准确 paper_id：
> ```
> GET /api/v1/workspaces/{wid}/papers
> ```

---

## 一、导出数据（每篇论文约 5 分钟）

对每篇论文，把五类 item 全量拉出来。以 PGIB 为例：

```bash
# 列出该论文所有 knowledge items
GET /api/v1/workspaces/123100ea-.../knowledge?paper_id=<paper_id>&limit=200

# 单独看某类（推荐，避免列表太长）
GET /api/v1/workspaces/123100ea-.../knowledge?paper_id=<paper_id>&type=method&limit=200
GET /api/v1/workspaces/123100ea-.../knowledge?paper_id=<paper_id>&type=claim&limit=200
# ... type 依次换成 task / dataset / limitation
```

### 导出后该看到的字段（KnowledgeItemRead）

| 字段 | 审查时用来干嘛 |
|---|---|
| `id` | 记录定位 |
| `type` | method/task/dataset/claim/limitation |
| `canonical_name` | 实体名，**核对是否与论文一致** |
| `content` | 各类型的结构化内容（见下方"每类核对要点"） |
| `confidence` | LLM 自评分，可辅助判断 |
| `status` | 当前 `extracted_candidate`，**审查前不许标 human_confirmed** |
| `source_provenance` | 含 `start_char`/`end_char`，回链坐标 |

### 各 type 的 content 结构（来自 extract_v1 prompt）

| type | content 键 | 核对重点 |
|---|---|---|
| method | `description` / `problem_addressed` / `key_idea` | 方法名、解决的问题、核心思想是否贴合原文 |
| task | `description` / `input_data` | 任务描述 + 输入数据是否准确 |
| dataset | `description` | 数据集名 + 描述 |
| claim | `statement` | **主张是否超出原文含义**（最重要） |
| limitation | `description` / `limitation_type` | 是否是真限制，还是通用背景 |

---

## 二、每个 item 的 8 步核对流程

对**每个抽查 item**，按下面顺序过：

**Step 1 — 打开证据原文**
```
GET /api/v1/workspaces/{wid}/knowledge/{item_id}/evidence/context
```
返回 `content`（完整 parsed_markdown）+ `spans`（含 `start_char`/`end_char`/`text`）。

**Step 2 — 验证回链精确性**
- 取 `spans[0].text`，手动到 `content` 里用浏览器/编辑器搜索（或按 offset 定位）
- ✅ **精确匹配**：文字一字不差、位置正确 → 记录"回链精确"
- ❌ **不精确**：text 与 content 切片对不上，或位置明显偏移 → 这条 item 就算内容对，回链也 FAIL（验收硬性要求 100% 精确）

**Step 3 — 核对 canonical_name**
- 方法/任务/数据集：实体名是否就是论文里出现的名字？有没有缩写变体被错误拆成两个实体？
- claim/limitation：canonical_name 通常从 statement 截取，看是否仍可读

**Step 4 — 核对 type**
- 是"方法"还是"任务"？"局限"还是"主张"？分错类的记"部分正确"或"错误"

**Step 5 — 核对 content 与证据一致**
- method.description：论文是不是这么描述这个方法的？
- claim.statement：**主张是否有超出原文的推断？** 比如论文说"在 X 数据集上优于 A"，抽取成"普遍优于所有方法"就是越界
- limitation.description：是论文作者明确写的限制，还是抽取器自己脑补的？

**Step 6 — 核对 claim 的范围/条件**
- claim 的 `statement` 是否保留了原文的条件状语（"在归因 shift 下"、"对稀疏图"、"当深度 > 5 时"）？
- 丢了条件 = 主张被泛化 = 部分正确甚至错误

**Step 7 — 记录判断**（五分类，见 §三）

**Step 8 — 顺手记录 rejection 对照**（可选，每篇看一次）
```
GET /api/v1/workspaces/{wid}/extraction-runs/{run_id}/rejections
```
看拒绝原因（`reason_code`：invalid_item_schema / evidence_not_found / relation_resolution…），判断拒绝是否合理：
- 一条看起来合法、证据明确的 item 被拒了 → 记"应接受但拒绝"
- 一条证据对不上、明显错位的 item 被接受了 → 记"应拒绝但接受"

---

## 三、五类判断（每条 item 必填一个）

| 判断 | 含义 | 常见触发 |
|---|---|---|
| ✅ **正确** | 名字、类型、内容、证据全部一致，回链精确 | 无 |
| 🟡 **部分正确** | 方向对，但某处不准确 | 丢了 claim 的条件状语；content 少了一半要点；type 分错 |
| ❌ **错误** | 内容与原文明显不符 | 方法描述张冠李戴；claim 泛化越界；limitation 是脑补的 |
| ⚠️ **应拒绝但接受** | 这条 item 不该进库（证据对不上、纯背景、重复），却进了 | 证据回链失败但 item 仍在；limitation 其实是 Related Work 背景 |
| 💤 **应接受但拒绝** | 证据明确、内容准确，却被 rejection 挡掉了 | 证据 span 恰好超出 batch 边界被误判 not found |

---

## 四、记录表模板

每篇论文一张表，每行一个 item：

```
论文: PGIB | Workspace: 123100ea-... | Paper: <paper_id>
抽査日期: 2026-08-04

| item_id | type | canonical_name | 回链精确 | 判断 | 备注 |
|---------|------|----------------|---------|------|------|
| <uuid>  | method | Graph Information Bottleneck | ✅ | 正确 | description 贴合 §3.2 |
| <uuid>  | claim | ... | ❌ | 部分正确 | 丢了"in covariate shift"条件 |
| ...     | ...   | ...            | ...     | ...  | ... |

抽查数: ____ | 正确: __ | 部分正确: __ | 错误: __ | 应拒绝但接受: __ | 应接受但拒绝: __
```

**抽样策略**（每篇 ≥5 个高价值 item）：
- 2 个 method（方法最关键）
- 1-2 个 claim（最易越界）
- 1 个 limitation（最易脑补）
- 0-1 个 dataset/task（看论文有没有）

---

## 五、验收标准（三篇都过才算 RG-1 完）

1. **回链精确 100%**：所有抽查 item 的 EvidenceSpan 字符级精确
2. **零错误 claim 被确认**：`status=human_confirmed` 的 item 必须是"正确"或"部分正确（已人工修正）"
3. **系统性问题处理**：
   - 若 >20% 的 claim 都越界 → 先改 `extract_v1.py` prompt（强调保留条件状语），再重抽
   - 若 >20% 的 limitation 都是脑补 → 改 prompt 加"只抽取作者明确声明的限制"
   - 若回链不精确集中在某类 → 先修 parser/chunker，再重跑那篇
4. **产出**：三张记录表 + 一份小结（统计 + 发现的系统性问题），建议存到 `docs/phase3_smoke_validation_and_next_plan.md` 旁边或单独 `docs/rg1_extraction_review.md`

---

## 六、常见陷阱（抽到前先读一遍）

| 陷阱 | 怎么识别 |
|---|---|
| **claim 被泛化** | 原文"在 X 数据集上 GAT 超过 GCN"，抽成"GAT 超过 GCN"——丢了数据集限定 |
| **limitation 是背景** | 抽取器把"深度方法计算开销大"这种通用常识当成论文 limitation |
| **method 张冠李戴** | 两篇论文都用类似缩写，canonical_name 串了 |
| **回链偏移 1 字符** | 尾随换行/空格被吃掉，`start_char` 差 1——内容对但回链 FAIL |
| **实体过度分裂** | "GIB" 和 "Graph Information Bottleneck" 被拆成两个 method 实体 |
| **拒绝误杀** | 证据跨 batch 重叠区被 `evidence_not_found` 拒绝，其实是合法 item |

---

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-04 | 初版；等人工执行三篇论文审查 |
