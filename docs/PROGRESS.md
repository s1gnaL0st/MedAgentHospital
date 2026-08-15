# MedAgent-Hospital 项目进度

## D1-D2：工程骨架 + 医学知识库

### 目标

1. 搭建可运行的项目骨架（依赖清单、环境变量模板、包结构、测试框架）；
2. 产出 6 个科室、40-50 种疾病的结构化医学知识库。

### 实现

#### 工程骨架

- `requirements.txt` / `requirements-dev.txt`：fastapi、uvicorn、openai、python-dotenv、pytest、matplotlib 等；
- `.env.example`：DeepSeek API、HuatuoGPT（vLLM）、规则模式三种 LLM 后端配置模板；
- `.gitignore`：排除 `.env` 与运行时生成数据；
- 包结构 `medagent_hospital/`：`config`、`llm`、`agents`、`memory`、`knowledge`、`simulacrum`、`web`；
- 冒烟测试覆盖配置默认值、案例库检索、经验规则存活率。

#### 知识库构建方法

论文附录 A.1/A.2 说明其知识库来自百度健康百科、丁香园常见病列表和 GPT-4 补充，
但**未公开结构化数据**，也没有找到官方代码仓库。因此本项目知识库全部自建，
参考公开医学资料整理，仅用于算法演示与研究，非临床建议。

构建步骤：

1. 确定 6 个科室：心内科、呼吸科、消化科、神经内科、内分泌科、皮肤科；
2. 每个科室选取 8 种常见病，共 48 种；
3. 按统一 schema 结构化每条疾病知识；
4. 为每种疾病配置 `patient_profile` 概率模板，供病人 Agent 生成器采样；
5. 编写 loader、查询接口和数据校验逻辑；
6. 用测试固定数据规模、字段完整性和别名查询。

#### 数据结构

每种疾病包含：

- `id` / `name` / `aliases` / `department`；
- `symptoms`：症状列表（可控词表）；
- `risk_factors`：危险因素；
- `examinations`：检查项及典型结果；
- `treatments`：治疗方案；
- `distinguishing_features`：鉴别要点；
- `patient_profile`：年龄范围、性别倾向、症状权重、病史倾向、检查命中率。

#### 产出文件

- `data/knowledge_base.json`：48 种疾病结构化数据；
- `medagent_hospital/knowledge/diseases.py`：loader、`KnowledgeBase`、校验；
- `tests/test_knowledge_base.py`：知识库测试；
- `data/README.md`：数据目录说明。

### 验证结果

- `python -m compileall`：全部通过；
- 知识库校验：`validation errors: 0`；
- 疾病数量：48，处于 40-50 目标区间；
- 科室数量：6，每个科室 8 种疾病；
- 别名查询正常：如“感冒”“慢阻肺”“牛皮癣”可命中主疾病；
- 冒烟测试与知识库测试全部通过。

### 决策记录

- 论文未公开训练数据/知识库，本项目自建精简版；
- 知识库使用 JSON 数据驱动，便于审计、替换和扩展；
- 文档语言为中文，`.env` 不入库，后续发布 GitHub。

## D3-D4：自定义 Agent 框架 + 规则模式医生

### 目标

1. 实现自研的 hospital runtime（LangGraph 风格状态机），合理规范；
2. 实现病人 Agent 生成器、护士分诊 Agent、医生 Agent（规则模式）；
3. 完成小型诊断测试。

### 实现

#### 自定义运行时（LangGraph 的 hospital edition）

- `HospitalState`：发病、分诊、挂号、问诊、检查、诊断、开药、随访、结束；
- `HospitalRuntime`：事件循环 + 显式状态转移表，驱动每个病人完整就诊闭环；
- `ConsultationContext`：类型化的就诊上下文，包含病人信息、分诊结果、检查结果、
  诊断、治疗方案、评分和完整 transcript（供回放）；
- `Action`：Agent 统一返回“动作”，runtime 根据动作和状态决定下一步。

#### 三个 Agent

- `PatientAgent`：报告症状、挂号、随访反馈；ground truth 通过 `doctor_view()`
  对医生隐藏；
- `NurseAgent`：按症状与知识库科室匹配度分诊，执行检查；
- `DoctorAgent`：规则模式完成选检查、诊断、开药；LLM 推理接口预留（D8-D9）。

