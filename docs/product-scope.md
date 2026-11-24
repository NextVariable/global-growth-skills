# Product Scope — Global Growth Skills / Global GTM Harness

Status: **frozen** for the V1.0 / V1.1 release closure · 2026-11-23

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
5. Lower manual handoff and repeated-research cost.

The product does **not** claim automated customer acquisition, automated deal
closing or automatic revenue lift.

## In scope (frozen)

- V1.0: versioned catalog, installer, harness fixture/reference execution,
  schemas, evidence discipline, five pinned Skill revisions, release gate.
- V1.1: multi-source research (GitHub, Hacker News, operator-captured public
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
- Real-model comparison remains **NOT TESTED** until an authorized model runs on
  the fixed protocol. A missing model, login or budget is reported as NOT TESTED,
  never fabricated.
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

- V1.0.0 and V1.1.0 are frozen. Only P0 and P1 fixes are allowed.
- P2 and Future items go to the backlog; they never reopen development on their
  own.
- The next major version requires real user feedback, a concrete business need
  or a measurable product benefit. Invested effort is not a reason to ship.

## Maintenance mode

- No automatic next version and no automatic V1.2 / V2.0 work.
- Backlog classes:
  - **P0** — security or data-integrity defect.
  - **P1** — a core user task cannot be completed.
  - **P2** — experience, performance or documentation improvement.
  - **Future** — unvalidated feature ideas.
- P2 and Future items are not scheduled without evidence.
