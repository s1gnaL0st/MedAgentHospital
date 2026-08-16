# MedAgent-Hospital

基于论文《Agent Hospital: A Simulacrum of Hospital with Evolvable Medical Agents》
实现的医疗多 Agent 仿真与进化系统。

## 项目目标

- 复现 SEAL：仿真世界自动生成病人数据，医生 Agent 在治疗中持续进化；
- 实现 MedAgent-Zero：医学案例库（成功病例检索）+ 经验库（失败反思规则，验证后入库）；
- LLM 底座可插拔：DeepSeek API / 3090 + vLLM 部署的 HuatuoGPT-II-7B / 规则推理兜底；
- 提供 Web 仪表盘：进化训练、交互诊断回放、记忆库浏览。

> 注意：本项目中的医学知识仅用于算法演示与研究，不构成任何临床建议。

## 目录结构

```text
medagent_hospital/
├── config.py            # 配置加载（.env）
├── llm/                 # LLM 后端抽象（OpenAI 兼容 + 规则兜底）
├── agents/              # 病人 / 护士 / 医生 Agent
├── benchmarks/          # 外部医学多选题评测（不注入候选疾病）
├── memory/              # 医学案例库 + 经验库
├── knowledge/           # 疾病知识库
├── simulacrum/          # 医院仿真与进化训练
└── web/                 # FastAPI 仪表盘
docs/                    # 项目规划等文档
tests/                   # 单元测试
```

## 快速开始

```bash
pip install -r requirements-dev.txt
copy .env.example .env    # Windows
python -m pytest
```

无 API key 时使用 `LLM_BACKEND=rule` 规则模式，离线可跑。

## 启动仪表盘

```bash
python -m medagent_hospital.web.server
```

浏览器打开 `http://127.0.0.1:8000`，包含像素医院模拟、记忆库和知识库视图。
进化训练实验暂未在界面启用，可通过 CLI 运行：

```bash
python scripts/run_deepseek_evolution.py
```

## 辅助诊断工作台

浏览器打开 `http://127.0.0.1:8000/assistant`。导医、主诊、主任各有独立
对话窗口，Agent 只提建议，医生可以讨论、反驳后再确认：

1. 导医分诊：症状 → 建议科室与匹配排序，支持对话辩论；
2. 主诊问诊：主诊 Agent 追问关键症状辅助判断；
3. 主诊开单：鉴别诊断、建议检查、用药参考；
   - 点“结诊”：写入医院记录库并提示“会诊记录已保存”；
   - 点“不确定，请主任判断”：主任查看历史对话后下最终结论再结诊。

症状输入与角色对话都支持浏览器语音转文字；Agent 回复支持语音朗读。
顶部“推理模式”可在规则模式与 DeepSeek 之间切换，会话进行中也能即时切换。
主诊开出拍片类检查（CT / X线 / 核磁 / 超声 / 造影）后自动生成影像报告，
包含检查所见、报告结论与建议，并随医嘱一起写入医院记录库。
所有会话、消息、检查/用药医嘱持久化到
`data/generated/hospital_records.db`。该界面定位为医生决策支持演示，
不构成临床诊断。

## 患者入口

浏览器打开 `http://127.0.0.1:8000/patient`，患者用自然语言描述症状，
后台按“导医 → 主诊 → 主任”自动切换 Agent：

1. 导医 Agent：收集症状，给出分诊建议，患者确认后转诊；
2. 主诊 Agent：追问关键症状，给出诊断、检查与用药建议；
3. 影像分析 Agent：患者提供拍片类影像或描述时，生成影像报告辅助主诊；
4. 主任 Agent：主诊不确定时升级会诊，查看完整历史后给出最终结论。

每次转诊都会记录 `handoff` 事件；就诊完成后的医嘱和影像报告写入
医院记录库。该页面仅用于算法演示与研究，不构成临床诊断。

## 记忆流（Stanford Generative Agents 风格）

`MedicalCaseBase` 升级为带时间戳的记忆流检索：

- 时近性：`exp(-decay_rate × 记忆年龄)` 指数衰减；
- 重要性：每条记忆带 `importance` 权重；
- 相关性：症状/检查 Jaccard 相似度；
- 检索强化：每次被检索命中，`retrieval_count` +1，
  后续检索权重提升（`1 + 0.1 × retrieval_count`）。

对应 Stanford Generative Agents 的 Recency / Importance / Relevance
记忆检索与记忆巩固机制。

## DeepSeek 冒烟测试

```bash
python scripts/smoke_deepseek.py
```

运行前确认 `.env` 已配置 `LLM_BACKEND=deepseek` 和 `DEEPSEEK_API_KEY`。

## 外部基准评测（打破闭环）

内部虚拟测试集由同一份知识库生成，属于“开卷选择题”。外部医学多选题
不注入候选疾病，用于衡量模型自身的医学知识：

```bash
python scripts/run_medical_benchmark.py
```

样例题库位于 `data/benchmarks/medical_mcq_sample.json`，报告写入
`data/experiments/medical_mcq_benchmark.json`。题库越大、来源越独立，
结论越可信；建议后续替换为 CMB / CBLUE 等公开数据集。

## 多 seed 后端对比实验

```bash
python scripts/run_backend_comparison.py --backends rule llm --seeds 42 2024 7
```

每组固定同一套训练/测试配置，报告 mean ± std，避免单 seed 噪声结论。
