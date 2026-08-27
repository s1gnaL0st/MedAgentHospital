# 机制实验协议（v1）

## 研究问题

本项目不验证“仿真医院能否替代真实医院”，也不将结果解释为临床有效性。初步实验验证以下机制命题：

> 在相同病例、相同推理后端和相同预算下，动态多 Agent 会诊、案例记忆与失败反思自进化，能否提升未见仿真病例上的决策质量，并且收益是否值得额外协作成本？

患者网页、PostgreSQL、Redis 和 LangGraph checkpoint 属于工程演示与基础设施，不是本实验的主要因变量。

## 假设与对照

| 编号 | 条件 | 回答的问题 |
| --- | --- | --- |
| B0 | 单医生 + 无记忆 | 基础决策能力与成本 |
| B1 | 单医生 + 案例记忆 | 成功案例检索是否改善未见病例 |
| B2 | 动态会诊 + 无记忆 | 多 Agent 协作是否优于单医生 |
| B3 | 动态会诊 + 案例记忆 | 记忆与协作能否叠加 |
| B4 | 动态会诊 + 失败反思自进化 | 规则验证、生命周期和失败回放是否持续改善 |
| B5 | 固定流程 + 每例会诊 | 动态升级是否优于无差别会诊 |
| B6 | 验证器驱动的选择性自进化 | 高价值失败筛选与严格规则验证是否优于普通自进化 |
| B7 | Skill-level 自进化 | 可复用技能卡是否优于直接写入经验规则 |
| B8 | 主动检查技能自进化 | Skill 是否能学习“何时追加/替换检查”的可执行动作 |

B0/B1 隔离案例记忆，B0/B2 隔离协作，B3/B4 隔离反思式自进化，B4/B6 隔离选择策略，B6/B7 隔离规则与 Skill 表示，B7/B8 隔离被动重排与主动检查动作，B2/B5 隔离动态路由。所有条件使用同一 seed 的完全相同 train、validation、test 病例。

B6 借鉴近期 Agent 优化中反复出现的三个稳定方向：verifier-guided admission、
uncertainty/utility-based experience selection 和 diversity-aware replay。它不是某一篇论文的
直接复现，而是针对本项目环境的可解释组合：只优先回放低置信/易混淆失败，并要求候选规则在
验证集上带来至少一个正确样本的净增益后才入库；规则只有在全部触发证据出现时才执行，
并用 validation checkpoint selection / early stop 防止后期记忆退化。

## 数据与隔离

- 数据源：`data/knowledge_base.json` 的 6 个科室、48 种疾病；病例由 `PatientGenerator` 以固定 seed 生成。
- 训练集：允许成功案例写入；只有 B4 可从失败中生成并验证经验规则。
- 验证集：仅用于 B4/B6 的候选规则准入与 B6 checkpoint selection。默认每病种 8 例，共 384 例/seed；验证运行在记忆副本上，验证集不写入案例库、规则库、检索强化计数或回放缓冲。
- 测试集：只读。每次测试评估使用训练记忆的深拷贝；代码在评估前后比较原始记忆签名，发生变更直接报错。
- 难度：测试和训练均包含普通病例与易混淆疾病组的症状混合病例，并记录 `ordinary` / `confusable` 子组指标。
- 主实验的训练与测试使用匹配的难度分布；课程学习必须作为独立消融条件，不能和记忆或反思策略绑在一起。
- 可复现性：输出记录每个 seed 的 train/validation/test SHA-256 清单、样本量、配置和条件定义。

当前内部知识库既生成患者又提供规则诊断，因此该实验是**机制验证**，不是独立医学泛化评估。外部 CMB、CBLUE 或经过许可的真实世界回顾性数据只能作为后续验证，且需保持病例来源和标签独立。

## 指标

核心质量指标：

- `diagnosis_accuracy`：最终诊断准确率；
- `department_accuracy`：分诊科室准确率；
- `top_k_accuracy` 与 `top_k_coverage`：只有可得到规则分数的后端才统计 Top-3；LLM JSON 输出没有候选分数时明确标记覆盖率；
- `consultation_gain`：发生会诊时，最终结论相对主诊初判的平均净改变量；
- `consultation_correction_rate` / `consultation_harm_rate`：会诊纠错与会诊造成的回退比例。

成本与机制指标：

- `consultation_trigger_rate`、`average_steps`、`average_exam_count`；
- `case_memory_hits`、`rule_memory_hits` 及命中率；
- `case_count`、`case_skipped`、`rule_count`、`rule_survival_rate`；
- `replay_episodes`、`replay_recovered`。

所有指标同时保留总体、按科室、按疾病和按病例难度的明细。真实 LLM 实验还应在运行层记录 token、延迟和 API 成本；规则后端不报告虚构的 token 成本。

## 运行

推荐先执行小规模离线冒烟：

```powershell
D:\python\python.exe scripts\run_initial_experiment.py `
  --seeds 42 `
  --patients-per-department 8 `
  --test-per-department 8
```

默认初步设置使用 3 个 seed、六科室均衡划分的训练集和测试集各 1008 例
（每科 168 例），验证集 384 例（每病种 8 例）：

```powershell
D:\python\python.exe scripts\run_initial_experiment.py
```

产物：

- `data/experiments/initial_experiment.json`：完整配置、数据清单、病例级聚合指标和多 seed 汇总；
- `data/experiments/initial_learning_curves.png`：各条件的 held-out 学习曲线。

LLM 对比必须固定模型版本、temperature、max tokens、重试规则和相同 cohort manifest。不要把 API 失败后的规则回退与原始 LLM 能力混为一组报告。

## 报告与判读

先报告每个 seed 的原始结果，再报告 `mean +/- std`，不能只挑选最优 seed。除准确率外，必须并列会诊率、平均步骤和会诊纠错/伤害率。

负结果是有效结果。例如：B4/B6 未优于 B3，说明当前反思策略没有带来稳健增益；B5 与 B2 性能相近但步骤显著更高，说明固定每例会诊不划算；案例命中率高但准确率不升，提示记忆可能只是冗余或污染。

结论边界：该协议能支持“特定仿真环境中的机制比较”，不能支持“临床可用”“优于医生”或“对真实患者安全”的结论。
