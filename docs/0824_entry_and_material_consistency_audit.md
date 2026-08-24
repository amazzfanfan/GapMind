# GapMind 文档与入口一致性审计（T0-04 / T1-04）

**审计日期**：2026-08-24
**分支**：`yx_dev`
**范围**：README、前端入口、Demo 脚本、PPT 初稿、效果验证模板、模型清单、提交目录和看板证据路径

## 一、结论

当前对外产品主叙事已经基本统一：

- 主学科：计算机科学—图机器学习/图神经网络；
- 用户：研究生/科研助理、导师/教师；
- 任务：证据问答、研究机会核验、研究计划/代码草稿辅助；
- 边界：AI 输出是候选或草稿，关键研究判断由用户确认；GraphRAG、成熟多模态、自动代码执行、最终生成模型 SFT、多租户规模化和真实用户效果不作为当前已完成能力。

当前不能把 T0-04 或 T1-04 标记为完全完成，原因是根目录仍有旧原型文件、外部服务/资料版本尚未冻结、真实用户和视频证据尚未形成。

## 二、已核对的入口和材料

| 检查项 | 当前状态 | 证据 |
|---|---|---|
| README 产品定位 | 通过 | `README.md` 已使用冻结的学科、用户、三类任务和禁止宣称 |
| 正式前端入口 | 通过 | `frontend/index.html` → `frontend/src/main.tsx`，标题为 GapMind |
| 后端入口 | 通过 | `backend/app/main.py`，README 指向 `http://localhost:8000` 和 `/docs` |
| 作品方案 PPT | 通过初稿 | `submission/GapMind_作品方案_v1.pptx`、`submission/04_作品方案_v1.pptx`，14 页，可正常重新打开 |
| 详细 Demo 脚本 | 通过话术边界 | `docs/0811_demo_script.md` 已同步学科、用户、任务和禁止宣称 |
| 三分钟 Demo 检查 | 已建立 | `docs/0824_three_minute_demo_checklist.md` |
| 效果验证材料 | 仅模板 | `docs/0824_effect_validation_report_template.md`，真实 Gold/用户数据待填 |
| 模型与服务口径 | 已形成初稿 | `docs/0824_model_manifest.md`、`docs/0824_model_card.md` |
| 提交物目录 | 已建立工作副本 | `submission/` 已有 01—07 材料、Demo 脚本和 reproducibility 骨架；真实地址、效果数据、授权快照和最终版本仍待冻结 |

## 三、发现的问题与处理决定

### 3.1 根目录旧原型入口

根目录 `index.html` 是未跟踪的独立静态原型，页面内容仍出现 `GraphRAG-X`，与 GapMind 当前正式产品叙事不一致。它不是 `frontend/` 的 Vite 入口，也没有被 README 启动命令引用。

处理决定：

1. 正式产品入口固定为 `frontend/`；
2. 根目录 `index.html` 不纳入比赛提交物，不作为产品链接或截图来源；
3. 不删除或覆盖该用户已有未跟踪文件；
4. 公开 Demo 和提交手册必须直接指向 `frontend` 启动后的 GapMind 页面，不能要求评委打开仓库根目录 HTML。

### 3.2 历史 Demo 资料和服务状态

`docs/0811_demo_script.md` 中的 `self-interpretable gnn`、19 篇论文、服务状态和历史阶段描述属于历史彩排前置条件，不等同于当前已冻结的比赛数据包。

处理决定：

1. 保留该文档作为详细彩排记录；
2. 三分钟提交版使用 `docs/0824_core_demo_tasks.md` 和后续 T2-04/T3-05 的冻结快照；
3. 在快照生成前，不把 19 篇、候选数量、外部服务可用性或历史成功记录写成当前效果数字。

### 3.3 文档中的版本和测试数量

`docs/0824_baseline_manifest.md` 记录的是基线时点；旧日期文档中的测试数量、迁移 head 和阶段状态可能不同。提交材料只能引用最新候选版本的版本清单，不应将历史记录覆盖为当前事实。

当前候选版本应以以下信息为准，并在 T5-02 再冻结一次：

- 审查起点记录的 Alembic head：`0024_chat_generation_observability`；当前候选工作区已新增 `0025_workspace_owner_acl`、`0026_paper_parse_quality`、`0027_chat_conversation_owner`、`0028_search_acl`，候选 head 为 `0028_search_acl`，最终仍需在冻结环境确认；
- 审查起点后端：469 tests 通过的记录；当前候选已完成认证、配额、解析质量、资源级 owner scope 和状态/导出边界改造，全量为 481 tests 通过，最终冻结时仍需重跑回填；
- 前端：56 tests 通过的记录；
- TypeScript、生产构建和 lint 的最新命令输出；
- 模型、Prompt、Schema、资料快照和 Milvus collection 的版本/哈希。

## 四、路径检查结果

### 已存在且可作为当前材料的路径

- `README.md`
- `docs/0811_demo_script.md`
- `docs/0824_scope_and_claims.md`
- `docs/0824_domain_positioning.md`
- `docs/0824_personas_and_tasks.md`
- `docs/0824_core_demo_tasks.md`
- `docs/0824_product_messaging_draft.md`
- `docs/0824_solution_ppt_outline.md`
- `docs/0824_effect_validation_report_template.md`
- `docs/0824_three_minute_demo_checklist.md`
- `docs/0824_model_manifest.md`
- `docs/0824_model_card.md`
- `submission/GapMind_作品方案_v1.pptx`

### 已在看板中规划、但尚未形成提交物的路径

以下路径属于后续 P0 任务产物，当前不能在提交说明中当作已完成链接：

- `submission/01_参赛信息.md`（工作副本，待用户填写）
- `submission/02_伦理与安全合规声明.md`（工作副本，待最终合规复核）
- `submission/03_Demo地址与操作手册.md`（工作副本，待填写正式地址）
- `submission/05_作品代码与技术报告.md`（工作副本，待冻结版本信息）
- `submission/06_效果验证报告.md`（工作副本，待真实效果证据）
- `submission/07_其他材料与许可证清单.md`（工作副本，待授权清单）
- `submission/reproducibility/`（已有入口、manifest 和 Smoke Test 骨架，待冻结环境执行）
- `submission/demo/`（已有三分钟脚本，待彩排/录屏）

## 五、T0-04 / T1-04 验收状态

- [x] 学科、用户、三条核心任务在 README、ChatHub、Demo、PPT 大纲和效果模板中保持一致。
- [x] 禁止宣称已同步到 README、详细 Demo 脚本、PPT 初稿、模型卡和效果验证模板。
- [x] 已明确正式前端入口为 `frontend/`，根目录旧原型不属于交付入口。
- [x] 已将 PPT 交付物放入被忽略的 `submission/`，其余说明材料放入 `docs/`；`submission/` 已建立 01—07、Demo 和 reproducibility 工作副本。
- [ ] T1-04 的真实用户效果、视频/录屏和现场链接待 T3-01～T3-06。
- [ ] T0-04 的最终提交链接、冻结资料和候选版本回归待 T2-04、T3-05、T5-01～T5-05。

## 六、后续动作

1. 先建立权威知识源台账和最小脱敏快照，再更新详细 Demo 的资料数量与服务状态；
2. 完成冻结 Gold、人工评审和真实用户记录后，填充效果报告，不修改历史数据冒充当前效果；
3. 补齐 `submission/` 工作副本中的真实地址、授权、效果和最终版本字段；
4. 最终回归时重新检查所有链接、版本、测试输出和入口说明。
