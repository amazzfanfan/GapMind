# 代码生成改进：开源项目调研与落地方案

> 日期：2026-08-19。作者：yx + AI 调研。
> 背景：GapMind 现有 Code Generation Agent 是"单次 LLM 调用生成整个项目"的简陋实现。本文调研 Paper2Code、DeepCode 及同领域项目，回答"能否基于它们改进"，并给出分期落地方案。
> **Phase A 已于 2026-08-19 实施完成**（A1-A5，见文末"八、Phase A 实施记录"）。

---

## 一、结论（TL;DR）

1. **可以借鉴，不宜"基于"（直接集成/依赖）**。两个项目都不适合作为依赖引入：Paper2Code 是论文配套研究代码（面向"复现整篇论文"的 benchmark 场景，输入是论文 PDF）；DeepCode 是一个完整的自研 agent 框架（自带 harness/编排器/桌面端，Python 3.12+）。直接嵌入违反本项目"不引入重型 agent 框架"的铁律，且它们的输入形态（完整论文）与我们（研究计划 + 工作区证据）不同。
2. **真正值得搬的是三件事**（机制层，不是代码层）：
   - **Paper2Code 的三阶段结构化交接**：planning → analysis → coding，每阶段产出结构化 JSON 交给下一阶段，而不是一口气生成全部文件；
   - **DeepCode 的检索接地（CodeRAG）与验证修复闭环**：先检索方法细节/参考实现再写代码；写完执行、收集报错、定点修复再执行；
   - **PaperBench 的 rubric 思路**：用"逐项检查清单"评估生成项目对研究计划的覆盖度，而不是空泛地声称"已复现"。
3. **落地方案**：在现有 `AgentRun/AgentStep/AgentArtifact` 协议内，把 code_generation 从单次调用改造成**受控多步流水线**（蓝图 → 逐文件生成 → 一致性检查 → rubric 自检 → 可选有界冒烟验证+一次修复），分 A/B/C 三期。A 期无需任何基础设施变更，比赛期内可完成并可演示。

---

## 二、现状盘点：我们的代码生成有多简陋

当前实现（`backend/app/domains/agent/service.py` `_execute_code_generation`）：

```
Step1 workspace_retrieval：用 question+hypothesis 做一次语义检索 → evidence
Step2 code_generation：   一次 _structured_completion(max_tokens=7000) 返回全部文件 JSON
Step3 static_review：     只写一条"检查通过"消息（没有实际检查）
→ 保存 AgentArtifact(validation_status=not_run) → succeeded
（可选）用户点验证 → Celery validate_agent_code → Docker sandbox 只做 py_compile 语法检查
```

弱点清单：

| # | 弱点 | 后果 |
|---|------|------|
| W1 | 整个项目塞进一次 7000 token 的 JSON 响应 | 文件浅、被截断、相互不一致 |
| W2 | 无项目蓝图/模块分解阶段 | 结构由模型即兴决定，无法按文件检查覆盖 |
| W3 | 证据以原始 JSON 塞入，没有"方法细节/公式/超参"分面检索 | 代码与论文方法脱节（有 Milvus chunks 却没用于代码接地） |
| W4 | 无验证修复闭环；sandbox 默认关闭且只查语法 | 生成的代码大概率跑不通，用户无从知晓 |
| W5 | 无自检：文件 vs 计划的 datasets/baselines/metrics 覆盖无核对 | "生成了"≠"覆盖了研究计划" |
| W6 | 代码文件不带证据回链 | 违背 Evidence Passport 精神，审查时无法溯源 |
| W7 | static_review 步骤是假的 | AgentStep 观测流有误导 |

---

## 三、调研对象

### 3.1 Paper2Code（going-doer/Paper2Code，即 PaperCoder，ICLR 2026）

