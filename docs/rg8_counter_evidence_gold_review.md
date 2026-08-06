# RG-8 Counter Evidence Gold 标注人工确认流程

> 更新日期：2026-08-05
> 前置：`evaluation/retrieval/gold/minimal_gnn_v1.json` + baseline 报告 `reports/minimal-gnn-v1_*.json`
> 目标：人工确认 3 条 counter-evidence claim 的 gold 论文标注是否准确，区分**标注问题**和**检索召回问题**

---

## 一、为什么需要人工确认

Baseline（`minimal_gnn_v1`，9 篇语料，完整版带 judge）结果：

| benchmark | Recall@10 | 阈值 | 状态 |
|---|---|---|---|
| Semantic Search | 1.0 | 0.80 | ✅ |
| Similar Work | 1.0 | 0.80 | ✅ |
| Counter Evidence | **0.5** | 0.70 | ❌ |

semantic / similar 达标，pipeline 工作正常（leakage=0）。**counter evidence 的 0.5 需要判断**：是 gold 标注不准（VGIB 未必真的限定这些 claim），还是检索召回不足（gold paper 确实是反证但没被召回）。

> 已确认 min-ce-03 的原始 Milvus 召回 top-30 里**没有 VGIB**——所以要么 VGIB 不是这个 claim 的反证（标注错），要么检索该召回它却召回不到。这一步必须靠人工读论文判断。

---

## 二、准备

### 需要的东西
1. workspace `123100ea` 的 9 篇论文（parsed_markdown 在 `backend/storage/.../artifacts/*.md`）
2. gold set：`evaluation/retrieval/gold/minimal_gnn_v1.json`
3. baseline 报告：`evaluation/retrieval/reports/minimal-gnn-v1_*.json`
4. 辅助脚本：`scripts/evidence_scan.py`（提取 gold 论文相关段落）

### 待确认的 3 条 claim

| id | claim | source | gold 标注（待确认） |
|---|---|---|---|
| **min-ce-01** | Prototype-based methods always produce more faithful explanations than information-bottleneck based methods. | ProtGNN | PGIB → qualifies；**VGIB → qualifies** |
| **min-ce-02** | Graph information bottleneck explanations remain perfectly stable across different graph structures. | PGIB | Why Self-Inconsistency → qualifies |
| **min-ce-03** | Adding more explanation constraints always improves prediction accuracy. | SunnyGNN | **VGIB → qualifies** |

> **重点看标粗的两个 VGIB**——min-ce-01 和 min-ce-03 的 recall 都是被 VGIB 拉低的。

---

## 三、核心流程：对每条 (claim, gold_paper, role) 三步

### Step 1 — 理解 claim 的语境
- claim_text 是什么？它的 source 论文讲了什么？
- 这个 claim 是"绝对化主张"（always / never / outperform all）还是"有条件主张"？
- **绝对化主张** → 更容易被限定/反驳，gold 大概率合理
- **具体方法主张**（"PGIB 在 X 上更好"）→ gold 需要是确实对比过该方法的论文

### Step 2 — 在 gold_paper 里找相关证据
用辅助脚本提取：

```bash
cd backend
.venv/Scripts/python.exe scripts/evidence_scan.py \
    --workspace-id 123100ea-e75b-4110-9048-1f5b92668c32 \
    --claim "Adding more explanation constraints always improves prediction accuracy." \
    --paper-ref "VGIB"
```

脚本会：
1. 解析 `paper_ref` → 该论文的 parsed_markdown
2. 提取 claim 的关键词（去 stopword）
3. 在 markdown 里按句子命中数排序，输出 Top 5 最相关段落（含 section + 前后文）

**读这些段落，回答**：
- 论文有没有明确讨论 claim 的主题？（比如 VGIB 有没有讨论"约束 vs 准确率的权衡"？）
- 论文有没有说"在 X 条件下 Y 成立，在 Z 条件下不成立"（qualifies）或"我们的更好/更差"（contradicts）？

### Step 3 — 判断关系 + 判断标注

| 论文是否真的反证/限定 claim？ | 判断 | 下一步 |
|---|---|---|
| ✅ 是，明确讨论且限定/反驳 | **标注正确** | 保留 gold；如果检索 top-K 没召回 → 记"检索召回不足" |
| ❌ 否，论文与 claim 无关 | **标注错误** | 删掉/换成真正反证 claim 的论文 |
| 🟡 部分相关但不直接表态 | **标注可疑** | 倾向删掉（宁可漏不可误） |

---

## 四、判断分类（记录时用）

对每条 (claim_id, gold_paper, role)：