#### 病人生成器

- 按疾病的 `patient_profile` 采样年龄、性别、症状（带权重）、病史、危险因素和
  检查结果；
- 支持 25% 概率加入同科室干扰症状，让病例更真实；
- 生成数据与医生视角严格隔离。

#### 产出文件

- `medagent_hospital/simulacrum/models.py`：状态、上下文、Action 等数据模型；
- `medagent_hospital/simulacrum/patient_generator.py`：病人 Agent 生成器；
- `medagent_hospital/agents/patient.py` / `nurse.py` / `doctor.py`：三个 Agent；
- `medagent_hospital/simulacrum/runtime.py`：hospital runtime 状态机；
- `medagent_hospital/simulacrum/demo.py`：小型诊断测试入口；
- `tests/test_hospital_flow.py`：D3-D4 验收测试。

### 验证结果

- 小型诊断测试：60 例（每科室 10 例），诊断准确率 100%；
- 完整流程测试：单病例可走完 发病->分诊->挂号->问诊->检查->诊断->开药->随访，
  `HospitalState.END` 正常到达；
- 分诊测试：典型肺炎病例正确分诊到呼吸科；
- 全部 10 个测试用例通过（冒烟、知识库、医院流程）。

### 说明

- D3-D4 全程使用**规则模式**，未调用任何 LLM API，完全离线可跑；
- 100% 准确率是“同一份知识库生成病人、同一份知识库规则诊断”的闭环结果，
  不代表真实临床能力；
- `LLMBackend` 接口和 `.env` 配置已预留，DeepSeek / HuatuoGPT 推理将在
  D8-D9 接入（需要用户提供 `DEEPSEEK_API_KEY`）。

### 下一步

- D7：进化训练循环 + 虚拟测试集 + 学习曲线。

## D5-D6：诊断 RAG（案例库 + 经验库）

### 目标

1. 案例库 / 经验库写入机制；
2. Jaccard 检索 + 检索结果注入医生规则打分；
3. 模板式经验规则生成与验证（失败反思）。

### 实现

#### 记忆库结构

- `MedicalCaseBase`：存成功病例（症状 + 异常检查名 + 诊断 + 治疗），
  按 Jaccard 相似度检索，返回 `CaseHit(case, score)`；
- `ExperienceBase`：存结构化规则
  （`trigger` 触发词、`favor` 优先疾病、`against` 降低疾病、`strength` 强度），
  按触发词命中比例检索，返回 `RuleHit(rule, score)`；
- `ConsultationContext` 新增 `retrieved_cases` / `retrieved_rules`，
  供解释和回放。

#### 医生 Agent 注入

- 诊断时先算知识库规则分，再叠加记忆贡献：
  - 案例命中：`相似度 * case_weight` 投给对应诊断；
  - 规则命中：`strength * 命中比例` 加成 / 减分；
- `top_k_cases=3`、`top_k_rules=4`（对齐论文最优超参）；
- 记忆只参与诊断任务（按讨论确定范围）。

#### MemoryManager

- 诊断正确：病例写入案例库；
- 诊断错误：对比真病与误诊病，取真病独有症状生成模板规则；
- 规则在验证队列上对比“加规则前 / 加规则后”准确率，不降点才入库；
- 统计 `validations / successes`，为 D7 的规则存活率可视化做准备。

#### 工程修复

- 修复 agents 与 simulacrum 的循环导入：`simulacrum/__init__.py` 改为
  只保留包说明、子模块按需导入（懒加载），避免 `agents -> simulacrum -> agents`
  依赖环。

#### 产出文件

- `medagent_hospital/memory/case_base.py`：案例库 + Jaccard 检索；
- `medagent_hospital/memory/experience_base.py`：经验规则库 + 检索；
- `medagent_hospital/agents/doctor.py`：记忆注入打分（修改）；
- `medagent_hospital/simulacrum/memory_manager.py`：记忆写入 / 反思 / 验证；
- `medagent_hospital/simulacrum/models.py`：新增 `retrieved_cases` / `retrieved_rules`（修改）；
- `tests/test_memory_rag.py`：RAG 诊断测试。

### 验证结果