- **是什么**：多智能体 paper-to-code 系统，输入论文 PDF，输出可运行代码项目。论文《From Research to Code: Unveiling the Synthesis Process of Paper-to-Code Transformation》（Seo et al., KAIST）。
- **核心机制**：
  - **三阶段**：① Planning（Planner 产出 roadmap：里程碑/功能/依赖）；② Analysis（5 类分析 agent——Method/Experiment/Findings/Discussion/Background——产出结构化配置）；③ Coding（Coder 按配置逐文件生成，Tester 运行测试，Documenter 写文档）。
  - **Paper2Code-Bench**：30 篇 ICML/NeurIPS/ICLR/ACL 论文 + 6000+ 细粒度 rubric 条目，用 LLM-as-judge 按 rubric 评分（模型级与 rubric 级双口径）。GPT-4o 跑分高于其它开源方案，且模型级评分与人类判断相关性高。
- **对我们的可借鉴点**：三阶段结构化交接（直接对应 W1/W2）；逐文件生成；rubric 覆盖度检查（对应 W5）。
- **不照搬的原因**：面向"复现整篇论文"，输入是完整 PDF；我们是"研究计划 + 证据"驱动的**新实验骨架**生成，不是复现。其 agent 间用完整论文文本传递，token 成本高；代码为 benchmark 研究服务，工程化程度一般（无服务化）。

### 3.2 DeepCode（HKUDS/DeepCode）

- **是什么**：港大数据智能实验室的开源 agentic coding 框架，v2.0，自述"Open Agentic Coding"，**其研究起点就是 Paper2Code 任务**，后泛化为通用编码框架。
- **核心机制**：
  - **编排器 + 专家 agent**：Orchestrator 统一调度，专家含 Intent Understanding（澄清任务）、Document Parsing（PDF→MD/结构）、Code Planning（项目规划）、Reference Mining（挖掘参考实现）、Code Indexing、Code Generation、Verification；
  - **CodeRAG**：检索代码/文档片段作为生成上下文；
  - **验证闭环**：执行生成代码→收集报错→迭代修复；
  - **成绩**：PaperBench 75.9%（自称 SOTA）；MIT 协议；Python ≥3.12；提供 CLI + Tauri 桌面端。
- **对我们的可借鉴点**：Code Planning 前置（同 Paper2Code）；**CodeRAG 检索接地**（对应 W3——我们有现成的 Milvus chunks，缺的是"按方法/公式/超参分面喂给代码生成"）；**执行→报错→修复闭环**（对应 W4）；验证作为独立专家步骤。
- **不照搬的原因**：一个完整框架（自有 harness、编排器、桌面端），嵌入=引入重型 agent 框架（项目铁律 ❌）；Python ≥3.12 与后端 3.11 冲突；自主执行理念与 HITL 铁律、"默认不自动执行生成代码"冲突。

### 3.3 Agent Laboratory（SamuelSchmidgall/AgentLaboratory，AMD/JHU，2025）

- **是什么**：端到端科研助手：输入研究想法 → 文献综述 → 实验（mle-solver）→ 写论文（paper-solver）。
- **可借鉴**：mle-solver 的**迭代执行-修复**（ Kaggle MLE-Bench 拿过金牌）：生成→运行→按报错改→再运行，循环有界。与我们 B 期"冒烟验证+一次修复"同思路，佐证"有界迭代"比"一次生成"有效。
- **不照搬**：端到端自主科研（literature→code→paper 一条龙），与 GapMind 的 HITL 定位正交；其 Kaggle 场景（现成数据集+leaderboard）与我们不符。

### 3.4 CodeScientist（allenai/codescientist，ACL 2025 Findings）

- **是什么**：AI2 的自动化科学发现系统：以代码实验为载体，"想法×实验"共同进化（遗传搜索），容器内自动生成-运行-查错-重跑；支持 HITL 与全自动两种模式。
- **可借鉴**：容器内**自动 bug 检测与重跑**（B 期 sandbox 升级的参照）；其 HITL 模式（人筛想法、人给反馈）印证 GapMind 的产品定位。
- **不照搬**：遗传搜索需要大规模并行实验算力；依赖 Claude 级模型；目标是无人生成"新发现"，我们是辅助人生成"可审查的实验骨架"。

### 3.5 MLR-Copilot（du-nlp-lab/MLR-Copilot，2024）

