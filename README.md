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

浏览器打开 `http://127.0.0.1:8000/assistant`，按角色推进一次就诊会话：

1. 导医分诊：症状 → 建议科室与匹配排序；
2. 护士问诊：逐项确认关键症状；
3. 主诊医师：鉴别诊断排序、建议检查、治疗参考、检索记忆；
4. 主任复核：最终诊断、治疗与随访建议。

每次确认都会写入共享会话，医生可以在任意角色界面调整建议后继续；
该界面定位为医生决策支持演示，不构成临床诊断。

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
