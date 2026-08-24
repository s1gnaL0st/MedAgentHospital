# MedAgent 记忆与会话数据库设计

## 1. 设计目标

1. **端到端完整会话**：每个患者/医生会话由数据库管理 Agent（DB Agent）统一保存，
   形成不可分割的完整记录；
2. **Agent 记忆隔离**：每个 Agent 只保存自己可见的那层会话内容，不能越权保存
   其他 Agent 的对话记录；
3. **写入审计**：Agent 保存记忆前，DB Agent 审查数据有效性、规范性、以及是否
   混入了其他 Agent 的会话内容；
4. **支撑“存储-检索-反思”**：数据库结构直接服务于赛博小镇式的
   Memory Stream / Retrieval / Reflection 机制；
5. **向后兼容**：现有 `sessions / messages / orders / reports` 表继续保留，
   新增表作为记忆层与审计层。

## 2. 核心原则

- **单一事实来源**：完整会话只存一份，属于 DB Agent；任何 Agent 都不得把整段会话
  复制进自己的记忆；
- **最小可见性**：会话事件带 `visible_to` 字段；Agent 只能引用 `visible_to`
  包含自己的事件；
- **记忆即产物**：`agent_memories` 是 Agent 的私有记忆表，按 `agent_id` 隔离；
  案例、规则、反思都是记忆的不同类型；
- **审计即写入**：所有记忆写入必须经过 DB Agent 校验并产生审计日志；
- **可追溯**：每条记忆都保留 `source_event_id` / `source_session_id`，可以回溯
  到原始会话。

## 3. 角色与可见性模型

```text
DB Agent（全局）
  └── 完整会话 sessions / session_events（全量，属 DB Agent）

导医 Agent    → 只写 分诊相关事件 的记忆
主诊 Agent    → 只写 问诊/诊断/医嘱 的记忆
主任 Agent    → 只写 会诊/最终结论 的记忆
影像分析 Agent → 只写 影像报告 的记忆
患者 Agent    → 只写 自身症状/确认 的记忆（模拟环境）
```

会话事件示例：

```json
{
  "event_id": "EVT-0001",
  "session_id": "SES-0001",
  "seq": 1,
  "agent_id": "guide-001",
  "role": "guide",
  "event_type": "triage_suggestion",
  "payload": {
    "department": "呼吸科",
    "reason": "症状匹配 3"
  },
  "visible_to": ["guide-001", "doctor-001", "chief-001", "db-agent"],
  "created_at": 1786860000.0
}
```

## 4. 表设计

### 4.1 agents

```sql
CREATE TABLE IF NOT EXISTS agents (
  agent_id   TEXT PRIMARY KEY,
  role       TEXT NOT NULL,          -- guide / doctor / chief / imaging / patient / db_agent
  name       TEXT NOT NULL,
  department TEXT DEFAULT '',        -- doctor 按科室区分
  created_at REAL NOT NULL
);
```

### 4.2 sessions（完整端到端会话）

```sql
CREATE TABLE IF NOT EXISTS sessions (
  session_id        TEXT PRIMARY KEY,
  session_type      TEXT NOT NULL,   -- patient / assistant / training
  patient           TEXT NOT NULL,
  department        TEXT DEFAULT '',
  diagnosis_id      TEXT DEFAULT '',
  diagnosis_name    TEXT DEFAULT '',
  status            TEXT DEFAULT 'open',   -- open / closed / audited
  complete_json     TEXT DEFAULT '',        -- DB Agent 保存的完整会话快照
  created_at        REAL NOT NULL,
  completed_at      REAL
);
```

`complete_json` 由 DB Agent 在会话结束时写入，任何业务 Agent 不直接修改。

### 4.3 session_events（会话事件流）

```sql
CREATE TABLE IF NOT EXISTS session_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  agent_id    TEXT NOT NULL,
  role        TEXT NOT NULL,
  event_type  TEXT NOT NULL,       -- triage / question / answer / order / report / handoff / final
  payload     TEXT NOT NULL,       -- JSON
  visible_to  TEXT NOT NULL,       -- JSON 数组：可见的 agent_id
  created_at  REAL NOT NULL
);
CREATE INDEX idx_events_session ON session_events(session_id, seq);
```

### 4.4 agent_memories（Agent 私有记忆流）

```sql
CREATE TABLE IF NOT EXISTS agent_memories (
  memory_id         TEXT PRIMARY KEY,
  agent_id          TEXT NOT NULL,
  session_id        TEXT NOT NULL,
  source_event_id   INTEGER,
  memory_type       TEXT NOT NULL,  -- observation / case / rule / reflection / summary
  content           TEXT NOT NULL,  -- JSON：记忆主体
  importance        REAL DEFAULT 1.0,
  created_at        REAL NOT NULL,
  last_accessed_at  REAL NOT NULL,
  retrieval_count   INTEGER DEFAULT 0,
  status            TEXT DEFAULT 'active',  -- active / decayed / archived
  audit_id          INTEGER,
  UNIQUE(agent_id, session_id, memory_type, content)
);
CREATE INDEX idx_memories_agent ON agent_memories(agent_id, created_at DESC);
CREATE INDEX idx_memories_session ON agent_memories(session_id);
```

