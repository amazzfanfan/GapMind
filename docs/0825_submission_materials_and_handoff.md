# 比赛提交资料补齐说明与新会话交接指南

> 文档日期：2026-08-25
> 适用分支：`yx_dev`
> 适用项目：GapMind  赛题交付与 P0 收口

## 1. 文档目的

当前代码、前端、自动化测试、交付模板和 Release Gate 已经整理到可以继续收口的状态，但 P0 不能仅依靠本地代码修改完成。剩余工作需要真实的知识库资料、真实用户测试、可用的 staging 环境和可复核的演练证据。

本文件用于说明：

1. 还需要由项目方补齐哪些资料；
2. 每类资料应达到什么格式和证据标准；
3. 哪些条件满足后可以再次把工作交给 AI 继续执行；
4. 新会话启动时应使用什么上下文和提示词；
5. 交接后 AI 应如何验证、修改、提交和停止。

本文件不允许用虚构数据、模拟用户或伪造录屏来替代真实证据。没有真实证据时，应保持 `pending`，让 Release Gate 继续失败。

## 2. 当前状态与边界

### 2.1 已完成的本地工作

- 后端权限隔离、认证依赖、Workspace/Chat/Task/Reading/Knowledge/Timeline/Paper 等路由的用户边界已补强。
- 新增数据库迁移 `0025_workspace_owner_acl`、`0026_paper_parse_quality`、`0027_chat_conversation_owner`、`0028_search_acl`。
- 增加健康检查、就绪检查、PDF 解析质量字段、证据新鲜度和 Agent 产物状态清单。
- 前端已同步认证、状态提示、证据新鲜度、Agent 产物状态和 API 自动生成类型。
- 后端测试当前候选结果为 `481 passed`；前端测试为 `56 passed`；TypeScript、构建、代码语法检查均已跑通。
- 已建立 `submission/reproducibility/release_gate.ps1`、Smoke Test 和证据记录模板。
- 已完成 PPT v1、比赛交付审查文档、模型/数据/知识源/合规/用户测试等材料模板。

### 2.2 当前不能声称已经完成的内容

- 没有经授权并可复现的比赛知识库快照、许可证记录和最终 SHA-256。
- 当前 Gold 评测仍不足以支撑比赛效果结论，尚未形成 12–20 条冻结问题、标准答案和独立人工复核记录。
- 没有两名真实目标用户的结构化测试记录、授权和可审计反馈。
- 当前 staging 依赖没有启动，尚未完成 PostgreSQL 15 迁移、双 Token ACL、依赖故障演练。
- 没有完成三次三分钟 Demo 彩排、录屏、录屏哈希和冻结的 Workspace/环境边界。
- `submission/` 中仍有待填写字段；最终提交 commit、最终工作区清洁状态和最终材料哈希尚未冻结。

当前 Release Gate 失败是有意的：它在阻止没有证据的材料被误认为已经完成。

## 3. 需要项目方补齐的资料清单

### 3.1 参赛与团队信息

请补齐 `submission/01_参赛信息.md` 中的真实内容：

- 作品名称、作品版本和提交批次；
- 学校/单位、学院/部门、指导教师；
- 团队成员姓名、角色和分工；
- 联系人、邮箱和电话；
- 代码仓库或评审可访问地址；
- Demo 访问地址、访问方式和有效期；
- 是否使用第三方模型、第三方 API、开源数据或开源代码。

要求：只能填写真实信息。若 Demo 只能在本机运行，需明确写成“本地演示”，不要填入不可访问的 localhost 地址作为评审地址。

### 3.2 知识库与数据授权

请提供最终 Demo 使用的知识库快照，至少包括：

- 原始文件或可下载的归档包；
- 每份论文/文档的稳定 ID、标题、作者、来源、发布日期；
- 来源网站或数据库名称；
- 许可证、授权范围、下载日期和使用限制；
- PDF 是否允许本地存储、解析、切分和向量化；
- 文件数量、总大小、解析成功数、失败数和失败原因；
- 最终归档包 SHA-256；
- 语料快照版本号和冻结时间；
- 是否含个人信息、未公开资料、付费墙内容或其他敏感数据。

建议把归档包放在项目外部的可访问位置，不要把大体积 PDF 或真实密钥直接提交到仓库。完成后填写：

- `docs/0824_knowledge_source_registry.md`
- `docs/0824_knowledge_snapshot_manifest.md`
- `submission/reproducibility/data_manifest.md`
- `submission/07_其他材料与许可证清单.md`

