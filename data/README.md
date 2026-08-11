# data

Generated patients, experiment metrics and figures go here.
Runtime-generated content under `experiments/` and `generated/` is git-ignored.
# data

Generated patients, experiment metrics and figures go here.
Runtime-generated content under `experiments/` and `generated/` is git-ignored.

## knowledge_base.json

结构化医学知识库（演示与研究用途，非临床建议）：

- 6 个科室：心内科、呼吸科、消化科、神经内科、内分泌科、皮肤科；
- 48 种常见疾病；
- 每种疾病包含：症状、危险因素、检查及典型结果、治疗方案、鉴别要点；
- `patient_profile` 提供年龄范围、性别倾向、症状权重、病史倾向、检查命中率，
  供病人 Agent 生成器采样使用。
