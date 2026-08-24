# GapMind Workspace ACL 路由覆盖审计

**日期**：2026-08-25
**对应任务**：T4-02 设计最低可用认证与 Workspace ACL
**结论**：认证入口、路径型 Workspace 保护和本轮发现的资源 ID/用户私有资源 owner scope 已补齐；T4-02 的代码实现已完成。仍缺 staging 双 token、真实数据库迁移和生产配置验证，因此任务仍保持进行中，不能把代码级测试当作生产隔离证明。

## 1. 已确认的保护层

| 层级 | 当前实现 | 结论 |
|---|---|---|
| API 认证 | `backend/app/main.py` 对 `/api/v1`（健康检查除外）调用 `resolve_user_id`；非 development 要求 Bearer token | 已有统一认证入口 |
| 身份来源 | `backend/app/core/deps.py` 在非 development 不接受伪造的 `X-User-ID` | 已避免最明显的身份冒用 |
| Workspace 所有者 | `Workspace.owner_id`、迁移 `0025_workspace_owner_acl`、Workspace 列表/独立空间按 owner 过滤 | 已有 owner 数据基础 |
| 路径型 Workspace 资源 | `/workspaces/{workspace_id}/...` 请求在 middleware 查询 owner；不属于当前用户时返回 404 | 覆盖 paper upload、artifact download/view、agent、discover、retrieval、gap、recommendation 等路径型资源 |
| 资源级 owner scope | Chat 对话、Reading 论文/批注、Task 资源、Knowledge 路由、Timeline 路由均按关联 Workspace owner 校验 | 已加入服务层/路由层保护，并有定向跨用户测试 |
| 用户私有搜索资源 | `PaperSearchHistory`、`PaperSearchFavorite` 增加 `owner_id`；迁移 `0028_search_acl` 改为按用户隔离，允许不同用户收藏同一外部论文 | 已完成代码和模型测试；真实数据库升级待 staging |

## 2. 仍需 staging 验证的路由类别

以下路由不能仅依靠当前 middleware 的路径解析完成授权，因为 Workspace ID 在 query、body 或关联资源中，或者 URL 只有资源 ID：

| 路由类别 | 示例 | 当前代码状态 | staging 验收要求 |
|---|---|---|---|
| Chat | `/api/v1/chat/conversations`、`/chat/conversations/{conversation_id}` | 已由 `ChatConversation.owner_id`、服务层 `actor_id` 和路由依赖保护 | 两 token 验证列表、详情、发送、重命名、删除、重试、流式接口均拒绝跨用户访问 |
| Reading | `/api/v1/reading/papers/{paper_id}`、`/reading/annotations/{annotation_id}` | 已通过 paper→workspace→owner 关联查询保护 | 两 token 验证读取、批注增改删和阅读进度接口 |
| Knowledge | 知识项/关系路径接口 | 已增加 `get_owned_workspace` 路由级防线；middleware 仍提供第一层保护 | 验证每个知识路由不泄露另一用户资源存在性 |
| Task/Timeline | `/tasks/{task_id}`、`/workspaces/{id}/timeline` | Task 资源 ID 和 Timeline 列表均已 owner 校验；无 Workspace 的系统任务对用户 API fail-closed 返回 404 | 验证任务详情/取消/恢复/重试及时间线读操作 |
| Global paper search/favorites | `/papers/search`、`/papers/favorites` | 外部搜索保持公开数据语义；历史和收藏已按 `owner_id` 隔离 | 验证用户 A 的历史/收藏不出现在 B，且同一论文可被两人独立收藏 |

## 3. 两用户验收矩阵

在 staging 使用两个不同 Bearer token，至少执行以下请求并保存状态码、响应摘要和日志脱敏检查：

| 资源 | 用户 A 自己的资源 | 用户 B 访问 A 资源 | 用户 B 修改/删除 A 资源 | 预期 |
|---|---|---|---|---|
| Workspace | 读/写 | 读 | 写/删 | A 成功；B 统一 404/403，不泄露存在性 |
| Paper/Artifact | 读/下载 | 读/下载 | 修改/删除 | B 拒绝 |
| Chat | 列表/详情/发送 | 详情 | 重命名/删除/重试 | B 拒绝 |
| Agent/Task | 列表/详情/确认/下载 | 详情 | 取消/确认 | B 拒绝 |
| Discover/Plan | 列表/详情/确认/转换 | 详情 | 确认/驳回/转换 | B 拒绝 |
| Reading/Knowledge/Timeline | 列表/详情 | 详情 | 修改/删除 | B 拒绝 |

## 4. 当前交付口径

允许写：

> 候选版本已加入最小 Bearer token、Workspace owner 基础保护，以及 Chat、Reading、Task、Knowledge、Timeline 和搜索历史/收藏的代码级 owner scope；公开或 staging 交付前仍需完成双 token、迁移和生产配置验收。

不允许写：

- “所有业务接口已经完成生产级多租户隔离”；
- “只要启用 `AUTH_REQUIRED` 就自动保护了所有资源”；
- “通过 Workspace 列表测试即可证明 Chat/论文/产物/Agent 全部安全”。