最低验收标准：`data_manifest.md` 中至少出现一个真实、可复核的 64 位 SHA-256，且哈希能够在交接时重新计算一致。

### 3.3 模型、Embedding 和运行配置

请提供最终 Demo 实际使用的模型信息，而不是仅写“使用大模型”：

- 主 LLM 的服务商、模型名、版本或模型文件 digest；
- 备用 LLM 的服务商、模型名和启用条件；
- Embedding 模型名称、版本、向量维度；
- Reranker 名称、版本和是否实际启用；
- 研究空白棋盘使用的模型名称、版本和访问方式；
- Ollama/远程服务的模型导出信息或镜像 digest（如可提供）；
- 关键 prompt 版本、检索参数、Top-K、阈值和上下文长度；
- 运行时 Python/Node/系统依赖版本；
- 网络边界：哪些请求离开本机，发送了哪些数据，是否保存日志；
- API Key 只说明“已配置”，不要把密钥放入仓库或文档。

完成后填写：

- `docs/0824_model_card.md`
- `docs/0824_model_manifest.md`
- `submission/reproducibility/model_manifest.md`
- `submission/05_作品代码与技术报告.md`

最低验收标准：模型 manifest 至少包含真实模型名和可复核的版本号、digest 或 64 位哈希，并与 Demo 使用的配置一致。不能用“待填写”或示例哈希通过门禁。

### 3.4 Gold 评测集与人工复核

当前只有少量离线评测样例，不能直接作为比赛效果报告。请准备冻结版 Gold Set：

- 总数 12–20 条问题；
- 覆盖论文定位、证据引用、相似工作、反证/局限、研究空白、研究计划等核心路径；
- 每条问题有标准答案或评分要点；
- 每条标准答案明确应引用的 `[En]` 证据，以及允许的 `[Pn]`/`[Dn]`/`[Cn]` 类型；
- 标明问题难度、目标功能和不可接受的回答；
- 固定语料快照、模型配置和评测参数；
- 至少一轮独立人工复核，最好采用 reviewer 1 / reviewer 2 的盲评记录；
- 保存每条问题的人工 verdict、错误类型、证据覆盖和修改意见；
- 明确区分“机械校验通过”和“人工认为回答有效”。

完成后填写：

- `docs/0824_gold_evaluation_plan.md`
- `docs/0824_manual_review_register.md`
- `docs/0824_baseline_ab_report.md`
- `submission/06_效果验证报告.md`
- `submission/evidence/gold_review_record.md`

最低验收标准：`gold_review_record.md` 中 `question_count` 为 12–20，且每条问题都有标准答案、证据判断和人工复核状态。人工 verdict 必须来自真实 reviewer，不能由 AI 自动补齐。

### 3.5 真实目标用户测试

请至少邀请两名符合目标画像的真实用户，例如科研教师、博士生或科研管理人员，并保留脱敏记录：

- 匿名用户 ID、角色和学科方向；
- 测试日期、环境和使用版本；
- 测试前授权或同意记录；
- 每名用户完成的任务列表；
- 任务是否完成、耗时、卡点和错误；
- 对引用可信度、研究空白、计划生成和代码生成的反馈；
- 用户发现的问题及其优先级；
- 截图或录屏（脱敏后）；
- 测试结束后的简短访谈或问卷结果。

不要提交用户姓名、手机号、邮箱、未授权论文或包含敏感信息的原始截图。完成后填写：

- `docs/0824_personas_and_tasks.md`
- `docs/0824_user_test_script.md`
- `submission/evidence/user_test_record.md`

最低验收标准：至少两条真实、可追溯、已脱敏的用户记录，而不是只写一段“用户反馈良好”。

### 3.6 Staging 环境与安全演练

请准备可运行的 staging 环境，至少包含：

- PostgreSQL 15；
- Redis 7；
- Milvus 2.4 及其依赖；
- 后端 API、Celery worker、前端；
- 可访问的 LLM/Embedding/S2 配置，或明确的可重复 Mock 方案；
- 数据库迁移可执行到 `0028_search_acl`；
- 两个不同用户 Token；
- 一个 Workspace、至少一条 Chat 会话、论文、阅读记录、任务和搜索收藏数据。

必须执行并记录：

