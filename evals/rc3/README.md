# RC3 evaluation

Four verticals: AI SaaS, developer tools, smart hardware and B2B services.

```bash
# deterministic harness checks (no model calls)
python3 scripts/evaluate_rc3.py --mode all --report evals/rc3/baseline.json

# real model evaluation (requires an authenticated Codex CLI and Skill checkouts)
python3 scripts/evaluate_rc3.py --mode model --model <name> \
  --checkouts <dir-with-stage-checkouts> --report /tmp/rc3-model.json
```

## Evidence classes

- `fixture`: minimal synthetic outputs; proves the workflow completes and shows the quality floor.
- `reference`: deterministic reference-quality outputs; validates the rubric can distinguish strong packages. Not a model result.
- `model`: real Codex calls. `real_model_execution` records the call count and tokens; billing is `not_measured` because the CLI does not expose per-call prices.
- `business_outcome`: always `not_measured`; no real publishing, outreach, CRM changes or ad spend occurs.

`baseline.json` is the committed deterministic run. It is not evidence of real-model quality.

## Example package

[`example-package.md`](example-package.md) is the exported markdown for the AI SaaS case in `reference` mode: quality scorecard, assumptions and evidence gaps included. It is a deterministic reference artifact, not a model output.

## 真实模型验收

当前环境没有 `codex` CLI，本轮未执行真实模型调用；`real_model_execution` 为 `not_run`，费用为 `not_incurred`。不得用 fixture/reference 分数替代模型质量。具备已认证 Codex CLI 与固定 Skill checkout 的环境按以下步骤独立验收。

```bash
# 1. 四行业调用与质量汇总（每个 case 完成五阶段）
python3 scripts/evaluate_rc3.py --mode model --model <name> \
  --checkouts <dir-with-stage-checkouts> --report /tmp/rc3-model.json

# 2. 战略 + 获客配对任务（同一输入、同一模型）
python3 -m harness --db "$db" start paired --execution model --stages strategy launch
python3 -m harness --db "$db" step paired --model <name> \
  --checkout "strategy=$strategy_repo" --checkout "launch=$launch_repo" --timeout 180
python3 -m harness --db "$db" step paired --model <name> \
  --checkout "strategy=$strategy_repo" --checkout "launch=$launch_repo" --timeout 180

# 3. 证据不足 / 来源冲突 / 引文不支持 Claim
python3 -m harness --db "$db" research-web <public-url> --topic market --quote "<fragment>"
python3 -m harness --db "$db" change '<context patch json>'   # 使用独立测试库
python3 -m harness --db "$db" audit paired

# 4. 价格变化后的精确失效
python3 -m harness --db "$db" change pricing.json

# 5. 中断恢复
python3 -m harness --db "$db" resume paired --recover --model <name> \
  --checkout "strategy=$strategy_repo" --checkout "launch=$launch_repo"

# 6. 导出与逐条审查
python3 -m harness --db "$db" export paired --format json
```

## 决策契约验收（Strategy → Acquisition → Experiments）

先用确定性测试确认门禁，再用真实模型执行三阶段。三阶段之外仍需内容与销售阶段作为实验的直接上游，完整五阶段在门禁稳定后执行。

```bash
# deterministic: 20 个决策与漂移回归用例，不调用模型
python3 -m unittest tests.harness.test_decision -v

# real model: 三阶段相关流程（含作为直接上游的 content / sales）
python3 -m harness --db "$db" start drift --execution model \
  --stages strategy content launch sales experiments --goal "Validate demand"
python3 -m harness --db "$db" step drift --model <name> \
  --checkout "strategy=$strategy_repo" --checkout "content=$content_repo" \
  --checkout "launch=$launch_repo" --checkout "sales=$sales_repo" \
  --checkout "experiments=$experiments_repo" --timeout 180
# 重复 step 直到五阶段完成；每次记录 decision_revision 与 constraint_check.status

# 观察到下游拟改阈值时，走人工批准修订，而不是让模型覆盖
python3 -m harness --db "$db" revise-decision drift sample-size-3.json \
  --reason "Operator approved a wider pilot" --actor operator
```

检查项：

- Strategy 交付的 `contract` 中 `sample_size=2 participant`、`target_value=2`、`observation_window=14 days`、`budget=0 USD`。
- launch / sales / experiments 的 `constraint_refs` 逐字复制同一 `decision_id` 与 `decision_revision`，`constraint_check.status` 为 `consistent`。
- 若模型输出 3 人或 60%，必须出现在 `proposals` 且带有理由；不得出现在 `constraints`，也不得自称 approved。
- 修订后旧产物变为 stale，下一次请求使用新 revision；旧 revision 的声明触发 `stale_version`。

**NOT TESTED**：当前环境没有可用模型宿主，本轮只执行确定性测试。真实模型结果、token 和耗时不得填写估计值。

## 来源分类验收（Evidence Provenance）

先复现并确认修复，不调用模型：

```bash
# 15 个来源分类与工作流回归用例
python3 -m unittest tests.harness.test_provenance -v
```

复现原始缺陷：不带操作者上下文审计 “0 USD” 文本会得到 `missing_claims`；同一文本在 `budget.amount_minor=0` 上下文下为 `no_claims`，`provenance.operator_input` 含 `budget`。真实模型流程（具备宿主时）：

```bash
python3 -m harness --db "$db" start provenance --execution model \
  --stages strategy content launch sales experiments --goal "Validate demand"
python3 -m harness --db "$db" step provenance --model <name> \
  --checkout "strategy=$strategy_repo" --checkout "content=$content_repo" \
  --checkout "launch=$launch_repo" --checkout "sales=$sales_repo" \
  --checkout "experiments=$experiments_repo" --timeout 180
python3 -m harness --db "$db" audit provenance
```

检查项：

- 正文中的 `0 USD` / `100 USD`、已批准样本量、独立条件和观察期进入 `provenance.operator_input`，不触发 `missing_claims`。
- 竞品价格、市场规模、付费客户数量和模型自增百分比阈值仍留在 `unmapped_external_flags`，除非有结构化 claim。
- `provenance.external_evidence` 只包含映射到来源的 claim；`inference` 保留假设；`proposal` 保留未批准建议。
- 包状态不再因操作者预算变为 `incomplete_evidence`；模型或手工交接的决策仍需要 `needs_decision_review`。

记录要求：

- 每次模型调用的模型名、输入/输出/缓存 token、耗时、`prompt_bytes`、`skill_document_bytes` 和 `skill_package_bytes`。
- 每条 claim 的 `support`、`semantic_support`、`review.verdict`；没有评审器时必须保持 `needs_review`。
- 包状态（`incomplete_evidence`、`needs_evidence_review`、`needs_quality_review`、`ready_for_internal_review`）。
- 失败、重试和恢复次数；货币成本若宿主不提供则记 `not_measured`。
- 与 RC2 对照输入/输出/缓存 token、端到端耗时、文档字节、任务成功率和包质量；不要把 Reference Score 当作模型质量。
- 真实发布、客户触达和业务结果始终为 `not_measured`。