- 案例库 Jaccard 检索：正确返回最相似病例；
- 经验规则检索：按触发词命中返回规则；
- RAG 注入：易混淆硬病例（慢阻肺 vs 哮喘）在案例库 / 经验库增强下
  从误诊翻转为正确；
- 反思：误诊 `单纯疱疹` vs `带状疱疹` 能生成 favor/against 规则；
- 验证：有效规则保留、有害规则丢弃；
- 全部 18 个测试用例通过，`compileall` 通过。

### 说明

- 记忆增强目前作用于诊断任务，选检查/治疗暂不接入；
- 检索先用 Jaccard（离线、稳定），embedding 检索留作后续可选升级；
- 规则生成先为模板式（可控），LLM 生成自然语言规则作为 D8 对比实验；
- 进化训练循环和学习曲线属于 D7，不在 D5-D6。

### 下一步

- D8：LLM 模式接入（DeepSeek / HuatuoGPT），复用同一套进化训练器。

## D7：进化训练循环 + 学习曲线

### 目标

1. 科室独立医生的进化训练器（每科室独立案例库/经验库）；
2. 推理器无关的训练循环，训练 / 验证 / 测试集隔离；
3. A/B/C/D 四组消融学习曲线 + 规则存活率；
4. 改进机制：案例去重、规则生命周期、失败回放、课程学习。

### 实现

- `DoctorRegistry`：按科室创建独立 DoctorAgent，runtime 按分诊结果路由；
- `EvolutionConfig` + `EvolutionTrainer`：批量治疗 -> 记忆更新 -> 周期评估；
- 课程学习：训练难度从易到难逐步提高
  （易混淆占比、症状缺漏、检查命中率均随轮次斜坡）；
- 易混淆疾病组 + 症状混合：真病症状占 50%，让基线下到 ~86-88%；
- 记忆质量：
  - 只有带异常检查的成功病例才入库；
  - 反思规则的触发词包含异常检查名；
  - 案例检索中检查证据权重是症状的 2 倍；
- 规则生命周期：低存活率规则淘汰，高存活率规则自动增强 strength；
- 失败回放：周期性重跑误诊病例；
- `run_evolution_experiment`：输出 `evolution_metrics.json` 和学习曲线图。

### 产出文件

- `medagent_hospital/agents/registry.py`：科室医生注册表；
- `medagent_hospital/simulacrum/evolution.py`：训练器、消融配置、绘图；
- `medagent_hospital/memory/case_base.py`：案例去重 + 检查加权检索（修改）；
- `medagent_hospital/memory/experience_base.py`：规则生命周期（修改）；
- `medagent_hospital/simulacrum/memory_manager.py`：记忆质量与反思（修改）；
- `tests/test_evolution.py`：注册表、去重、生命周期、训练器、四组消融、绘图测试；
- `data/experiments/evolution_comparison.png`：学习曲线图；
- `data/experiments/evolution_metrics.json`：实验指标。

### 验证结果

- 全部测试通过（共 24 个用例，含训练器、四组消融和绘图测试）；
- 小型训练器冒烟、四变体曲线、绘图产物均验证通过；
- 正式实验（seed=42，每科室训练 300 / 测试 100）：

| 变体 | 初始准确率 | 最终准确率 |
| --- | --- | --- |
| A（原版 SEAL） | 87.7% | 85.0% |
| B（+案例去重） | 87.7% | 85.0% |
| C（+规则生命周期） | 87.7% | 85.3% |
| D（+失败回放+课程学习） | 87.7% | 87.0% |

D 最终准确率高于 A 2.0pp，且曲线更稳定。

### 说明

- 规则模式下知识库本身很强，记忆增益有限且带噪声，本结果定位为**机制验证**；
- 主实验放到 D8：同一套训练器切换 `reasoner="llm"`，规则模式保留为离线基线和兜底；
- 学习曲线为规则模式初步结果，不代表临床效果。

### 下一步

- D8：DeepSeek 接入 + LLM 医生 + RAG 记忆，跑同一套进化实验；
- D9-D11：Web 仪表盘（训练控制、交互诊断回放、记忆库浏览）。

## D8：DeepSeek 接入（已完成）

### 目标

