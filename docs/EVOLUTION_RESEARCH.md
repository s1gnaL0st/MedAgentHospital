# Agent Evolution Research (2026-08-27)

## Search Snapshot

The following arXiv records were retrieved on 2026-08-27. They are research
leads, not claims that this project reproduces the papers.

| Direction | Recent record | Transferable idea |
| --- | --- | --- |
| Recursive strategy improvement | [Meta^n, arXiv:2608.24735](https://arxiv.org/abs/2608.24735) | Keep the meta-operation fixed while evolving a growing chain of strategic layers; use convergence and an archive rather than unrestricted self-editing. |
| Reliability audit | [On the Fragility of Self-Improving Agents, arXiv:2608.18066](https://arxiv.org/abs/2608.18066) | Measure seed variance and task-order effects; detailed rubrics and environment feedback are part of the learning signal. |
| Verifier-grounded optimization | [SBCO, arXiv:2608.10157](https://arxiv.org/abs/2608.10157) | Optimize the harness/planning process against an external verifier instead of trusting self-authored success claims. |
| Skill learning | [HypoForge, arXiv:2608.25770](https://arxiv.org/abs/2608.25770) | Match skill-learning strategy to the available supervision: comparative critique when outcomes are unavailable, execution outcomes when they are available. |
| Action-level utility | [AUSO, arXiv:2608.21292](https://arxiv.org/abs/2608.21292) | Evaluate skill-conditioned versus skill-free actions and weight updates by action-level benefit, not only trajectory success. |
| Programmatic skills | [Better, Faster, Stronger, arXiv:2608.11338](https://arxiv.org/abs/2608.11338) | Store executable/programmatic procedures to reduce repeated reasoning and cost. |
| Skill distillation | [Search2Skill, arXiv:2608.05245](https://arxiv.org/abs/2608.05245) | Distill reusable skills using explicit rubrics rather than raw textual memories. |
| Continual evaluation | [ContinualSkillBench, arXiv:2608.03874](https://arxiv.org/abs/2608.03874) | Test whether capability transfers and remains stable over task streams. |
| Experience reliability | [Escaping the Self-Confirmation Trap, arXiv:2606.24428](https://arxiv.org/abs/2606.24428) | Separate execute, distill and verify stages to prevent an agent from certifying its own bad experience. |

## Fit To This Project

The most suitable path is a staged combination:

1. **Skill card**: a structured condition, action, expected discriminator and
   safety boundary, rather than a copied diagnosis label.
2. **External outcome verifier**: compare skill-enabled and skill-free
   decisions on the same validation cases.
3. **Action-level credit**: record whether the skill changed examination choice,
   consultation routing or diagnosis ranking, and whether that change helped.
4. **Archive and rollback**: retain validation-best skill populations and
   discard later populations that regress.
5. **Order/seed audit**: repeat shuffled streams and multiple seeds; curriculum
   must be an explicit ablation.

## Current Implementation Status

`memory/skill_base.py` now provides `DiagnosticSkill` and
`DiagnosticSkillBase`. B7 integrates skill extraction and validation into the
offline experiment. It is intentionally separate from B6's reflection-rule
baseline.

The first B7 prototype is negative: a skill that only reranks diagnoses is not
enough. It is useful as a failed ablation because it demonstrates why the next
implementation must learn action-level utility and not merely add another
memory namespace.

This project does not claim that the above arXiv records are clinical methods,
nor that the internal generated knowledge base measures medical competence.
