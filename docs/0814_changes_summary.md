# 0814 P1.5 模块独立化改动总结

> 日期：2026-08-14
> 作者：yx
> 范围：P1.5 模块独立化（前端模块化首页 + W7 独立化 + 系统独立空间 + ChatComposer 独立模式）
> 配套：`0814_independent_modules_plan.md`（详细计划）

---

## 一、改动总览

| # | 改动 | 文件 | 验证 |
|---|---|---|---|
| 1 | **模块化首页**：Dashboard 顶部 6 个研究生命周期模块卡片 | `LifecycleModules.tsx`（新）+ `DashboardPage.tsx` + `index.css` | tsc |
| 2 | **W7 独立化**：analyze/write/respond 无需研究计划 | `agent/service.py`（PLAN_REQUIRED/OPTIONAL、_optional_plan、3 execute、3 prompts）+ `ChatComposer.tsx` + `ChatPage.tsx` | 372 后端测试 |
| 3 | **系统独立空间**：无 workspace 也能用 W7 | `workspace/service.py`（get_or_create_independent）+ `workspace/router.py`（GET /independent）+ `api/workspace.ts`（independent）+ `ChatPage.tsx` | 真实 202 |
| 4 | **ChatComposer 独立模式**：无 workspace 时 W7 三模式可选 | `ChatComposer.tsx`（disabled 拆分 + 独立 hint + plan Select 条件）| tsc + 35 前端测试 |

## 二、每项细节

### 1. 模块化首页（P1.5 第一步）
- `LifecycleModules.tsx`：6 卡片（Discover/Plan/Execute/Analyze/Publish/Respond），镜像根目录 index.html
- `DashboardPage.tsx`：PageHeader 后集成
- 导航：Discover/Plan → workspace 功能页；W7 → Chat

### 2. W7 独立化（P1.5 第二步）
- 后端 `PLAN_REQUIRED = {code_generation, deep_research}`（强制 plan）/ `PLAN_OPTIONAL = {analyze, write, respond}`
- `_optional_plan`：无 plan 返回 None（不 raise）
- 3 个 execute：无 plan 跳过 workspace 检索，产物标记 `independent: True`
- 3 个 prompts：独立分支（无 plan 用用户输入构造上下文）
- 前端：ChatComposer plan 可选、ChatPage 无 plan 启动

### 3. 系统独立空间
- `get_or_create_independent()`：查找/创建 `__independent__` workspace（幂等）
- `GET /workspaces/independent`（注册在 `/{workspace_id}` 前）
- 前端无 workspace 自动用独立空间（ChatPage `workspaceApi.independent()`）

### 4. ChatComposer 独立模式（本轮）
- disabled 拆分：research_plan/code_generation `!workspaceEnabled`；analyze/write/respond 始终可用
- 无 workspace 时：W7 三模式可选 + hint 显示"独立模式"说明；plan Select 隐藏
- 移除误导的外层 Tooltip

## 三、测试基线

- 后端 **372**（原 371 + analyze 独立模式测试更新）
- 前端 **35** vitest + tsc 全过
- 真实验证：独立空间 + 无 plan analyze → 202，`independent: True`

## 四、Git

`yx_dev` 分支，P1.5 相关 commit：
- `dce6fdd` 模块化首页
- `7b596d0` W7 独立化
- `97f6f2c` 系统独立空间
- （本轮 ChatComposer 独立模式待 commit）

## 五、边界（不假装完整）

- Discover/Plan 在独立空间不可用（需论文语料）
- 独立模式产物无法回链语料证据（用户材料即证据，标记 independent）
- Execute（代码生成）仍强制 plan
- 独立空间是系统级空间（列表可见，可后续过滤）
