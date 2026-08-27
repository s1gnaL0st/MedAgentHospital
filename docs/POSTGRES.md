# PostgreSQL 后端

项目默认使用 SQLite，便于离线开发和测试。设置 `DATABASE_URL` 后，医院记录、
Agent 记忆、事件审计和 LangGraph checkpoint 会切换到 PostgreSQL。

## 启动

需要 Docker 时：

```bash
docker compose -f docker-compose.postgres.yml up -d
```

PowerShell：

```powershell
$env:DATABASE_URL = "postgresql://medagent:medagent@127.0.0.1:5432/medagent"
D:\python\python.exe -m medagent_hospital.web.server
```

也可以把同名配置写入 `.env`。首次启动会自动创建业务表和 LangGraph
checkpoint 表，不会自动删除或覆盖现有数据。

## 数据边界

`PostgresRecordStore` 与 SQLite 的 `HospitalRecordStore` 提供相同的业务方法，
DB Agent 不直接依赖 SQL 方言。PostgreSQL 使用 `JSONB` 保存患者、事件、记忆和
审计 payload，并为会话、事件、Agent 记忆建立索引。

LangGraph 使用 `langgraph-checkpoint-postgres` 的 `PostgresSaver`，患者的
`session_id` 仍然作为 `thread_id`。没有 `DATABASE_URL` 时，保持使用
`SqliteSaver`。

## 迁移说明

当前版本提供新库自动建表，但不执行 SQLite 数据搬迁。生产迁移应先导出 SQLite
中的 `sessions / messages / orders / reports / agents / session_events /
agent_memories / audit_logs`，再导入 PostgreSQL；导入后用审计日志数量、会话数量
和记忆数量进行校验。

Redis 暂未作为事实存储接入。它适合后续承载 A2A 长任务队列、SSE 广播、缓存和
分布式锁，PostgreSQL 仍是患者记录和 Agent 长期记忆的唯一事实来源。
