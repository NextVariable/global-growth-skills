# V1.1 Structural Benchmark

`cases.json` defines three public product cases used by `scripts/benchmark_v11.py`:

| Case | Segment | Public reference |
| --- | --- | --- |
| `ai-saas` | AI SaaS | Granola public site and pricing page |
| `developer-tools` | Developer Tools | Biome public documentation and repository |
| `smart-hardware` | Smart Hardware | Oura public product and membership pages |

Reference URLs only identify public material. The fixtures import no price, revenue, customer count or market-size claim from them.

## Modes

All three modes are deterministic fixtures; none calls a model.

- `generic_single_agent` — one prose response pretending to cover all five stages.
- `manual_five_skills` — the five skills run separately with no structured handoff.
- `harness_orchestrated` — the full Harness with decision brief, contract checks and handoff.

## Run

```sh
python3 scripts/benchmark_v11.py --report /tmp/v11-benchmark.json
python3 scripts/benchmark_v11.py --live --report /tmp/v11-benchmark-live.json
```

`--live` adds public Hacker News discussion snapshots via the read-only HN provider. Points and comments are discussion activity, not demand, adoption or market size.

## What the numbers mean

`quality` is the deterministic rubric score out of 100. It checks delivery structure, traceability fields, consistency and action completeness. It is not a semantic quality score and not a business-result score.

`complete_actions` counts action items that carry an owner role, preconditions, resources, metric and next step.

`decision_ready` and `external_basis_refs` stay at zero in offline mode because no sources are captured. They rise only when sources are supplied, which is the intended behaviour: missing evidence stays `needs_evidence` rather than being filled with invented numbers.

Repository metadata and Hacker News discussions are recorded as `external_signal`. They never make an area `decision_ready` on their own; only an explicitly captured public web page counts as `external_evidence`.

## Boundaries

- Real model execution: **NOT TESTED** in this pass. No model tokens or cost were produced.
- Business outcome: **not measured**. No customers, revenue, retention or conversion results exist.
- Do not cite these scores as commercial quality evidence.