- **是什么**：与我们**结构最像**的系统：三阶段 = 研究想法生成（读文献）→ 实验实现（想法转代码）→ 实验执行（运行验证）。
- **可借鉴**：阶段间以结构化"研究想法卡"（motivation/idea/experiment plan）交接——对应我们 Discover 产出的 opportunity → plan → code 链路，可把"实验计划卡"的字段（数据集/模型/评估步骤）更细地喂给代码生成。
- **不照搬**：实现绑定其自有 pipeline 与 OpenAI 系模型；工程活跃度一般。

### 3.6 评测基准：PaperBench（OpenAI，ICML 2025）与 CORE-Bench（Princeton/JHU）

- **事实**：PaperBench 上最强 agent（Claude 3.5 Sonnet + OpenAI 自研框架）平均复现得分 **21.0%**，人类 ML 博士 ~41.3%；CORE-Bench 困难任务最好成绩也 ~21%。**"完整复现论文"对当前所有 agent 都是未解难题。**
- **对我们的意义**：
  1. 定位校准：GapMind 代码生成的合理目标是**"可审查的最小实验骨架"**（能跑冒烟、结构完整、与计划对齐），不是"复现论文结果"。现有 prompt 已是这个方向，保持；
  2. 借鉴 rubric 方法：把"是否覆盖计划"拆成机器可查的条目（文件/入口/数据集/基线/指标/种子），生成后逐项打勾并作为 artifact 展示——把"生成了 N 个文件"升级为"计划覆盖度 checklist"。

---

## 四、改进方案

### 4.0 设计原则（与项目铁律对齐）

1. 复用 `AgentRun/AgentStep/AgentArtifact` 协议（约定 6），多阶段=同一 run 内的多个 Step，不新增状态系统、不加新 agent 名义；
2. 不引入任何外部框架/运行时依赖（全部在 `agent/service.py` 内实现，文件可能需要拆分）；
3. HITL 铁律不变：产物仍止步于 artifact（预览/下载），确认落正式表的机制不变；
4. Evidence Passport 延伸到代码：每个文件带 `evidence_refs`；
5. 执行验证永远 opt-in + 有界（默认关，`AGENT_CODE_EXECUTION_ENABLED=true` 才开；无网络、只读、限时、限内存，只跑测试/冒烟，绝不跑完整实验项目）；
6. LLM 调用全部 `disable_thinking=True`，token 用量累计进 `stage_summaries["token_usage"]`（P0-3 已有机制）。

### 4.1 目标流水线（改造后）

```
code_generation run 内部：
┌─ Step1 evidence_retrieval   语义检索证据 + （B期）方法细节分面检索
├─ Step2 module_design        LLM 产出项目蓝图 JSON：
│                             模块清单/每模块职责/文件清单/文件间依赖/
│                             每文件要引用的 evidence_refs/入口与测试位置
├─ Step3..N incremental_gen   按蓝图逐文件（或逐模块）生成：
│                             上下文 = 蓝图 + 计划 + 该文件证据 + 已生成文件的接口摘要
├─ StepK consistency_review   纯 Python 静态检查（不花 LLM）：
│                             imports↔requirements 一致 / 蓝图文件齐全 /
│                             入口存在 / 测试存在 / 路径合法
├─ StepK+1 rubric_check       LLM 对照计划的 datasets/baselines/metrics/
│                             validation_steps 逐项核对 → checklist artifact
└─ (opt-in) smoke_validation  Docker 有界运行 pytest/入口 --help 冒烟
                              失败 → 收集 stderr → 一次定点修复 → 复跑（≤1 轮）
```

### 4.2 Phase A（比赛期可完成、可演示、零基础设施变更）

