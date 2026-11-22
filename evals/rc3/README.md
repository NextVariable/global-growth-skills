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
