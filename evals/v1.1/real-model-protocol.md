# Real-model evaluation protocol (V1.0 vs V1.1)

Status: **NOT TESTED**. No model call was made in this pass.

The structural benchmark in this directory is deterministic and cannot substitute
for this protocol. It checks delivery shape, not fact accuracy or commercial quality.

## Fixed variables

| Variable | Value |
| --- | --- |
| Product input | `evals/rc2/public-project.json` (same file for both arms) |
| Research inputs | the same GitHub and public-web captures, imported into both databases |
| Model | one value of `GTM_MODEL` for both arms |
| Stages | `strategy content launch sales experiments` |
| Budget | the `budget_constraints` already recorded in the project input |
| Tool permissions | read-only host, no shell, no web search, no MCP |
| Harness A | V1.0 at `7112a7df48d59419594619d51d279e6d0f20fb00` |
| Harness B | V1.1 at the Draft PR #3 head |

## Reproduce

Prepare two worktrees so each arm runs its own harness code:

```sh
git worktree add ../gte-v10 7112a7df48d59419594619d51d279e6d0f20fb00
git worktree add ../gte-v11 origin/feat/v1.1-gtm-intelligence
export GTM_MODEL="<model available to this Codex account>"
work="$(mktemp -d)"
```

Capture identical research for both arms and reuse the saved JSON:

```sh
cd ../gte-v10
python -m harness --db "$work/a.sqlite" init evals/rc2/public-project.json
python -m harness --db "$work/a.sqlite" prepare-pins "$work/pins"
python -m harness --db "$work/a.sqlite" research market "AI meeting notes" > "$work/research-market.json"
python -m harness --db "$work/a.sqlite" research competitor "meeting notes" --limit 3 > "$work/research-competitor.json"

cd ../gte-v11
python -m harness --db "$work/b.sqlite" init evals/rc2/public-project.json
python -m harness --db "$work/b.sqlite" prepare-pins "$work/pins"
python -m harness --db "$work/b.sqlite" change "$work/research-market.json"
python -m harness --db "$work/b.sqlite" change "$work/research-competitor.json"
```

Run each arm with timing, then export:

```sh
cd ../gte-v10
time python -m harness --db "$work/a.sqlite" start eval --execution model \
  --goal "full workflow"
time python -m harness --db "$work/a.sqlite" resume eval \
  --model "$GTM_MODEL" --checkouts-dir "$work/pins"
python -m harness --db "$work/a.sqlite" export eval > "$work/a-package.md"
python -m harness --db "$work/a.sqlite" status eval > "$work/a-status.txt"

cd ../gte-v11
time python -m harness --db "$work/b.sqlite" start eval --execution model \
  --goal "full workflow"
time python -m harness --db "$work/b.sqlite" resume eval \
  --model "$GTM_MODEL" --checkouts-dir "$work/pins"
python -m harness --db "$work/b.sqlite" export eval > "$work/b-package.md"
python -m harness --db "$work/b.sqlite" status eval > "$work/b-status.txt"
python -m harness --db "$work/b.sqlite" cost-report eval > "$work/b-cost.json"
```

If a run fails, record the failing stage and error verbatim. Use `resume --retry`
only for adapter failures and `resume --recover` only after confirming the old
process exited.

## Record

| Measure | How to collect |
| --- | --- |
| Fact accuracy | sample 20 external claims per package; count claims whose cited excerpt does not support the wording |
| Citation support | share of external claims with a valid `source_id` and verbatim quote |
| Cross-stage consistency | contract fields copied without change; audience, price and budget agree across stages |
| Executability | share of actions with owner role, preconditions, resources, metric and next step |
| Manual edits | line diff between exported package and the version a human would actually use |
| Task success | all five stages succeeded without retry |
| Tokens | host receipt input/output counts per stage |
| Wall time | `time` totals per arm |
| Model cost | only if an approved price table exists; otherwise `not_estimated` |

## Reporting rules

- Report arms A and B with the same model, inputs and permissions. If any differs, say so.
- Do not convert rubric scores into commercial-quality claims.
- A missing model, missing login or blocked network means **NOT TESTED**, not a fabricated result.