1. LLM 后端工厂：按 `.env` 配置创建 DeepSeek（OpenAI 兼容）后端；
2. `DoctorAgent(reasoner="llm")`：LLM 诊断 + RAG 记忆注入 + JSON 解析 + 规则回退；
3. Web 仪表盘支持推理模式切换（规则模式 / DeepSeek）。

### 已实现

- `medagent_hospital/llm/base.py`：新增 `build_llm_backend()`；
- `medagent_hospital/agents/doctor.py`：LLM 诊断路径
  （系统提示 + 病人/检查/候选疾病/相似案例/经验规则入 prompt，输出结构化 JSON）；
  - JSON 解析失败或 API 异常时自动回退规则打分；
  - 检查选择与治疗方案仍由知识库保障（LLM 专注核心诊断）；
- `medagent_hospital/web/server.py`：`/api/episode/run` 支持 `reasoner` 参数；
- 前端工具栏新增“推理模式”下拉框（规则模式 / DeepSeek）；
- `tests/test_llm_doctor.py`：有效 JSON、乱码回退、API 异常回退、后端工厂测试。
- `scripts/smoke_deepseek.py`：一键 DeepSeek 冒烟脚本（无 key 时提示配置）。
- `medagent_hospital/config.py`：增加标准库 `.env` 解析兜底，不依赖 python-dotenv；
- 密钥处理：`DEEPSEEK_API_KEY` 从 `.env.example` 移入 `.env`，
  `.env.example` 已恢复为占位符，避免提交 GitHub 时泄露。

### 验证结果

- 全部 30 个测试通过；
- `node --check` JS 语法通过；
- LLM 医生单元测试（fake backend）通过。
- 真实 DeepSeek 冒烟通过（需沙箱外网络）：带状疱疹病例诊断正确，
  LLM 返回完整中文医学推理；
- `.env` 读取验证通过：`LLM_BACKEND=deepseek`、key 可加载。

### 待办

- D9（可选）：DeepSeek 进化实验复用同一训练器；
- 3090 + vLLM 部署 HuatuoGPT-II-7B，做通用 vs 垂类底座对比；
- README、架构图、实验报告、面试讲稿与 GitHub 发布。

## 前端仪表盘（初步实现）

### 目标

1. 像素小人风格的医院就诊模拟（类 Smallville / Agent Hospital 演示）；
2. 就诊回放：病人从入口到分诊、挂号、问诊、检查、诊断、开药、随访；
3. 进化训练、记忆库、知识库三个数据视图。

### 实现

- `medagent_hospital/web/server.py`：stdlib 本地服务器，提供
  `/api/health`、`/api/kb/overview`、`/api/episode/run`、
  `/api/evolution/run`、`/api/evolution/latest`；
- `medagent_hospital/web/static/`：原生 HTML/CSS/JS 单页仪表盘；
- 像素医院场景：Canvas 绘制医院地图（入口、分诊台、挂号处、候诊区、诊室、
  检查室、药房、出口），病人/护士/医生小人按就诊状态移动并显示气泡文案；
- 就诊记录侧栏实时追加事件，结束后显示诊断结果（预测 vs 真实）与记忆检索；
- 进化训练视图：A/B/C/D 四组学习曲线 Canvas 图表 + 结果表；
- 记忆库视图：每科室案例数、规则数、规则存活率；
- 知识库视图：6 科室 48 疾病卡片。

### 验证结果

- `node --check app.js`：JS 语法通过；
- 后端接口本地验证通过：health、KB overview、就诊模拟、小规模进化实验、latest；
- Chrome 无头截图验证页面有实际内容渲染（1280x900，1516 种颜色，非空白）；
- 新增 `tests/test_web.py`：知识库概览与就诊模拟接口测试。

### 说明

- 服务器已在本机运行：`http://127.0.0.1:8000`；
- “使用进化记忆”在运行进化训练后可用，否则走规则模式基线；
- 前端为初步版本，后续可继续打磨动画节奏、移动端布局和 LLM 模式接入；
- 规则模式进化实验已从 Web 移除，进化训练界面暂未启用；
  DeepSeek 进化实验保留 CLI：`python scripts/run_deepseek_evolution.py`。

## 真多 Agent 协作：医生会诊 + 护士追问

### 目标