- 用户 A 访问自己的 Workspace、Chat、Task、Reading、Knowledge、Timeline、Paper 数据；
- 用户 B 访问用户 A 数据应得到明确的 401/403/404 失败结果；
- 用户 A 与用户 B 可独立收藏同一外部论文；
- 未认证请求在要求认证的接口上被拒绝；
- 数据库、Redis、Milvus、Embedding、LLM、S2 任一依赖短暂不可用时，系统给出可理解的降级或错误提示；
- 健康检查与 readiness 检查返回符合预期的状态。

完成后填写：

- `docs/0824_dependency_state_matrix.md`
- `docs/0824_security_checklist.md`
- `submission/evidence/staging_smoke_record.yml`
- `submission/evidence/dependency_drill_record.md`

最低验收标准：Smoke 记录中 `status: pass` 且 `cross_user_acl: pass`，每个依赖故障都有时间、操作、预期、实际结果和日志/截图索引。

### 3.7 三分钟 Demo 彩排与冻结

请使用最终知识库和最终配置完成至少三次完整彩排：

- 彩排 1：发现问题并修正操作路径；
- 彩排 2：按正式比赛节奏计时；
- 彩排 3：作为最终候选版本，冻结 Workspace、数据、模型和配置。

每次彩排记录：

- 日期、版本、操作人；
- 开始和结束时间；
- 是否在三分钟内完成；
- 是否经过论文导入、解析、检索、引用、Discover、HITL、研究计划等关键路径；
- 每一步实际耗时；
- 失败、降级或人工补救动作；
- 录屏文件名、大小和 SHA-256；
- 最终冻结的 Workspace ID、数据快照 ID 和 Git commit。

完成后填写：

- `submission/demo/three_minute_demo_script.md`
- `submission/evidence/demo_rehearsal_record.md`
- `submission/03_Demo地址与操作手册.md`

最低验收标准：至少三条真实彩排记录，最终录屏可播放且哈希可复核。没有录屏时，不要把 Demo 状态写成“已完成”。

### 3.8 最终提交包

资料齐全后，补齐以下文件中的真实字段：

- `submission/01_参赛信息.md`
- `submission/02_伦理与安全合规声明.md`
- `submission/03_Demo地址与操作手册.md`
- `submission/05_作品代码与技术报告.md`
- `submission/06_效果验证报告.md`
- `submission/07_其他材料与许可证清单.md`
- `submission/reproducibility/data_manifest.md`
- `submission/reproducibility/model_manifest.md`
- `submission/evidence/*.md` 与 `submission/evidence/*.yml`

最终阶段还需要：

- 确认 `yx_dev` 为最终提交分支；
- 确认所有应该提交的代码和文档已经 commit；
- 确认 `deploy/`、密钥、原始大文件和比赛 PDF 没有被误提交；
- 运行全套测试、Smoke Test 和 Release Gate；
- 生成最终交付包清单及 SHA-256；
- 由项目负责人进行一次人工逐项审查。

## 4. 何时可以再次把工作交给 AI

### 4.1 现在不适合交付的原因

如果以下条件仍不满足，AI 只能继续做模板、脚本和代码级改进，不能完成真正的比赛交付：

- 没有真实语料或授权信息；
- 没有 12–20 条 Gold 问题和人工 reviewer；
- 没有两名真实目标用户；
- 没有可启动的 staging 或明确的远程环境；
- 没有三次彩排和最终录屏；
- 没有决定最终提交的模型、数据和 Demo 版本。

### 4.2 推荐的交接时机

建议在满足以下“交接包”后再开启新会话：

1. 把真实数据、模型和录屏放在项目外部的安全路径，并准备好哈希；
2. 将已填写的 `submission/` 材料和 `submission/evidence/` 记录放入工作区；
3. 启动 staging，确认 API、前端、PostgreSQL、Redis、Milvus 和必要模型服务可访问；
4. 准备两个测试 Token，并明确哪个 Token 对应用户 A/B；
5. 至少完成一轮 Gold 人工评测和一次真实用户测试；
6. 在新会话提示词中列出所有实际路径、访问方式、禁止事项和目标截止时间。

### 4.3 交接前自检

交接前请先执行：

```powershell
cd D:\MyCode\Spark-competition\refactor\GapMind
git status --short
Get-NetTCPConnection -State Listen
cd backend
.venv\Scripts\python.exe -m pytest tests/ -q
cd ..
.\submission\reproducibility\smoke_test.ps1 -RequireAuth
.\submission\reproducibility\release_gate.ps1
```

此时不要求 Release Gate 已经通过，但应把失败项从“占位符/缺资料”缩小到具体的最终审查问题，并把真实失败输出一并交给 AI。

