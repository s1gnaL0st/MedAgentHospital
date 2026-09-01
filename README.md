# MedAgent-Hospital

基于论文《Agent Hospital: A Simulacrum of Hospital with Evolvable Medical Agents》
实现的医疗多 Agent 仿真与进化系统。
<img width="2516" height="1004" alt="image" src="https://github.com/user-attachments/assets/bd7a9ae6-fe3c-45f1-a06a-7d808fba9ab9" />

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

## DeepSeek 冒烟测试

```bash
python scripts/smoke_deepseek.py
```

运行前确认 `.env` 已配置 `LLM_BACKEND=deepseek` 和 `DEEPSEEK_API_KEY`。