1. 护士 Agent 主动追问缺失症状，病人 Agent 按隐藏 ground truth 回答；
2. 医生低置信时发起会诊，多位医生独立给意见并加权汇总；
3. 前端把追问和会诊过程可视化。

### 实现

- `HospitalState` 新增 `SYMPTOM_QUESTION` / `SYMPTOM_ANSWER` / `CONSULTATION_ROUND`；
- 新增 `GuideAgent`（导医）：掌握全院科室知识，病人不知道挂什么科时引导挂号，
  自带案例库/经验库，分诊正确入案例、错误反思生成规则（修改）；
- `NurseAgent._ask_symptom`：从科室疾病症状池选择“未观察到且权重最高”的症状提问；
- `PatientAgent`：根据真实疾病回答“有 / 没有”，有的症状补进病人可见症状；
- `DoctorRegistry`：支持每科室多位医生（演示 3 位：1 主诊 + 2 会诊），
  主诊和会诊医生各自独立实例，且会诊医生带不同专业视角：
  会诊医生 1 为“检查导向”（检查证据权重 1.8），会诊医生 2 为“病史导向”
  （病史/危险因素权重 2.0），LLM 模式下系统提示词也携带各自角色描述；
- `HospitalRuntime`：
  - 追问两态循环，默认 2 轮；
  - 诊断低置信（规则分差小于阈值，或 LLM 无分数）触发会诊；
  - 收集主诊 + 会诊意见后进入 `CONSULTATION_SUMMARY`，由主任医生仲裁：
    LLM 模式让主任综合意见做最终裁定，规则模式按权重加权、平局偏向主诊；
- Web：默认 2 次追问 + 低置信会诊（阈值 0.6），支持“强制会诊”开关；
- 前端：新增追问 / 回答 / 会诊事件文案，会诊时诊室显示两位医生，
  结果卡展示会诊意见列表与来源。

### 产出文件

- `medagent_hospital/simulacrum/models.py`：新状态与会诊上下文（修改）；
- `medagent_hospital/simulacrum/runtime.py`：追问两态 + 会诊轮次 + 加权汇总（修改）；
- `medagent_hospital/agents/nurse.py` / `patient.py` / `doctor.py`（修改）；
- `medagent_hospital/agents/registry.py`：每科室多医生（修改）；
- `medagent_hospital/web/server.py` + `static/app.js`（修改）；
- `tests/test_multiagent.py`：注册表、追问、会诊测试（新增）。

### 验证结果

- 39 个测试全部通过；
- HTTP 验证（强制会诊）：2 次护士追问、3 位医生意见、主任仲裁后诊断正确；
- HTTP 验证（导医）：分诊由 `导医` Agent 完成，正确分诊后案例库 +1；
- 视角分化测试：同一病例中，检查导向医生诊断肺炎、病史导向医生诊断肺结核，
  证明会诊医生不是复制体；
- 仲裁测试：三份冲突意见下，主任按权重裁定正确诊断；LLM 仲裁走模型输出；
- 前端 JS 语法检查通过。

### 说明

- 会诊目前为“同科室独立医生 + 意见加权”，后续可扩展跨科室会诊或 LLM 仲裁；
- 默认仍按低置信触发；勾选“强制会诊”可固定演示会诊流程。
- 分诊由导医 Agent 完成（带独立记忆），追问改为主诊医生在诊室完成；
- 前端动画支持重新开始：连点“开始就诊”会作废旧动画并播放新流程。

## D9：DeepSeek 进化实验（小规模）

### 目标

用同一套进化训练器切换 `reasoner="llm"`，跑一次真实的 DeepSeek 进化实验。

### 实现

- `EvolutionConfig` 新增 `reasoner` 字段，`DoctorRegistry` 与 `MemoryManager`
  均按该字段创建医生与规则验证；
- `scripts/run_deepseek_evolution.py`：小规模受控实验
  （每科室 12 训练 / 8 测试，关闭规则验证队列控制 API 成本）；
- 产物写入 `data/experiments/deepseek_evolution.json` 与 PNG。

### 实验结果（seed=42，约 72+ 次 DeepSeek 调用）

| 检查点 | 准确率 |
| --- | --- |
| 初始（0 训练） | 87.5% |
| 第 1 轮 | 91.7% |
| 第 2 轮 | 91.7% |
| 最终 | 85.4% |