## 5. 新会话提示词

下面的提示词适合在资料补齐、staging 可用后直接复制到新会话。使用前请替换尖括号中的内容，不要把真实 API Key 放入提示词。

```text
这是 GapMind 比赛项目，请在 Windows 工作区
D:\\MyCode\\Spark-competition\\refactor\\GapMind
的分支 yx_dev 上继续工作。

项目目标：完成比赛交付 P0 的最终收口，不要重新设计项目，也不要伪造任何证据。请先阅读并遵守：

1. AGENTS.md；
2. docs/0825_p0_completion_audit.md；
3. docs/0825_submission_materials_and_handoff.md；
4. docs/0824_competition_delivery_board.md；
5. docs/0824_competition_todolist.md；
6. submission/reproducibility/release_gate.ps1；
7. submission/evidence/README.md。

当前真实交接资料：
- 知识库快照：<外部路径或归档路径>
- 数据 manifest：<已填写文件路径>
- 模型 manifest：<已填写文件路径>
- Gold Set：<路径>，共 <数量> 条
- 人工 reviewer 记录：<路径>
- 用户测试记录：<路径>
- Demo 录屏与 SHA-256：<路径>
- staging 地址：<地址>
- 用户 A Token 注入方式：<环境变量名或安全方式>
- 用户 B Token 注入方式：<环境变量名或安全方式>
- 最终截止时间：<时间>

本次任务按以下顺序执行：

第一阶段：只读盘点
- 检查 git status、当前 commit、分支和受保护文件。
- 检查 8000、5173、5432、6379、19530、11434 的实际状态。
- 复核数据/模型哈希、Gold 数量、人工记录、用户记录、录屏哈希。
- 运行 release_gate.ps1，列出剩余失败项，并把每项映射到具体文件或操作。

第二阶段：真实环境验证
- 执行 Alembic upgrade head，并确认 head 为 0028_search_acl。
- 用用户 A/B 做 Workspace、Chat、Task、Reading、Knowledge、Timeline、Paper 和收藏的跨用户 ACL 矩阵测试。
- 执行 smoke_test.ps1 -RequireAuth。
- 按 dependency_drill_record.md 逐项执行依赖故障演练。
- 使用冻结数据和模型运行 Gold 评测；区分机械结果、模型结果和人工 verdict。
- 核对三分钟 Demo 的实际路径、录屏和冻结 Workspace。

第三阶段：只修复真实发现的问题
- 只修复可复现的代码、配置、文档或交付问题。
- 后端模型变化必须同步迁移、测试和 OpenAPI；前端 API 类型必须通过 npm run gen:api 生成，禁止手写 api.gen.ts。
- 保持数据按 workspace_id 和用户隔离；不得硬删除数据。
- 所有 LLM 调用保持 disable_thinking=True，不要同时传 reasoning_effort。
- 不能把 AI 生成内容直接升级为人工事实；所有 Gold verdict、用户反馈和合规结论必须保留真实来源。
- 不要修改固定 Gold 数据来“过门禁”，不要把测试替代真实用户证据。

第四阶段：验证与交付
- 运行后端全量测试、前端测试、tsc、构建、compileall、Smoke Test 和 Release Gate。
- 更新 docs/0825_p0_completion_audit.md，使每个结论都能指向实际证据。
- 只有所有真实材料齐全且 Release Gate 通过后，才可以说明 P0 完成。
- 如果仍缺真实数据、用户、staging 或录屏，停止并输出精确阻塞清单，不要伪造、不自我宣布完成。

提交纪律：
- 可以修改代码和文档，但先展示 diff、测试结果和待提交文件清单。
- 只有我明确说“可以 commit”后才执行 git commit；commit 信息使用中文。
- 不要 push。
- 不要改动或提交 deploy/、比赛 PDF、真实密钥、原始大体积数据和根目录 index.html，除非我明确授权。
```

## 6. AI 新会话的预期输出格式

新会话开始后，要求 AI 先输出以下内容，再执行有风险的修改：

1. 当前分支、HEAD、工作区状态；
2. 运行中的服务和版本；
3. 已收到的真实资料及哈希核对结果；
4. Release Gate 当前失败项；
5. 本轮计划修改的文件和不修改的文件；
6. 验证命令和通过标准；
7. 若遇到外部阻塞，明确说明需要谁提供什么资料。

这样可以避免新会话重复扫描项目，也可以防止把“代码通过测试”误报为“比赛交付已经完成”。
