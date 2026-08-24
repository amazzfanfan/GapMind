# GapMind 安全检查清单

**状态**：代码和材料初稿；最终生产配置与跨用户验证待执行。
**对应任务**：T4-02、T4-03、T4-06、T4-07。

## 访问控制

- [x] staging/production 默认要求 Bearer token。
- [x] `X-User-ID` 在非 development 环境不能作为身份真实性来源。
- [~] Workspace 记录 `owner_id`；路径型资源由 middleware 保护，Chat、Reading、Task、Knowledge、Timeline 及搜索历史/收藏已增加资源级 owner scope。代码级定向测试通过，双 token staging 验收仍待完成。
- [ ] 使用两个真实 token 完成跨 Workspace 读/写/下载/任务/Agent/Chat 越权测试。
- [x] 完成 Chat、Reading、Knowledge、Task、Timeline 及全局搜索私有资源的 owner scope 代码审查和定向测试。
- [ ] 确认最终 token 不写入前端 bundle、截图、日志和提交包。

## 配置与网络

- [x] CORS 不再允许任意 methods/headers，credentials 关闭。
- [ ] 生产 `CORS_ORIGINS` 只保留正式前端来源，并做预检验证。
- [ ] 生产 `APP_ENV`、数据库、Redis、Milvus 和远程模型配置由受控 secret 注入。
- [ ] `/docs`、`/openapi.json` 是否公开由比赛部署策略确认。

## 上传与存储

- [x] 上传按分块读取，单文件上限 50 MB。
- [x] 校验 `.pdf` 扩展名和 `%PDF-` magic；不信任客户端 MIME。
- [x] 保存为 `application/pdf`，不让客户端 MIME 决定响应类型。
- [x] Workspace 默认 500 MB 配额，超限返回 `workspace_storage_quota_exceeded`。
- [ ] 反病毒/恶意 PDF 扫描由生产网关或部署平台补充。
- [ ] 完成磁盘权限、剩余空间和备份恢复演练。

## 数据与日志

- [x] 数据等级、远程调用、留存和删除规则已形成文档。
- [ ] 检查日志中不出现 token、API key、完整 PDF、完整 prompt 或个人信息。
- [ ] 用户测试记录脱敏并留存授权证明。
- [ ] 关闭开发默认密码和示例 key。

## 故障与降级

- [x] `/health` 与 `/health/ready` 分离。
- [x] required 依赖失败返回 503；可选依赖显示 degraded。
- [x] 上传/解析失败原因可见，不能显示为已索引。
- [ ] 现场分别演练 DB/Redis/Milvus/LLM/worker/S2 不可用和恢复路径。

## 路由覆盖证据

详细审计见 `docs/0825_acl_route_audit.md`。代码级覆盖已完成；在两 token 矩阵、真实数据库迁移和生产配置复核完成前，T4-02 保持进行中，不开放真实敏感资料或公开多用户访问。