- 案例库 62 例、经验规则 4 条；
- 曲线先升后降：训练中期达到 91.7% 峰值，最终回落；
- 原因：测试集仅 48 例（6 科室 × 8），方差大；LLM 模式下记忆规则数量少，
  且回放/课程学习带来的增益不稳定。

### 说明

- 这是小规模成本控制实验，结论用于验证“LLM 可跑通进化循环”，
  不代表最终效果；
- 后续可增大每科室训练量（如 50-100）并固定多次 seed 取平均，曲线会更稳；
- HuatuoGPT 对比实验仍在 3090 待部署。

## D10：打破闭环与多 Agent 协作深度

### 目标

1. 外部基准：不再只依赖“同一知识库生成 + 同一知识库评分”的闭环虚拟集；
2. 会诊意见交换：会诊医生能看到主诊与前一医生意见，并据此调整自己的判断。

### 实现

- `medagent_hospital/benchmarks/`：外部医学多选题评测框架，
  题目静态存于 JSON，prompt 不注入候选疾病，输出准确率与按来源分解；
- `data/benchmarks/medical_mcq_sample.json`：16 道通用医学知识点演示题，
  标注为演示样例，不构成正式基准；
- `scripts/run_medical_benchmark.py`：用当前 LLM 后端跑外部基准，
  产物写入 `data/experiments/medical_mcq_benchmark.json`；
- `scripts/run_backend_comparison.py`：多 seed × 多底座进化对比，
  输出 mean ± std，避免 D9 单 seed 先升后降的噪声结论；
- `DoctorAgent`：新增 `deliberation_weight` 与 `_diagnose_with_deliberation`，
  规则模式会诊按先前意见权重调整候选得分；LLM 模式把已有会诊意见写入
  prompt，明确允许“同意或提出不同意见”；
- 会诊意见新增 `considers` / `agrees_with` 字段，供前端与评测观察协作过程。

### 验证

- `tests/test_benchmark_mcq.py`：答案解析、准确率统计、来源分解、数据集加载；
- `tests/test_multiagent.py`：会诊医生在无先前意见时保持独立视角，
  看到主诊意见后按权重调整结论；
- `tests/test_llm_doctor.py`：LLM 会诊 prompt 包含已有会诊意见。

### 下一步

- 用真实 LLM 跑外部基准，并用更大、更独立的公开题库（CMB/CBLUE）替换样例；
- 在 Web 会诊回放中展示 `agrees_with` / `considers`；
- 评估“检索到正确案例时准确率是否更高”，把 RAG 从机制变成可审计指标。

## D11：角色化辅助诊断工作台（/assistant）

### 目标

把模拟层与辅助层分开：医院模拟负责 Agent 进化，辅助诊断界面按角色
提供会话式决策支持，最终由医生确认。

### 实现

- `POST /api/assistant/start`：录入病人信息，导医生成分诊建议与科室匹配排序；
- `POST /api/assistant/answer`：护士逐项追问，答案写回共享病人会话；
- `POST /api/assistant/confirm`：导医 / 护士 / 主诊 / 主任四阶段确认，
  支持医生改写分诊科室与诊断；
- `GET /api/assistant/state`：按会话读取当前状态，方便前端刷新；
- `medagent_hospital/web/static/assistant.{html,css,js}`：角色化工作台，
  左侧流程、中间会话、右侧患者信息与建议；
- `tests/test_web.py`：覆盖完整四阶段流程与阶段错误校验。

### 验证

- 48 个测试全部通过；
- `node --check assistant.js` 通过；
- HTTP 验证：`/api/assistant/start` 返回导医建议与科室匹配；
- 服务器运行于 `http://127.0.0.1:8000/assistant`。

### 下一步

- 医生最终确认回写案例库/经验库，让辅助层复用模拟层进化出的记忆；
- 主诊/主任界面接入 LLM 模式与会诊意见交换；
- 按角色做字段可见性控制，模拟真实科室权限。

## D12：辅助诊断工作台重构（角色独立对话 + 语音 + 医院记录库）

### 目标

