# Research arc — v1 → v5

## Setup

Fictional Series A biotech, **Helix Labs**. The agent is an onboarding specialist: incorporation, banking, international hires, customer expansion. Training is 5 task episodes through a planner / reviewer / curator loop — the curator writes a structured markdown playbook from review feedback. Evaluation is 3 held-out cross-task tests (each touches 2–3 training episodes' facts) × N configs × 3 seeds. Grader is Sonnet at temp 0 against curated reference items tagged by `kind` (action / question / risk) and category. LLM-as-judge has not been validated against human labels.

## v1 — routing failure

`warm_routed` (section-level routing via a small router model) underperforms `warm_full` on 2/3 tests. Per-category recall says exactly what's failing: **Banking & Payments and Equity & Cap Table drop to 0%** on `intl_contractor_batch`, because "expand the engineering team" never says "banking" or "equity." Section is the wrong granularity. The +23pp Iter5 headline from the pre-harness round also doesn't survive N=3 seeds — that test now sits at +5pp ± noise.

## v2 — bullet RAG fixes routing, exposes a content gap

Bullet-level RAG (top-K=10, text-embedding-3-small) recovers Banking & Equity from 0% → 100% on `intl_contractor`. `warm_full` still wins 2/3 tests though — bullet RAG is competitive at lower context, not dominant.

The surprise was `customer_expansion` Banking & Payments stuck at **0% across every config including warm_full**. The playbook learned vendor-side banking (pay Wise not Mercury), not customer-side billing. Not a retrieval failure — a content gap. No retrieval method will fix missing content.

## v3 — cascade reveals reasoning vs retrieval

Move the planner from Sonnet to Haiku over identical bullet RAG (`warm_rag_cascade`). On `intl_advisor` and `intl_contractor`, Haiku matches Sonnet at ~half the cost ($0.018 vs $0.033). On `customer_expansion`, it collapses: **−33pp vs `warm_full`** — Haiku can't synthesize the cross-task pattern even when retrieval is good. So "cascade works" splits cleanly: retrieval-bottlenecked tasks survive the planner downgrade, reasoning-bottlenecked ones don't.

## v4 — HyDE wins and loses; displacement is the mechanism

Queries are narrative ("Bringing on Dr. Costa as an advisor in Brazil…"); bullets are declarative policy ("Pay via Wise NOT Mercury"). HyDE bridges that by embedding a synthetic playbook bullet generated from the task instead of embedding the task itself. Result: **+7.7pp on intl_advisor, +6.1pp on customer_expansion** — alignment was the bottleneck on those.

But **−6.7pp on intl_contractor_batch**. `warm_rag` already retrieves 100% on Banking & Equity there. HyDE rotates the retrieval distribution and displaces correctly-retrieved bullets. Not noise — directional across all three seeds.

Customer expansion Banking still at 0%. The content gap is unmoved by every retrieval improvement so far.

## v5 — designed positive control (not yet run)

Add a 6th training case for customer-billing-via-Mercury, retrain, watch the 0% close (or not). Until that runs, "content gap" is observational — persistent across every retrieval improvement, but not isolated. v5 is the test.
