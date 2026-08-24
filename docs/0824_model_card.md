# GapMind 垂类能力与模型口径卡（T2-02 初稿）

**状态**：初稿，训练/微调证据和模型 digest 待补
**制定日期**：2026-08-24
**适用分支**：`yx_dev`
**对应任务**：T2-02 判断并记录“垂类模型”口径
**关联清单**：`docs/0824_model_manifest.md`

## 一、结论先行

当前最准确、风险最低的比赛口径是：

> GapMind 采用通用生成模型完成受控的科研问答、研究机会候选、Critic 反馈和计划/代码草稿生成；采用 BGE-m3 与 reranker 建立论文证据检索链路；采用 `research-dataset-qwen3` 作为研究空白棋盘的垂类抽取/标注组件，并通过 Evidence Passport、Evidence Gate 和 HITL 将输出限制在可追溯、可审阅的科研流程中。

因此，当前不应宣称“最终生成模型已经完成图机器学习领域 SFT”。产品的垂类能力来自以下组合：

1. 图机器学习/图神经网络的受控 Workspace 资料与证据回链；
2. 研究空白抽取模型的结构化 Schema 约束；
3. 面向科研任务的检索、反证、外部核验、Critic 和 Evidence Gate 工作流；
4. 研究者/导师对候选、计划和代码草稿的人工确认。

## 二、模型角色矩阵

| 模型/组件 | 是否垂类 | 输入 | 输出 | 当前职责 | 不能据此宣称 |
|---|---|---|---|---|---|
| `deepseek-v4-flash` | 通用生成模型 | 用户问题、检索证据、研究机会状态、计划字段 | 问答、归纳、候选、Critic/计划/代码草稿 | 受控生成与草稿编排 | 已完成图机器学习领域 SFT；自动完成新颖性判断 |
| `BAAI/bge-m3` | 通用多语言 Embedding | 论文 Chunk、用户查询 | 1024 维向量 | 语义召回 | 直接理解科学事实；向量相似等于证据支持 |
| `BAAI/bge-reranker-v2-m3` | 通用重排模型 | 查询 + 召回文本 | 相关性排序 | 二阶段排序 | 排序结果等于事实正确性或新颖性结论 |
| `research-dataset-qwen3:run7-q8-templatefix` | 垂类抽取/标注组件 | 论文 Markdown + Gap Board 指令 | 方法/问题等结构化标注 | 方法 × 问题棋盘抽取、Schema 校验和有限修复 | 最终科研写作生成；自动证明研究空白成立 |
| Semantic Scholar | 外部知识服务 | 研究轴、方法名、论文 ID | 论文元数据、开放全文线索 | 外部新颖性与相似工作核验输入 | 完整、实时、权威的新颖性裁决 |

## 三、垂类抽取模型卡（当前可证据范围）

### 3.1 基本信息

| 字段 | 当前记录 |
|---|---|
| 模型 ID | `research-dataset-qwen3:run7-q8-templatefix` |
| Provider | Ollama；开发机默认访问 `http://127.0.0.1:11434` |
| 真实部署位置 | 项目约定为服务器 Ollama，通过 SSH 隧道访问；本机不应启动 Ollama 占用同一端口 |
| 输入 | 解析后的论文 Markdown，以及 `backend/app/domains/gap/prompt.py` 中的抽取指令 |
| 输出 | `GapAnnotationOutput` 结构化 JSON，经 `parse_model_json` 和 `validate_annotation` 校验 |
| 主要实体类型 | `RESEARCH_PROBLEM`、`TASK`、`METHOD`、`MODEL`、`DOMAIN`、`OTHER_SCIENTIFIC_TERM` |
| 主要消费者 | Gap Board；未确认的棋盘格交给 Discover 做外部证据核验 |
| 模型参数 | `num_ctx=32768`、`num_predict=4096`、`temperature=0.01`、`top_p=1.0`、`repeat_penalty=1.05`、`seed=42` |
| 校验失败处理 | 默认最多 2 次 repair；最终失败保留错误类别，不生成有效棋盘结论 |
| digest | 当前配置 `GAP_EXTRACTOR_MODEL_DIGEST` 为空，待补 |

### 3.2 训练与数据证据状态

当前代码和配置能够证明模型 ID、推理位置、输入输出 Schema、校验规则和失败处理，但不能独立证明以下内容：

- 训练语料的完整来源、许可、去重和脱敏记录；
- Base model、LoRA/SFT 配置、训练步数、数据规模和训练日期；
- 该模型相对于通用模型的离线准确率提升；
- 模型权重 digest、Ollama Modelfile 和服务器实际 build；
- 研究空白抽取错误率、漏召回率和跨学科泛化能力。