| 项 | 内容 | 对应弱点 |
|----|------|---------|
| A1 蓝图阶段 | 新 `_code_blueprint_prompt`：输入计划+证据，输出模块/文件/依赖/每文件 evidence_refs 的 JSON（约 1.5k token 预算） | W1 W2 |
| A2 逐文件生成 | 按蓝图循环调用，每次 1-2 个文件、4k token 上限；上下文带蓝图与已生成文件"接口摘要"（import/类与函数签名），不带全文 | W1 |
| A3 做实 static_review | 纯 Python：AST 解析 imports 对拍 requirements.txt；蓝图清单 vs 实际文件；入口/测试存在性；结果写进 Step 详情与 run.result | W7 |
| A4 rubric 自检 | `_code_rubric_prompt`：对照 plan 的 datasets/baselines/metrics/validation_steps 输出 checklist（covered/partial/missing + 说明），存为 `artifact_type="report"` 产物 | W5 |
| A5 证据护照 | 每个 code artifact 的 `metadata_payload` 记录该文件的 `evidence_refs`（来自蓝图）；前端文件预览可展示"依据：[E3] [E7]" | W6 |

改动面：`agent/service.py`（主要）、`agent/schemas.py`（result 增字段）、前端 CodeGeneration 页（蓝图/checklist 展示，`npm run gen:api`）。无迁移、无新表。

### 4.3 Phase B（有界验证闭环，需 Docker，仍默认关）

| 项 | 内容 | 参照 |
|----|------|------|
| B1 CodeRAG-lite | 检索升级：除 evidence 外，按"方法步骤/公式/超参数/数据预处理"分面检索工作区 chunks（复用 retrieval 域，多 query），公式以 LaTeX 文本进 prompt | DeepCode CodeRAG |
| B2 sandbox 升级 | 从 py_compile → 可选运行：预装科学计算基础镜像（`python:3.11-slim` + torch/numpy/pandas/sklearn 层），无网络、只读、限时（如 120s）、限内存 pids（参数已有）；只跑 `pytest -x` 与入口 `--help`/`--dry-run` 冒烟 | CodeScientist / mle-solver |
| B3 修复迭代 | 冒烟失败 → 抽取 stderr 尾部 + 出错文件 → 一次定点修复调用 → 复跑一次；两轮都失败则如实标注 `validation_status=failed`，不阻塞 artifact 产出；全过程 AgentStep 可观测 | DeepCode verification |

风险与缓解：镜像体积（用 slim+CPU torch，本地 build 一次）；无网络装不了 requirements（B2 白名单预装 + prompt 约束只允许白名单依赖）；Windows 下 Docker Desktop 依赖（validation 保持 opt-in，失败降级为 A3 静态结果，不影响主流程）。

### 4.4 Phase C（赛后/时间富余）

- C1 参考实现挖掘：从 S2/GitHub 链接抓取相关开源实现片段做 grounding（DeepCode Reference Mining 的轻量版）；
- C2 结果分析闭环：analyze agent 消费冒烟运行日志与产物指标；
- C3 评测：在 `evaluation/` 加 PaperBench 式 rubric 评测（固定小规模 gold set，遵守"不为过评测改 Gold Set"纪律）。

### 4.5 铁律兼容性自查

| 铁律 | 结论 |
|------|------|
| 不引入重型框架 | ✅ 全部自研于 agent 域，零新依赖 |
| 复用 Agent 协议 | ✅ 多阶段=多 Step |
| HITL | ✅ 产物仍止步 artifact，无自动落表 |
| 默认不自动执行生成代码 | ✅ 执行仅 pytest/冒烟、opt-in、有界；完整实验仍只预览/下载 |
| Evidence Passport | ✅ A5 每文件 evidence_refs |
| disable_thinking | ✅ 沿用 `_structured_completion` |
| Windows/Celery solo | ✅ 无新队列；B 期任务仍在现有 validate task 内 |

### 4.6 工作量估算

- Phase A：后端 ~2-3 天（含测试），前端展示 ~0.5 天；
- Phase B：~2 天（sandbox 与镜像一次性成本为主）；
- Phase C：赛后按需。

---

## 五、明确不做

- ❌ 不 fork/依赖 Paper2Code 或 DeepCode 代码（输入形态、运行时、框架理念均不匹配）
- ❌ 不做端到端自主实验执行（mle-solver 式长时间自主循环）
- ❌ 不宣称"复现论文"——目标定位是"计划对齐的最小实验骨架 + 诚实覆盖度报告"
- ❌ 不为生成代码自动下载数据集/访问网络（sandbox 无网络）

