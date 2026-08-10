# 0811 端到端演练结果（W6-2 / W6-3 部分）

> 日期：2026-08-11
> 作者：yx
> 关联：`0809_freeze_version.md`（版本冻结清单）、`research_assistant_completion_plan.md` W6-2/W6-3

---

## 一、三次端到端结果

| # | 起点 | Run ID | 结果 | 机会候选 | AgentStep | 耗时估算 |
|---|---|---|---|---|---|---|
| 1 | **全新 workspace**（导入 1 篇 GIB → 解析/抽取/向量化）| `57864625` | ✅ succeeded | 2 个（conf 0.3/0.5）| 12 | 导入+解析+抽取 ~45s；Discover ~2.5min |
| 2 | 现有语料 `self-interpretable gnn`（19 篇）| `fec22cfb` | ✅ succeeded | 2 个（conf 0.3/0.5，方向不同）| 12 | ~2.5min |
| 3 | 现有语料（同 topic 重复）| `b4ea7358` | ✅ succeeded | 2 个（conf 0.3/0.5）| 12 | ~2.5min |

**三次全部 succeeded，可复现。** 每次产出 2 个有区分度机会候选 + 完整多智能体交接流（12 AgentStep：planner→evidence→external_novelty→external_selection→critic→gate→narrowing→complete）。

## 二、各阶段验证

| 阶段 | 结果 |
|---|---|
| 导入 → 解析 → 抽取 → 向量化（全新起点）| ✅ GIB 论文 17 chunks，parsed/extracted |
| Workspace 检索（similar/counter）| ✅ |
| 外部核验（S2）| ✅ 52-65 真实候选/次；query 429 rate limit → `succeeded_partial` 降级正常 |
| 外部全文核验（OA 下载）| ✅ GIB + Prototype GIB → 2 篇 verified + full_text（另次运行验证）|
| 机会合成（多候选）| ✅ 每次 2 个有区分度候选 |
| 多智能体交接流 | ✅ 12 AgentStep（真实 LLM planner/critic/gate）|
| HITL 决策 | ✅ defer + Timeline（另次验证）|
| 研究计划 → 人工确认 | ✅ 计划落库（另次验证）|
| 代码生成 | ✅ 7 文件 PyTorch 项目（另次验证）|
| W7 生命周期（Write/Respond/Analyze）| ✅ 真实 LLM（另次验证）|

## 三、错误率 / 降级

- **Run 失败率：0/3**（三次全部 succeeded）
- **外部核验降级**：部分 S2 query 429（rate limit）→ `succeeded_partial`，不影响 run 完成
- **机会 gate**：coverage 不足 → `needs_more_evidence`（正确降级，非失败）

## 四、耗时 / token（W6-3 部分）

- **耗时**：Discover 单次 ~2.5min（检索 + S2 + LLM 合成 + Critic）；全新起点另 +45s（导入解析抽取 1 篇）
- **token**：⚠️ **AgentStep.details 未记录 usage**（`_agent_step` 未传 token），无法从运行记录聚合 LLM 成本——**审计缺口**，建议后续在 `_agent_step` 补 token usage

## 五、发现的问题

| 问题 | 状态 |
|---|---|
| **run 详情 API 漏传 agent_steps**（Multi-agent handoff 卡片空）| ✅ 已修复（`d04ebe2`）|
| AgentStep 未记录 token usage（W6-3 成本审计缺口）| ⚠️ 待补（建议 `_agent_step` 加 usage）|

## 六、结论

主链路 3 次可复现跑通；外部核验/全文核验/多智能体/机会/降级均真实验证。剩余：完整 token 成本记录（补 usage）、演示脚本打磨（W6-4）、正式封版确认。