每条记忆只能由 `agent_id` 对应的 Agent 检索，查询必须带 `WHERE agent_id = ?`。

### 4.5 audit_logs（DB Agent 审计日志）

```sql
CREATE TABLE IF NOT EXISTS audit_logs (
  audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  agent_id     TEXT NOT NULL,
  memory_id    TEXT DEFAULT '',
  action       TEXT NOT NULL,       -- save / update / delete / reflect
  verdict      TEXT NOT NULL,       -- approved / rejected / needs_review
  issues       TEXT NOT NULL,       -- JSON 数组：违规与问题描述
  reviewed_by  TEXT DEFAULT 'db-agent',
  created_at   REAL NOT NULL
);
CREATE INDEX idx_audit_agent ON audit_logs(agent_id);
```

### 4.6 orders / reports（沿用现有表）

```sql
CREATE TABLE IF NOT EXISTS orders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  kind        TEXT NOT NULL,       -- exam / medication / imaging
  name        TEXT NOT NULL,
  status      TEXT DEFAULT 'ordered',
  created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  exam_name   TEXT NOT NULL,
  findings    TEXT NOT NULL,
  impression  TEXT NOT NULL,
  suggestion  TEXT NOT NULL,
  created_at  REAL NOT NULL
);
```

## 5. 数据库管理 Agent（DB Agent）

### 5.1 职责

1. 维护端到端完整会话（`sessions.complete_json`）；
2. 接收 Agent 的记忆写入请求，执行隔离审查；
3. 校验数据有效性与规范性；
4. 归一化并写入 `agent_memories`；
5. 输出审计日志；
6. 定期执行“反思”任务，把近期记忆综合成高层记忆。

### 5.2 写入审查流程

```text
Agent 提交记忆
    │
    ▼
[1] Schema 校验       字段完整、类型正确、内容非空
    │
    ▼
[2] 隔离审查          source_event_id 的 visible_to 必须包含该 agent_id；
                      content 中不得出现其他 Agent 可见层级的结论
    │
    ▼
[3] 有效性校验        disease_id 存在于知识库；symptom 已归一化；
                      时间戳合理；引用关系完整
    │
    ▼
[4] 规范性审查        统一枚举值、统一时间格式、统一 JSON 结构
    │
    ▼
[5] 写入 + 审计日志   approved / rejected / needs_review
```

审查规则示例：

- 导医记忆中的 `payload.department` 必须是科室枚举之一；
- 主诊记忆不得包含主任的最终结论（除非 `visible_to` 明确授权）；
- 影像分析记忆只能引用影像事件，不得写入诊断结论；
- 患者记忆只能引用患者可见事件，ground truth 永不可见；
- 同一 `(agent_id, session_id, memory_type, content)` 自动去重。

## 6. 与“存储-检索-反思”机制的对应

### 存储（Store）

`agent_memories` 即记忆流：

- `importance` 由记忆创建时计算；
- `created_at` / `last_accessed_at` 用于时近性；
- `retrieval_count` 用于检索强化。

### 检索（Retrieve）

```text
score = relevance × exp(-decay_rate × age) × importance × (1 + 0.1 × retrieval_count)
```

检索必须限定 `agent_id`，保证 Agent 只能检索自己的记忆。

### 反思（Reflect）

DB Agent 定期执行：

```sql
SELECT agent_id, memory_type, content, importance
FROM agent_memories
WHERE agent_id = ? AND created_at >= ?
ORDER BY importance DESC, created_at DESC;
```

把近期记忆归纳为 `memory_type = 'reflection'` 的高层记忆写回，
继续参与后续检索。

## 7. 迁移路径

1. 保留现有 `sessions / messages / orders / reports`；
2. 新增 `agents / session_events / agent_memories / audit_logs`；
3. `messages` 迁移为 `session_events` 的扁平视图；
4. `MedicalCaseBase` 与 `ExperienceBase` 改为读写 `agent_memories`；
5. 服务启动时由 DB Agent 加载各 Agent 记忆，重启不丢失；
6. 仿真训练按“训练变体 + 科室”注册独立医生 Agent，成功病例和验证通过的
   反思规则均通过 DB Agent 审计后持久化，下一次训练会先恢复这些记忆。

## 8. 安全与边界

- 记忆写入必须经过 DB Agent，业务代码不直接写 `agent_memories`；
- 完整会话只存在 DB Agent 手里，Agent 拿到的永远是“视图”；
- 所有内容仅用于算法演示与研究，不构成临床建议；
- 后续若接入真实医院系统，需在 DB Agent 层增加权限、脱敏与合规检查。