## 六、参考

- Paper2Code：<https://github.com/going-doer/Paper2Code>
- DeepCode：<https://github.com/HKUDS/DeepCode>
- Agent Laboratory：<https://github.com/SamuelSchmidgall/AgentLaboratory> / [arXiv:2501.04227](https://arxiv.org/pdf/2501.04227)
- CodeScientist：<https://github.com/allenai/codescientist> / [AI2 博客](https://allenai.org/blog/codescientist) / [arXiv:2503.22708](https://arxiv.org/abs/2503.22708)
- MLR-Copilot：<https://github.com/du-nlp-lab/MLR-Copilot> / [arXiv:2408.14033](https://arxiv.org/html/2408.14033v3)
- PaperBench：[OpenAI](https://openai.com/index/paperbench/) / [arXiv:2504.01848](https://arxiv.org/html/2504.01848v1)
- CORE-Bench：[GitHub](https://github.com/siegelz/core-bench) / [arXiv:2409.11363](https://arxiv.org/html/2409.11363v2)

---

## 八、Phase A 实施记录（2026-08-19）

改动文件：`backend/app/domains/agent/service.py`、`backend/tests/test_agent_api.py`、`frontend/src/components/chat/ChatAgentRunCard.tsx`、本文档。

### 流水线（code_generation run 内的 AgentStep 序列）

```
workspace_retrieval → module_design（蓝图 JSON，1800 token）
  → code_generation ×N（逐文件，4000 token/文件，上限 8 文件，含接口摘要与证据过滤）
  → static_review（纯 Python 5 项检查，零 LLM）
  → rubric_check（对照计划的覆盖度自检，1600 token，产出 code_rubric.md）
  → artifacts_ready
```

- A1 蓝图：`_code_blueprint_prompt` + `_normalize_blueprint`（路径安全/去重/上限/evidence_refs 防幻觉/README+requirements 兜底）
- A2 逐文件：`_generate_file`（一次重试）+ `_file_prompt`（蓝图+计划+该文件证据+AST 接口摘要）+ `_interface_summary`；蓝图即契约，文件路径强制归位
- A3 静态检查：`_static_review`（蓝图文件齐全/入口/测试/脚手架/imports↔requirements，stdlib 白名单 + sklearn→scikit-learn 等别名）
- A4 rubric：`_code_rubric_prompt` + `_normalize_rubric`（以计划条目为准防漏报）；产物 `artifact_type="code_review"` 的 `code_rubric.md`（markdown 表格）；计数进 `run.result.rubric`
- A5 证据护照：每个 code artifact 的 `metadata_payload` 带 `purpose` + `evidence_refs`（仅真实存在的 E 编号）

`run.result` 新增 `blueprint` / `static_review` / `rubric` / `token_usage(llm_calls)`。

### 前端（ChatAgentRunCard）

代码 Agent 卡片新增：项目蓝图折叠面板（模块 Tag + 文件清单）、静态检查清单（✅/⚠️ + detail，默认展开）、覆盖度计数 Tag（绿/黄/红）、代码文件按钮旁的 E 编号引用 Tag、rubric 报告入口（markdown 预览）；Steps 阶段标签补 module_design/rubric_check。

### 验证

- 后端 398/398、前端 43/43、`tsc --noEmit` 0 错误、`gen:api` 无差异
- 踩坑记录：① `AgentStep.details` 是 dict 类型，塞列表会 pydantic 校验失败；② `run.result` 为 JSON 列，SQLAlchemy 不追踪原地 dict 修改，必须整体重赋值；③ 实机首跑 README.md 生成失败——max_tokens 截断导致 JSON 无闭合（原样重试必然复现），修复为：`_parse_json` 先剥离 markdown 围栏、`_structured_completion` 识别 `finish_reason=="length"` 明确报"被截断"、`_generate_file` 重试时附加精简指令（正文 ≤2000 字符）而非原样重发；`llm_calls` 改为实测调用计数（含重试）

### 实机演示注意

Celery worker 需重启后才会加载新流水线（Windows solo 池不热载）；uvicorn 若带 `--reload` 无需重启。
