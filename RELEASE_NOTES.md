# Global Growth Skills — V1.0.0 Release Notes

**Prepared:** 2026-11-22 · **Status:** release-ready, awaiting Product Owner authorization to merge
**Repository:** [NextVariable/global-growth-skills](https://github.com/NextVariable/global-growth-skills) · **PR:** [#1](https://github.com/NextVariable/global-growth-skills/pull/1) · **Accepted HEAD:** `251a52f0382c34b23392470ed1fd61b842cf4c0e`

V1.0 packages five independently maintained Agent Skills for international go-to-market work, plus an optional local orchestration harness. Every skill keeps its own repository, installation unit and version; this repository provides the versioned catalog, installer, harness, schemas and evidence discipline that connect them.

V1.0 is a **research and drafting system**. It produces decisions, drafts, operating packages and experiment plans for human review. It does not run campaigns, contact customers, close deals or generate revenue on its own.

## Highlights

- **Five independent skills**, each installable alone:
  - Strategy — market selection, customer choice, competitive trade-offs, entry path.
  - Content — positioning, landing pages, articles, README and social/video scripts.
  - Acquisition — channel choice, launch package, partnerships, schedule, execution checks.
  - Sales — customer actions, pilots, follow-up, activation, renewal and expansion.
  - Experiments — validation design, measurement, guardrails, results and continue/stop decisions.
- **One context, five responsibilities.** A single product brief is passed forward; no skill requires the other four.
- **GTM Harness 1.0.0** (Python 3.10+, SQLite): optional five-stage orchestration, resumable runs, revision-safe handoffs and Markdown/JSON export.
- **Evidence Engine 2.0:** claim–evidence mapping with verbatim fragments, source freshness, deduplication, conflict handling, injection blocking and package quality scoring.
- **Four provenance classes:** `operator_input`, `external_evidence`, `inference` and `proposal`. Operator-approved budgets, targets, sample sizes, independence conditions and observation windows no longer require an external citation; unsupported competitor prices, market sizes, customer counts and success thresholds still do.
- **Versioned decision contract:** downstream stages must copy approved constraints verbatim; changing a number, unit, denominator, window, budget or revision fails before any draft is written.
- **Read-only public web provider** with SSRF, DNS-rebinding and redirect protections; no login, JavaScript, search or write actions.
- **Context budget:** each stage always receives `SKILL.md`, selected references/templates, and stays within a 60 KB budget with receipt-level byte accounting.
- **Audit and doctor commands** for evidence coverage, package quality and local runtime checks.

## Evidence status

Three layers are recorded separately and must not be conflated.

| Layer | Status | Basis |
|---|---|---|
| Engineering validation | **PASS** | Deterministic tests, schema checks, installer/offline runs, CI |
| Real-model execution | **PASS** (recorded at `faa29ad`) | Authenticated Codex CLI, requested model `gpt-6.2-sol` |
| Real business outcome | **NOT MEASURED** | No publishing, outreach, CRM writes or ad spend was executed |

### Real-model acceptance record

Executed at commit [`faa29ad`](https://github.com/NextVariable/global-growth-skills/commit/faa29ad1badd2c35f345e6a4769156d9b6e3284a), the last commit before the final provenance fix. No paid model calls were made after that run.

| Workflow | Completed calls | Input / output tokens | Cached input | Wall clock | Harness stage failures |
|---|---:|---:|---:|---:|---:|
| Strategy → Acquisition → Experiments | 3/3 | 111,390 / 5,689 | 0 | 149.42 s | 0 |
| Full five stages, one retry | 10/10 | 370,350 / 11,668 | 0 | 376.82 s | 1 |

- Strategy initially returned its thresholds, observation window and independence conditions as `proposed`. The operator approved them through `revise-decision`; downstream drafts bound to revision 2 and the approved receipt SHA256.
- The full run's first content generation was rejected at persistence time because a citation was missing, stale or contradicted. No partial draft was saved; the retry resumed from the same revision-2 checkpoint and all five stages completed.
- Both runs kept the approved "at least 2 independent participants, different projects, 14-day window, 0 USD budget" constraints; neither replaced them with 3 participants or a 60% threshold.
- The hosting layer did not expose a verifiable bill, so monetary cost is recorded as `not_measured`.

### Final provenance fix

Commit `251a52f` scopes monetary provenance to operator-approved budgets and preserves validated claim IDs. It is covered by deterministic regression tests (`tests/harness/test_provenance.py`, 19 cases) plus the full harness suite. The expensive five-stage model evaluation was **not** repeated for this fix; the original real-model evidence remains the reference run.

## Validation summary

| Check | Result |
|---|---|
| Harness unit/integration tests | 125/125 pass |
| Installer tests | 10/10 pass |
| Product scenarios (fixture, no model calls) | 10/10 pass |
| RC3 deterministic evaluation (fixture + reference) | 8 runs, 0 errors |
| Catalog, schema and documentation links | 5 catalog entries, pass |
| Privacy scan (tracked files) | no current findings |
| Static analysis (ruff E4/E7/E9/F) | pass |
| Clean-directory install → init → start → step → resume → export | all commands exit 0 |
| GitHub Actions on `251a52f` | 18/18 checks success |

Fixture and reference modes verify structure and the quality rubric; they are not model-quality or business-outcome evidence.

## Known limitations

- No independent semantic reviewer is connected. Verbatim matches leave `semantic_support` at `unverified` and packages at `needs_evidence_review`.
- Provenance classification relies on structured numeric matching. English number words above ten, unusual currency formats or ambiguous prose may still demand an external citation and need human review.
- Decision-contract consistency checks read structured declarations. Contradictions that exist only in free text still require human review.
- `research-web` supports one explicit public HTTPS page. It does not support searches, logins, JavaScript-rendered pages, redirects or proxy transport.
- Approval identity is the local POSIX account that owns the private SQLite database. There is no remote authentication, multi-user RBAC or production write connector.
- Real customer adoption, paid conversion, publishing, outreach and revenue remain unmeasured. The harness does not automate acquisition or deal closing.
- Billing data depends on what the model host reports; missing values are recorded as unknown rather than estimated.

## Upgrade from RC2 / RC3

- RC2 added public GitHub research, precise source dependencies, verbatim citation checks and export.
- RC3 made the evidence gate blocking, added the public web provider, the decision contract, package quality scoring, provenance classes, `audit`/`doctor`, and the 60 KB stage context budget.
- V1.0 is the accepted, documented form of RC3: no new runtime features, corrected release documentation, a machine-readable release gate and explicit evidence boundaries.
- Upgrade in place by reinstalling the five pinned catalog revisions into a new directory; existing installs are not overwritten.

## Release gate and merge

- **Release Gate: PASS** at `251a52f0382c34b23392470ed1fd61b842cf4c0e`, on the Product Owner's acceptance.
- **Recommended merge:** create a merge commit on GitHub (not squash), so the evidence commits `faa29ad` and `251a52f` remain reachable and auditable. If the repository prefers a linear history, squash is acceptable only if these release notes and PR #1 stay linked as the evidence record.
- `main` is unchanged. No GitHub Release has been created. Both actions require the Product Owner's separate authorization.

See [docs/v1.0.0-release.md](docs/v1.0.0-release.md) for the bilingual product guide and [validation/release-gate-v1.0.0.json](validation/release-gate-v1.0.0.json) for the machine-readable gate record.

[MIT License](LICENSE). Each installed unit retains its bundled license and notices.