1. 导医、主诊、主任各有一个独立对话窗口，Agent 只提建议，医生可讨论后确认；
2. 护士窗口取消，问诊并入主诊 Agent，由主诊决定开检查/开药；
3. 医嘱与处方持久化到医院记录库；主诊拿不准时可请求主任会诊。

### 实现

- `POST /api/assistant/message`：向任意角色窗口发送讨论消息，Agent 按角色
  规则回复（导医解释匹配依据、主诊解释鉴别诊断、主任读取历史后回应）；
- `POST /api/assistant/answer_question`：主诊 Agent 逐项追问关键症状；
- `POST /api/assistant/confirm`：导医确认分诊、主诊确认诊断并开单、
  主任确认最终方案；主诊支持 `escalate=true` 请求会诊；
- 角色窗口“录音”改为“语音转文字”，输入直接填入对话；
- `medagent_hospital/web/hospital_store.py`：SQLite 医院记录库，
  持久化会话、消息、检查医嘱与用药医嘱；
- 前端 `/assistant`：三角色独立对话窗口、症状语音转文字、角色对话语音转文字、
  Agent 回复语音朗读、主诊“结诊 / 不确定”双按钮；
- 推理模式切换：会话级 `reasoner`（规则 / DeepSeek），
  导医分诊与主诊诊断按所选模式运行，会话中可即时切换；
- 结诊后界面提示“会诊记录已保存”并提供“开始新会话”；
- 修复导航：主页新增“辅助诊断”入口，tab 逻辑跳过纯链接。

### 验证

- 50 个测试全部通过；
- `node --check assistant.js / app.js` 通过；
- HTTP 实测：导医讨论 → 确认分诊 → 主诊追问 → 开检查/用药 →
  写入记录库并完成会话。

### 说明

- 语音识别依赖浏览器 Web Speech API，失败时区分未授权/未识别/网络原因；
- Agent 回复的“AI 语音”当前用浏览器 TTS 朗读，文字内容已持久化。

## D13：拍片类检查自动生成影像报告

### 目标

主诊开出拍片类检查（CT / X线 / 核磁 / 超声 / 造影）后，自动生成结构化
影像报告并写入医院记录库，让“开检查 → 出报告”形成完整闭环。

### 实现

- `medagent_hospital/web/hospital_store.py`：新增 `reports` 表，
  提供 `add_report` / `list_reports`；
- `medagent_hospital/web/server.py`：新增 `IMAGING_KEYWORDS` 与
  `_imaging_report`，按知识库检查所见生成
  “检查所见 / 报告结论 / 建议”；
- 主诊或主任结诊时，对拍片类检查自动生成报告并持久化；
- `/assistant` 前端在“医嘱记录”面板展示影像报告内容。

### 验证

- 52 个测试全部通过；
- HTTP 实测：开出“胸部CT”结诊后生成并保存影像报告；
- 服务运行于 `http://127.0.0.1:8000/assistant`。

## D14：患者访问入口 + 后台 Agent 切换

### 目标

新增患者自助问诊页面，患者只面对一个对话窗口，后台按
“导医 → 主诊 → 主任”自动切换 Agent，体现真实的 handoff 协作；
仿真训练层保持不变。

### 实现

- `POST /api/patient/start`：创建患者会话，导医 Agent 开始问诊；
- `POST /api/patient/message`：按会话阶段路由到导医 / 主诊 / 主任，
  患者确认分诊后自动转诊，主诊不确定时升级主任会诊；
- `PatientSession`：维护当前接诊 Agent、对话消息、转诊记录
  （`handoffs`）、追问进度与建议；
- `/patient` 前端：聊天式问诊、当前接诊徽标、转诊记录、语音转文字、
  医嘱与影像报告展示；
- 复用 `hospital_store` 持久化患者会话、消息、医嘱与报告；
- 主页与辅助诊断页新增“患者入口”导航。

### 验证

- 54 个测试全部通过；
- HTTP 实测：患者描述症状 → 导医分诊 → 主诊追问 → 确认结诊；
  以及“请主任会诊” → 主任查看历史 → 确认结诊；
- 服务运行于 `http://127.0.0.1:8000/patient`。

### 下一步

- 将患者页的结诊结果回写案例库/经验库，打通“仿真训练 → 真实使用 → 反馈进化”；
- 增加更多 Agent（药师、影像科、随访护士）接入同一切换机制。
