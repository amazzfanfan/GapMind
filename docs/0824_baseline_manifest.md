# GapMind 当前基线清单

**记录日期**：2026-08-24
**记录任务**：T0-02 记录当前基线版本
**分支**：`yx_dev`
**基线 commit**：`465b9d638b5c6c7b034be469a033e8fba7f5f95c`
**提交信息**：`docs: 增加比赛审查与交付文档`
**记录性质**：只读基线记录；本文件由 T0-02 新增，尚未提交。

## 一、Git 基线

### 1. 分支关系

```text
## yx_dev...origin/yx_dev [ahead 1]
```

本地分支相对 `origin/yx_dev` 多 1 个本地 commit，即本次用户授权创建的文档提交 `465b9d6`。本轮没有 push。

### 2. 基线记录前的工作区状态

在生成本基线文件之前，工作区状态为：

```text
## yx_dev...origin/yx_dev [ahead 1]
?? deploy/
?? docs/XH-202620_面向一流学科建设的学科垂类大模型与创新应用开发.pdf
?? index.html
```

上述三个路径及其内容属于已有工作区材料，未纳入本次文档 commit，也没有在 T0-02 中修改、删除或暂存：

- `deploy/`：本地部署物料；
- `docs/XH-202620_面向一流学科建设的学科垂类大模型与创新应用开发.pdf`：比赛要求原文件；
- `index.html`：已有根目录入口/原型文件，尚未作入口决策。

生成本文件及后续看板状态更新后，工作区会额外出现：

```text
?? docs/0824_baseline_manifest.md
```

该文件及看板/Todo 的 T0-02 状态更新不属于已完成的 `465b9d6`，等待用户后续审查和授权处理。

## 二、迁移基线

使用后端虚拟环境中的 Alembic 可执行文件查询：

```text
0024_chat_generation_observability (head)
```

查询命令：

```powershell
cd backend
.venv\Scripts\alembic.exe heads
```

曾尝试使用 `.venv\Scripts\python.exe -m alembic heads`，该环境中的 Alembic 包没有 `__main__` 入口，命令返回 `No module named alembic.__main__`。这属于命令调用方式不适配，不是迁移或项目功能故障；已改用可执行文件并成功确认 head。

## 三、自动化验证结果

以下结果均在 commit `465b9d6` 工作区上执行；本次没有业务代码变更。

| 检查项 | 命令 | 结果 | 说明 |
|---|---|---|---|
| 后端测试 | `backend\.venv\Scripts\python.exe -m pytest tests -q` | **469 passed, 2 warnings** | 约 20.22 秒；警告来自 pytest-asyncio 配置和第三方依赖弃用提示 |
| 前端测试 | `npm run test -- --run` | **17 files / 56 tests passed** | Vitest 通过 |
| TypeScript | `npm run typecheck` | **通过** | `tsc --noEmit` 通过 |
| 前端构建 | `npm run build` | **通过** | 3422 modules transformed；存在大包提示 |
| ESLint | `npm run lint` | **0 errors / 14 warnings** | 主要是 Fast Refresh、Hook 依赖和无效 disable 警告 |
| 缓存区格式检查 | `git diff --cached --check` | **通过** | 已提交文档在提交前完成检查 |

### 构建警告明细

- 主构建包约 `1,830.84 kB`，超过 500KB 警戒线；当前只是性能/分包提醒，不是构建失败。
- `KnowledgeGraph` chunk 约 `493.99 kB`，接近警戒线。
- 该问题进入 P1-11，不作为 T0-02 的阻塞项，但最终候选版本需要有处理结论。

### Lint 警告明细

- `ErrorBoundary.tsx`：无效 `eslint-disable`；
- Chat/Status/Layout/ResearchPlans/Theme 等组件：Fast Refresh 导出警告；
- Dashboard/Discover/GapBoard/Workspaces 等页面：Hook 依赖警告。

这些问题目前没有 lint error；进入 P1-11 处理，不能在最终材料中写成“lint 完全无警告”。

## 四、运行环境和服务清单

### 1. Compose 服务

从 `infra/docker-compose.yml` 读取到的基础设施服务：

- `postgres`
- `redis`
- `milvus-etcd`
- `milvus-minio`
- `milvus`

数据卷包括 Postgres、Redis、Milvus etcd、Milvus MinIO 和 Milvus 数据卷。

### 2. 配置项类别

本次只记录 `.env.example` 中的变量名，不读取和写入真实值。配置类别包括：

- 应用：`APP_ENV`、`APP_HOST`、`APP_PORT`、`APP_LOG_LEVEL`、`APP_STORAGE_DIR`；
- PostgreSQL：用户、密码、数据库、地址、端口、`DATABASE_URL`；
- Redis/Celery：Redis 地址、端口、URL、Broker、Result Backend；
- Milvus：地址、端口、Collection 前缀；
- 主/备用 LLM：Deepseek API、Base URL、Model；
- Gap Board：本地/远程模型地址、模型、digest、超时、repair、采样和 fallback 参数；
- Chat/Agent：历史消息、字符限制、RAG top-k、上下文预算、代码文件/字符上限；
- Embedding/Reranker 相关：SiliconFlow、模型、维度；
- Semantic Scholar：API Key、Base URL；
- 前端和跨域：`CORS_ORIGINS`、`VITE_API_BASE_URL`。

### 3. 本次未验证的服务状态

本次 T0-02 没有启动或依赖以下真实外部服务，因此不能把它们记为“已可用”：

- PostgreSQL、Redis、Milvus、MinIO、Celery worker 的真实运行状态；
- Deepseek 主/备用服务；
- SiliconFlow Embedding/Reranker；
- Semantic Scholar API；
- 本地或远程 Ollama Gap extractor；
- 任何公开访问、登录、反向代理和公网 HTTPS 状态。

这些状态将在 T0-04、T3-05、T4-05、T4-07 和 T5-03/T5-04 中按需要验证。

## 五、当前项目状态判断

### 已确认

- 三份审查/交付文档已在 `465b9d6` 中提交。
- 当前分支仍为 `yx_dev`，本地领先远程 1 个 commit，未 push。
- 后端、前端、TypeScript 和构建验证通过。
- 当前迁移 head 为 `0024_chat_generation_observability`。
- 原有部署物料、比赛 PDF 和根目录入口没有被提交或修改。

### 未确认或仍需处理

- 真实外部服务是否当天可用；
- 完整真实数据十步 Demo；
- 两名真实目标用户效果；
- 公开访问和资源级权限；
- 构建大包和 14 个 lint 警告；
- 文档入口和失效引用检查；
- 干净环境恢复和最小 Smoke Test。

## 六、T0-02 验收结论

**状态：完成。**

T0-02 的验收证据已经覆盖：

- 分支、commit 和远程关系；
- 基线前工作区状态和受保护路径；
- Alembic head；
- 后端/前端测试、TypeScript、构建和 lint；
- 构建和 lint 警告；
- 配置变量类别和基础设施服务清单；
- 未验证外部服务边界；
- 下一步任务范围。

## 七、下一步

下一项为 **T0-03：冻结本轮“不做事项”**。建议只处理以下内容：

1. 明确本轮不做或不承诺 GraphRAG、复杂多模态、代码执行、多租户和大规模并发；
2. 将“已完成、实验中、未验证、后续规划”分成四类；
3. 形成 README/PPT/Demo/现场话术都能遵守的禁止宣称清单；
4. 不修改业务代码，不启动 P1/P2，先把范围冻结。
