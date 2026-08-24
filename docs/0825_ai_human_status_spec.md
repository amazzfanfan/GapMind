# GapMind AI 产物与人工确认状态规范

**版本**：v0.1（2026-08-25）
**适用分支**：`yx_dev`
**对应任务**：T4-04 统一 AI 生成和人工状态标识
**状态**：代码已有分散实现；候选版本已补齐 Agent 文件卡状态徽章和 Evidence Passport 新鲜度字段，最终验收仍需真实截图与端到端检查。

## 1. 目的与基本原则

用户看到任何回答、研究机会、计划、报告或代码时，至少应能回答四个问题：

1. 这是 AI 生成、人工编辑，还是系统原始资料？
2. 当前是候选、待人工确认、已确认，还是已驳回？
3. 结论是否有当前版本的证据支持，证据是否完整或已过期？
4. 代码是只做静态检查，还是确实运行过并留下运行记录？

状态不能用一个“置信度”数字代替。候选状态、证据状态、人工状态和执行状态必须分开记录；缺失信息时显示“未记录/未核验”，不能默认显示为已完成。

## 2. 统一状态轴

### 2.1 来源类型

| 标识 | 含义 | 使用边界 |
|---|---|---|
| `[En]` | 论文或工作区证据 | 只能指向真实存在、可定位的证据片段；不能用来标记计划或 AI 推断 |
| `[Pn]` | 研究计划草稿 | 表示计划内容，不是论文事实或实验结果 |
| `[Dn]` | 报告/分析草稿 | 表示 AI 生成的分析或写作草稿，不能替代人工结论 |
| `[Cn]` | 代码草稿 | 表示 AI 生成的代码文件或实验骨架，不能表示已运行 |

上述四类来源不可互换。计划、报告和代码中的假设必须回链 `[En]` 或显式标注为待验证假设。

### 2.2 产物来源与人工状态

| 内部值 | 中文显示 | 适用对象 | 说明 |
|---|---|---|---|
| `ai_generated` | AI 生成 | Chat、Discover、Agent 产物 | 初始来源，不能直接成为正式事实 |
| `candidate` | 候选 | Discover 机会 | AI 提出的研究方向，等待证据门和人工判断 |
| `needs_more_evidence` | 证据不足 | Discover 机会/核验结果 | 当前证据不能支持确认，下一步应补证或收窄 |
| `waiting_for_user` | 待人工确认 | Agent/外部候选流程 | 系统暂停，需用户选择、确认或补充输入 |
| `unreviewed` | 待人工审阅 | AgentArtifact | 产物已生成，但没有人工审核记录 |
| `confirmed` | 已确认 | Research Opportunity/人工决策 | 只在用户确认后使用；不能由 AI 自动设置 |
| `edited_confirmed` | 编辑后确认 | Research Opportunity | 用户修改后确认，必须保留版本历史 |
| `rejected` | 已驳回 | Opportunity/人工决策 | 不得继续作为已确认研究方向使用 |
| `deferred` | 暂缓 | Opportunity/人工决策 | 保留记录，后续可重新审阅 |

### 2.3 证据与执行状态

| 维度 | 允许值/显示 | 解释 |
|---|---|---|
| 核验 | `unverified` 未核验、`incomplete` 核验不完整、`verified_with_warnings` 已核验（有警告）、`verified` 核验完成、`verification_failed` 核验失败 | 只描述当前检索/核验过程，不等于科学结论正确 |
| 证据门 | `insufficient_full_text_evidence` 全文证据不足、`verified` 已满足门槛、`verified_with_warnings` 满足但有警告 | 必须显示独立论文数、全文/元数据范围和阻断原因 |
| 证据新鲜度 | `current` 当前快照、`stale` 版本较旧、`expired` 需要重新核验、`unknown` 未记录 | 这是“核验证据快照”的运维新鲜度，不等于论文或科学结论失效；未记录时不能暗示为实时核验 |
| 代码执行 | `not_executed` 未执行、`static_checked` 仅静态检查、`executed` 有运行记录、`execution_failed` 执行失败 | 当前候选版本的代码 Agent 默认是 `static_checked`，不允许显示为 `executed` |

## 3. 当前代码映射