| 分类 | 含义 | 处理 |
|---|---|---|
| ✅ 标注正确 | 论文确实是该 claim 的反证/限定，检索该召回 | 保留；若 top-K 无 → 检索问题 |
| ❌ 标注错误 | 论文与该 claim 无关，检索不该召回它 | 改 gold set（删掉或换论文） |
| ⚠️ 检索召回不足 | 论文合理反证，但检索 top-K 没召回 | 修 RG-4/5（召回/重排），不是 gold 问题 |
| 🟡 需讨论 | 边界情况，论文有相关讨论但不直接表态 | 团队讨论，倾向保守删除 |

**核心区别**：
- 检索 top-K 里**有** gold paper 但 role 标错 → gold 的 role 错
- 检索 top-K 里**没有** gold paper，且 gold paper 确实是反证 → **检索问题**
- 检索 top-K 里**没有** gold paper，且 gold paper 不是反证 → **gold 问题**

---

## 五、记录模板

```
论文: 123100ea 9 篇 | 日期: 2026-08-05

| claim_id | gold_paper | role | 相关段落(section) | 判断 | 备注 |
|----------|-----------|------|-------------------|------|------|
| min-ce-01 | VGIB | qualifies | Method §3.2 | ✅/❌/⚠️/🟡 | ... |
| min-ce-01 | PGIB | qualifies | Discussion | ✅ 标注正确 | 检索已召回 |
| min-ce-02 | Why Self-Inconsistency | qualifies | Experiment | ✅ 标注正确 | 检索已召回 |
| min-ce-03 | VGIB | qualifies | (无相关段落) | ❌ 标注错误 | VGIB 未讨论该 claim |
```

每条至少一个判断 + 一个"相关段落"证据（Step 2 找到的原文位置）。

---

## 六、验收标准

1. **3 条 claim 的全部 gold 都有明确判断**（✅/❌/⚠️/🟡）
2. **标注错误/可疑的 gold 已修正**：删掉无关论文，或换成真正反证该 claim 的论文
3. **修正后重跑 baseline**：
   - 若修正后 recall ≥ 0.70 → Gate 过，记录
   - 若修正后 recall 仍 < 0.70，且 gold 都合理 → **真检索问题**，回退到 RG-4/RG-5 修召回/重排
4. **区分清楚**：标注问题 vs 检索问题的结论写进记录表，供 zwx 看

---

## 七、常见陷阱

| 陷阱 | 说明 |
|---|---|
| **把"相关"当"反证"** | 论文提到了 IB/constraints 不等于反驳了 claim。要读是否明确说"我们的方法更好/在 X 条件下失败" |
| **gold 论文是 claim 的来源** | 如果 gold_paper == source_paper（claim 出自它），它是"支持"不是"反证"——这种 gold 要标 supports 或删掉 |
| **缩写混淆** | workspace 标题用缩写（DIR/VGIB/TIF）。确认 gold 引用的缩写对应哪篇，别张冠李戴 |
| **检索 top-K 里没有 ≠ gold 错** | 可能是真召回问题。先读论文确认 gold 合理性，再下结论 |

---

## 八、修正后的下一步

1. 改 `minimal_gnn_v1.json` 的 `counter_evidence` 部分
2. 重跑：
   ```bash
   cd backend
   .venv/Scripts/python.exe ../evaluation/retrieval/run_eval.py \
       --workspace-id 123100ea-e75b-4110-9048-1f5b92668c32 \
       --gold ../evaluation/retrieval/gold/minimal_gnn_v1.json
   ```
3. 达标 → RG-8 过，记录到 `docs/phase3_smoke_validation_and_next_plan.md` / 新建 `docs/retrieval_gate_report.md`
4. 未达标 → 判断是标注还是检索，回退修复

---

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-05 | 初版；baseline counter recall=0.5（VGIB 两处待确认） |
| 2026-08-05 | 用 `evidence_scan.py` 初步验证：**min-ce-03 的 VGIB 标注错误**（全文 0 段落命中 claim 关键词）；**min-ce-01 的 VGIB 可疑**（有 fidelity 实验但不直接对比 prototype vs IB）。→ baseline 0.5 主要是 gold 标注问题，不是检索问题 |

## 九、evidence_scan.py 使用示例

```bash
cd backend
# 查 min-ce-03 的 VGIB 是否真的讨论该 claim
.venv/Scripts/python.exe scripts/evidence_scan.py \
    --workspace-id 123100ea-e75b-4110-9048-1f5b92668c32 \
    --claim "Adding more explanation constraints always improves prediction accuracy." \
    --paper-ref "VGIB"
# → 输出: keywords=['adding','constraints'], Top 5 段落为空 → VGIB 无相关证据
```

脚本用关键词重叠（去 stopword）从 parsed_markdown 提取 Top 相关段落，**是定位器不是裁判**——最终判断还是要读段落原文。
