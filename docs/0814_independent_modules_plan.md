# 0814 P1.5 模块独立化详细计划

> 日期：2026-08-14
> 作者：yx
> 状态：已实施（配套 `0814_changes_summary.md` 改动总结）
> 关联：`0811_todolist.md` P1.5、根目录 `index.html`（生命周期模块展示参考）

---

## 一、目标

让 GapMind 各功能**既能作为整体闭环（围绕 workspace），也能作为独立模块使用**——用户可能处于科研不同阶段，只用一个模块（如只想审稿回复，不想建 workspace 跑 Discover）。

## 二、范围界定

| 模块 | 本质依赖 | 独立化 |
|---|---|---|
| **Analyze / Publish / Respond**（W7）| 用户提供的实验 JSON / 研究内容 / 审稿意见 | ✅ 可独立（输入即材料）|
| **Discover / Plan** | 论文语料 → 证据 | ❌ 保留 workspace（本质需语料）|
| **Execute**（代码生成）| 研究计划 | ⚠️ 随 W7 解耦了 plan 可选，但代码生成强制 plan（保留）|

**原则**：独立模式下"用户输入即证据"（产物回链到用户材料），这是无 workspace 的固有取舍。

## 三、方案：系统独立空间

**选择独立空间方案**（而非 nullable workspace_id 迁移）：
- `AgentRun.workspace_id` 保持非空（数据隔离不破坏，免迁移）
- 无 workspace 时，agent 自动挂到**系统独立空间**（`__independent__`，用户无感）
- `GET /api/v1/workspaces/independent` 返回/创建独立空间（幂等）

## 四、改动点（已实施）

### 后端
| 文件 | 改动 |
|---|---|
| `workspace/service.py` | `get_or_create_independent()`：查找/创建 `__independent__` 系统空间 |
| `workspace/router.py` | `GET /workspaces/independent`（注册在 `/{workspace_id}` 前避免抢匹配）|
| `agent/service.py` | `PLAN_BOUND` → `PLAN_REQUIRED`（code_generation/deep_research 强制 plan）+ `PLAN_OPTIONAL`（analyze/write/respond 可选）|
| `agent/service.py` | `_bound_plan` → `_optional_plan`（无 plan 返回 None 不 raise）|
| `agent/service.py` | 3 个 execute（analyze/write/respond）：无 plan 跳过检索，产物标记 `independent` |
| `agent/service.py` | 3 个 prompts 独立分支（无 plan 时用用户输入构造上下文）|

### 前端
| 文件 | 改动 |
|---|---|
| `LifecycleModules.tsx` | 6 个生命周期模块卡片；W7 无 workspace → 独立模式（/chat），Discover/Plan → 选 workspace |
| `DashboardPage.tsx` | 顶部集成模块区 |
| `api/workspace.ts` | `independent()` 方法 |
| `ChatPage.tsx` | 无 workspace 时自动用独立空间启动 agent（`workspaceApi.independent()`）|
| `ChatComposer.tsx` | 禁用逻辑拆分：research_plan/code_generation 依赖 workspace；**analyze/write/respond 无 workspace 可用**（独立模式 hint）|

## 五、用户流程

**独立模式（无 workspace）**：
1. 首页点 W7 模块（Analyze/Publish/Respond）→ 直接进 /chat 独立模式
2. 选"结果分析/论文写作/审稿回复"（不再禁用）
3. 粘贴实验 JSON / 研究内容 / 审稿意见 → 启动 agent
4. 系统自动用独立空间运行，产物标记 independent

**workspace 模式**：进入 workspace 后，Discover/Plan/代码生成/计划绑定等完整功能可用。

## 六、验证

- 后端 `GET /workspaces/independent` → 200（`__independent__`）
- 独立空间 + 无 plan analyze → 202（独立模式启动）
- analyze 独立模式执行 → `independent: True`，verdict 基于用户输入
- 后端 372 + 前端 35 测试全过

## 七、边界与权衡（诚实说明）

1. **Discover/Plan 在独立空间不可用**（无语料证据）——本质依赖论文语料
2. **证据回链弱化**：独立模式产物无法回链语料证据，只能"用户材料即证据"——与 GapMind 核心原则（证据回链）有张力，产物标记 `independent` 以区分
3. **Execute（代码生成）保留强制 plan**（代码需基于可证伪计划）
4. **独立空间是系统级空间**：会出现在 workspace 列表（可用 `__independent__` 名称过滤/隐藏，若需要后续处理）

## 八、后续可选

- 独立空间在 workspace 列表/首页过滤隐藏
- 独立模式的产物落库（当前在 agent_artifacts，可审计）
- Discover/Plan 支持"临时语料"（上传几篇 PDF 作证据源，不需正式 workspace）——大改造，暂缓