| 业务区域 | 当前实现证据 | 对外应显示 |
|---|---|---|
| Workspace Chat | `frontend/src/components/chat/ChatMessages.tsx` 会显示 grounding、引用一致性和证据不足提示 | “AI 回答”；有工作区证据时显示 `[En]`；无证据或引用失败时显示警告/降级 |
| Discover | `frontend/src/pages/DiscoverPage.tsx` 显示候选、核验、证据覆盖、人工状态、版本创建者和 Evidence Passport | “AI 生成候选/证据门/人工状态”；确认前不能写成新颖性结论 |
| Research Plan | `opportunity_workflow.py` 只允许 confirmed/edited_confirmed Opportunity 创建计划，计划初始为 `draft`；`frontend/src/pages/ResearchPlansPage.tsx` 增加产物状态边界提示 | “研究计划草稿，待人工确认” |
| Agent Artifact | `AgentArtifactRead.validation_status` 记录 `unreviewed` 等校验状态 | 文件卡显示“AI 生成/待人工审阅”；状态不能因为生成成功自动变为已确认 |
| Code Agent | `frontend/src/components/chat/ChatAgentRunCard.tsx` 已显示静态检查和“代码未运行”说明 | “AI 代码草稿；静态检查；未执行”，下载前仍需人工审阅 |
| Gap Board/知识抽取 | `extracted_candidate` 与 `human_confirmed` 分离 | “AI 待审核”与“人工确认”必须分开统计 |

## 4. 状态迁移约束

```text
AI 生成
  ├─ 证据不足/核验失败 → 证据不足或核验失败 → 补证/重试/收窄
  ├─ 需要用户决定      → 待人工确认 → 确认 / 编辑后确认 / 驳回 / 暂缓
  └─ 证据门通过        → 仍是候选 → 人工确认后才可进入计划

代码草稿 → 静态检查 → 待人工审阅 → （另行执行并留存运行记录）→ 已运行/运行失败
```

禁止以下隐式迁移：

- LLM 返回成功就把 `candidate` 变成 `confirmed`；
- 有引用就把回答标成“事实正确”；
- 静态检查通过就把代码标成“实验已验证”；
- 缓存或部分成功的外部查询显示成“已完成新颖性判断”；
- 人工编辑后覆盖原版本而不记录 `created_by=user` 和版本历史。

## 5. 候选版本验收清单

- [x] Discover 页面已有候选、证据门、核验状态、人工状态和版本来源显示。
- [x] Agent 代码卡明确静态检查不代表运行验证，并展示 AI 代码草稿提示。
- [x] Agent API 暴露 `validation_status`，Discover Evidence Passport 暴露 `human_status`、模型和语料版本。
- [x] Chat 在无证据、引用失效、引用缺失和引用质量拒绝时给出可见提示。
- [x] Chat 页面显示远程资料发送边界；Gap Board 的远程备份必须显式勾选并展示警告。
- [x] Agent 文件卡统一显示一处“AI 生成/待人工审阅”或“静态检查/未执行”状态徽章；代码 ZIP 额外包含 `ARTIFACT_STATUS.json`，保留每个文件的 `validation_status`。
- [x] Evidence Passport 已补齐 `evidence_freshness`、`evidence_checked_at` 字段、30 天/60 天可配置的快照新鲜度判定和 Discover UI 展示；真实截图和 staging 运行证据仍待补齐。
- [ ] 在 staging 完成计划、报告、代码、审稿回复四类产物的状态截图与人工确认端到端测试。

### 5.1 候选版本的新鲜度判定

- 后端配置 `EVIDENCE_FRESHNESS_MAX_AGE_DAYS` 默认 30 天；不超过 30 天显示 `current`，超过 30 天但不超过 60 天显示 `stale`，超过 60 天显示 `expired`。
- 判定依据是该机会所挂证据行的最近 `created_at`，即系统最近一次记录核验证据快照的时间；不是论文发表时间，也不是对科学结论正确性的判断。
- 没有证据、时间戳缺失或类型无法识别时显示 `unknown`，不得自动降级为 `current`。
- 当前实现覆盖 Discover Evidence Passport；Chat/Agent 的既有结果字段仍按其自身上下文提供，不能据此宣称所有产物已经完成统一的证据过期自动识别。

## 6. 交付材料写法

允许写：

> 系统将 AI 生成、候选、证据核验、待人工确认、已确认和代码静态检查状态分开呈现；研究计划和代码默认是可审阅草稿，不把模型输出自动写入科学事实或实验结果。

不允许写：

- “所有 AI 结果都已人工验证”；
- “代码已通过实验验证”（只有静态检查时）；
- “系统自动完成新颖性判断”；
- “证据过期会自动被系统完整识别”（只有代码级判定、尚无 staging 证据时）。
