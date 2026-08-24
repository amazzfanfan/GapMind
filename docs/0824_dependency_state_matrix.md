# GapMind 依赖状态与降级矩阵

**版本**：v0.1（2026-08-24）
**目的**：把“服务不可用时用户看到什么、能否重试、是否可以继续”固定下来，作为 Demo 话术、前端状态和 Smoke Test 的共同依据。

## 1. 基础依赖矩阵

| 依赖 | 关键用途 | 就绪检查 | 必需级别 | 失败表现 | 用户动作 |
|---|---|---|---|---|---|
| PostgreSQL | 工作区、论文、任务、证据和聊天状态 | `GET /health/ready` 的 `database` | 必需 | `not_ready`，核心 API 不应继续宣称可用 | 检查连接/迁移后重试 |
| Redis | 限流、缓存、Celery broker/backend | `redis` ping | 必需 | `not_ready` 或相关任务无法排队 | 恢复 Redis 后重试 |
| Milvus | 语义检索、Workspace RAG | `milvus` list collections | 必需 | 检索失败；不能伪装为无相关结果 | 恢复索引服务或走明确离线材料 |
| 文件存储 | PDF、切片和产物 | 目录存在且可写 | 必需 | 上传/产物写入失败 | 检查目录权限/空间 |
| LLM | Chat、Discover 和 Agent 草稿 | gateway 配置检查 | 必需 | `deepseek_unavailable` 或上游请求失败 | 重试或切换已配置备用端点 |
| Embedding | 建索引和向量检索 | gateway 配置检查 | 必需 | 新资料无法索引，语义检索不可用 | 修复 key/服务后重试 |
| Celery worker | PDF 解析、知识抽取、异步 Agent | control ping | 任务路径必需 | API 可存资料，但任务停在队列/无法完成 | 启动 worker，勿重复提交 |
| Reranker | 检索结果重排 | gateway 配置检查 | 可降级 | `reranker_degraded`，返回向量召回结果 | 可先查看结果，恢复后重试 |
| Semantic Scholar | 外部新颖性检索 | base URL 配置；网络调用时再验证 | 可降级 | `semantic_scholar_error`，外部证据缺失 | 标记外部核验未完成，不把结果当新颖性结论 |
| Gap Board Ollama | 垂类研究空白抽取 | 实际调用 | 特定功能必需 | 模型不可用/解析失败，返回未完成状态 | 检查 SSH 隧道、模型名和服务 |

## 2. `/health` 与 `/health/ready` 口径

- `/health` 是进程存活检查，只回答 API 进程是否启动，返回 200 不等于依赖全部正常。
- `/health/ready` 返回每项依赖的 `status/detail/checked`，必要依赖失败时返回 503 `not_ready`。
- Celery、Reranker、Semantic Scholar 是“功能级依赖”：基础 API 可启动，但对应功能必须在 UI 和 Demo 中显示降级状态。
- 配置存在不等于供应商健康；当前 provider 检查应在后续部署中增加带超时的真实探测或在启动 Smoke Test 中完成。

## 3. 用户可见状态

| 状态 | 含义 | 禁止的表述 |
|---|---|---|
| `queued/running` | 已接受但尚未完成 | “已经完成” |
| `succeeded` | 该步骤完成并有可查看产物 | “结论一定正确” |
| `degraded` | 完成了部分步骤，存在明确降级或缺失 | “完整核验通过” |
| `failed` | 本次步骤未产生产物 | “没有相关文献” |
| `insufficient_evidence` | 系统没有达到证据门槛 | “研究方向不存在” |
| `human_confirmed` | 人工确认过该资产 | “模型自动证明” |
| `draft/unconfirmed` | AI 草稿或候选，未进入正式事实层 | “最终方案/最终代码” |

## 4. 复现与现场处理顺序

1. 打开 `/health` 和 `/health/ready`，记录 `checked_at` 与失败项。
2. 若基础依赖失败，停止重复点击，保留原始错误码和时间。
3. 若仅可降级依赖失败，展示明确标记并切换到预先冻结的离线步骤。
4. 任何离线缓存必须在脚本中注明“冻结结果”，不得假装是实时调用。
5. 恢复后重新运行受影响步骤，并比较新旧证据/版本，而不是覆盖原始失败记录。
