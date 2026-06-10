# v5 — content-gap positive control

## What v4 leaves unresolved

`customer_expansion` Banking & Payments sits at **0% recall across every config so far** — cold, warm_full, warm_routed, warm_rag, warm_rag_cascade, warm_rag_hyde. The user-facing claim in the README is that this is a *content gap*: the playbook learned vendor-side banking ("pay Wise not Mercury" for international contractors) but never accumulated a rule for customer-side billing (e.g. how Helix collects payment from Beacon when they upgrade their ARR).

That's the most plausible explanation given the data, but it's observational. Five different retrieval strategies all hitting 0% is consistent with "content not in the playbook," but it's also consistent with "retrieval pathology none of these strategies escapes." Until we manipulate the content directly, we can't isolate which.

## The intervention

Add **T6** to the training set. A customer-billing scenario specific enough to seed a Banking & Payments bullet on the customer side. Something like:

> "Beacon (existing customer) wants to switch from monthly to annual on their next renewal. They're asking us to invoice via Stripe with NET-30 terms. What's the right path?"

This forces the curator to write a customer-billing-side bullet — probably in Banking & Payments, possibly in Vendor & Customer History. The reviewer's reference items should include billing-side risks (revenue recognition, NET-30 cash flow, dunning) so the lesson gets surfaced.

## What we should see

Re-run all 6 configs on the same 3 held-out tests (unchanged) plus optionally a new held-out variant of customer_expansion that explicitly tests the new content.

Predictions:
- `warm_full` on customer_expansion Banking & Payments: 0% → 100% (or close). This confirms the content gap.
- `warm_rag` on the same: should also recover, assuming the new bullet's embedding is reachable from the SSO / ARR query. If `warm_rag` stays at 0% while `warm_full` rises, the bottleneck moves from content to retrieval-of-content.
- `warm_rag_hyde`: depends on the synthetic bullet. If HyDE generates "set up customer invoicing in Stripe with NET-30," it should match; if it generates "ensure Mercury banking compliance for the customer," it won't.

## What kills the hypothesis

- If `warm_full` on the new playbook still flatlines at 0% on Banking & Payments → the curator didn't write the bullet, or wrote it in the wrong section. The gap was process, not content.
- If only `warm_full` recovers and every retrieval config stays at 0% → there's a retrieval issue independent of content.
- If everything stays at 0% → grader artifact. The reference items for that category might not be reachable from any plausible plan output.

## Cost

One training run (5 → 6 episodes, ~+$0.10) + one eval (~$1.50). ~$1.60 to settle a claim the README is currently making conditionally.

## Not in scope for v5

- Ensemble retrieval (union of `warm_rag` and `warm_rag_hyde` top-K, deduplicated) — addresses displacement; orthogonal to content gap.
- Top-K sweep on cached embeddings — cheap follow-up; doesn't bear on the content question.
- Grader noise-floor measurement — needs separate runs at temp 0 with fixed inputs to estimate the floor.