因此，比赛材料中若需要使用“微调模型”字样，应在提交前补齐模型卡、训练/权重来源、版本和对照评测；否则使用“垂类抽取/标注组件”更准确。

## 四、通用生成模型卡（当前可证据范围）

| 字段 | 当前记录 |
|---|---|
| 模型 ID | `deepseek-v4-flash` |
| Provider | DeepSeek OpenAI 兼容 API |
| 代码入口 | `backend/app/gateway/llm.py` |
| 使用场景 | Workspace Chat、Discover Planner/Opportunity/Critic、研究计划和代码草稿等 |
| 结构化调用约束 | `disable_thinking=True`；不得同时传 `reasoning_effort` |
| 备用机制 | 只有 `DEEPSEEK_BACKUP_API_KEY`、`DEEPSEEK_BACKUP_BASE_URL`、`DEEPSEEK_BACKUP_MODEL` 全部配置时启用 |
| 产物边界 | 回答带来源一致性检查；研究机会是候选；计划/代码是 AI 草稿；代码默认只静态检查和预览/下载 |
| 可证明范围 | 已有网关、调用约束、fallback 逻辑和自动化测试 |
| 待证明范围 | 真实外部调用稳定性、领域生成质量、用户效果和成本/延迟分布 |

通用生成模型的输出不直接成为论文事实、已确认的新颖性结论或正式研究资产。进入长期资产前需要 Evidence Passport、版本和人工确认。

## 五、Embedding 与 Reranker 卡

### 5.1 BGE-m3

- 模型：`BAAI/bge-m3`；维度：1024；服务：SiliconFlow OpenAI 兼容 Embedding API。
- 输入主要是论文 Chunk 和用户检索问题；输出用于 Milvus dense retrieval。
- Embedding 不负责事实判断，也不负责决定引用是否真正支持问题。
- 当前没有记录远程服务实际 build、批量成本、P50/P95 延迟和跨领域质量，不能把固定 corpus 的召回观察点外推为通用效果。

### 5.2 BGE reranker

- 模型：`BAAI/bge-reranker-v2-m3`；服务：SiliconFlow `/v1/rerank`。
- 输入是查询和 Milvus 召回文本，输出是相关性排序。
- 重排失败时检索链路可以降级为向量召回，并标记 `reranker_degraded`。
- 相关性排序不是事实正确性、证据覆盖或新颖性判断；这些由来源校验、Evidence Gate、Critic 和人工判断共同约束。

## 六、风险与控制

| 风险 | 当前控制 | 仍需补齐 |
|---|---|---|
| 把抽取模型写成垂类生成模型 | 材料明确拆分抽取、检索、生成和 HITL 职责 | 训练/微调证据、模型卡和对照实验 |
| 模型生成无来源结论 | Chat 来源隔离、`[En]` 一致性检查、证据不足 fail closed | 冻结 Gold 和人工事实评审 |
| 把相似度当新颖性 | Discover 的支持/反证、外部核验、Critic、Evidence Gate | 真实用户和典型机会案例 |
| 远程服务接收敏感材料 | 后端保管 key；远程 Gap 抽取默认关闭；需要显式同意 | 数据分类、外发提示、留存和删除策略 |
| 模型服务版本漂移 | 配置记录模型 ID | digest、服务版本、提示词/Schema 版本和 checksum |
| 代码草稿被误认为已执行 | UI/产物标识静态检查和未执行状态 | 提交包中的状态字典与截图证据 |

## 七、提交材料推荐写法

可以写：

- “系统采用垂类研究空白抽取组件、领域知识库和证据驱动工作流增强科研任务表现。”
- “通用生成模型负责受控问答和草稿生成，关键研究判断由用户确认。”
- “方法—问题棋盘的候选格不会自动成为研究事实，而是交给 Discover 进行证据核验。”
- “当前已完成工程闭环和离线评测基础，真实用户效果与外部服务持续稳定性仍在验证。”

不要写：

- “已完成图机器学习领域生成模型 SFT”；
- “模型自动判断研究方向是否新颖”；
- “代码已经执行并复现结果”；
- “模型在所有论文和学科上都具备稳定效果”；
- “自动化测试通过证明用户已经认可”。

## 八、T2-02 验收记录

- [x] 已区分通用生成模型、Embedding、Reranker、垂类抽取模型和外部知识服务。
- [x] 已给出当前可证明的垂类口径：抽取/标注组件 + 领域证据 + 受控工作流。
- [x] 已记录输入、输出、推理位置、调用约束和失败边界。
- [ ] 训练/微调数据、LoRA/SFT 配置、训练日期和权重来源待补。
- [ ] 模型 digest、服务 build、Prompt/Schema 版本和对照评测待补。
- [ ] 真实用户效果和典型研究机会人工结论待 T3-01～T3-03、T2-06～T2-08。
