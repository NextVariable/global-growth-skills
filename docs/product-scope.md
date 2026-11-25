# Product Scope — Global Growth Skills / Global GTM Harness

Status: **Development frozen · maintenance mode.** V1.0.0 is the stable
release. V1.1 real-model acceptance ended in **FAIL** and PR #3 remains
**Draft / Blocked**. [Current release status and evidence](maintenance.md)

## Product position

Global Growth Skills is five independently installable Agent Skills for
international go-to-market work. Each Skill keeps its own repository,
installation unit and version.

Global GTM Harness is the optional local system that coordinates research and
planning across the five Skills.

**Official positioning: AI-native GTM Research & Planning Harness.**

### Core workflow

Product Context → Market Research → ICP & Positioning → Acquisition → Sales &
Retention → Growth Experiments → GTM Package

### Core value

1. Traceable evidence and source provenance.
2. Business decisions that stay consistent across Skills.
3. An executable international growth plan.
4. A persistent, resumable run record.
5. Shared context that can be reused across handoffs.

The product does **not** claim automated customer acquisition, automated deal
closing or automatic revenue lift.

## In scope (frozen)

- Stable V1.0.0: versioned catalog, installer, local Harness, schemas, evidence
  review, five pinned Skill revisions and a release gate.
- Unreleased V1.1 draft: multi-source research (GitHub, Hacker News, operator-captured public
  web), evidence versus signal grading, nine-area GTM decision brief, GTM
  package enhancements, host contract, cost telemetry, benchmark framework.

## Out of scope / non-goals

- No sixth Skill and no new research provider.
- No new agent runtime, multi-agent architecture, orchestrator or SQLite rewrite.
- No SaaS frontend, CRM, outreach automation, ad buying or unsupervised
  marketing action.
- No claim that an unmet question or an unverified assumption is a fact.
- No invented market size, demand, adoption or willingness to pay.
- No automatic publishing, customer contact, CRM write or ad spend.

## Evidence boundaries

- Engineering validation, model quality and business outcome are three
  different claims and are reported separately.
- Structural benchmark scores are deterministic delivery-shape checks; they are
  not commercial-quality scores.
- V1.1 underwent real-model acceptance. The final candidate completed Content
  from a saved Strategy checkpoint. Acquisition was rejected and later stages
  did not run. Earlier runs and deterministic checks retain their recorded scope.
- Real commercial outcomes remain unmeasured.
- Public Hacker News or GitHub activity is a signal, not demand, adoption,
  paying customers or market size.

## Version stop conditions

A version may be released only when all of the following hold:

1. Deterministic suite is green: harness tests, installer tests, privacy scan
   (current and history), static analysis, release gate.
2. CI is green on the exact release head.
3. No open P0 (security or data integrity) or P1 (core GTM task blocked) defect.
4. README, release notes and the runtime version string agree.
5. All five Skill revisions resolve and install in a clean directory.
6. Evidence boundaries are recorded, and every unexecuted check is marked
   NOT TESTED with its reason.
7. The Product Owner authorizes merge, tag and GitHub Release.

## Freeze rules

- V1.0.0 remains the stable release. V1.1 stays frozen as a draft.
- Record outstanding issues in the maintenance backlog. Resuming V1.1
  requires explicit Product Owner authorization based on a real usage need.

## Maintenance mode

- No automatic next version and no automatic V1.2 / V2.0 work.
- Backlog classes:
  - **P0** — security or data-integrity defect.
  - **P1** — a core user task cannot be completed.
  - **P2** — experience, performance or documentation improvement.
  - **Future** — unvalidated feature ideas.
- P2 and Future items are not scheduled without evidence.
