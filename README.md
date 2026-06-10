# Compounding Memory Agent

*Pressure-testing where playbook-style memory actually breaks.*

A small experimental harness for studying compounding memory in LLM agents — when it helps, when it hurts, and which failure mode causes which. Four iterations against a held-out test suite over a fictional Series A biotech ("Helix Labs"), decomposing retrieval-based memory failures into five distinct mechanisms.

## TL;DR

"Compounding memory works" is not one claim — it bundles at least five distinct failure modes, and the technique that fixes one often introduces another. This repo isolates each.

| Config | intl_advisor | customer_expansion | intl_contractor_batch | $/run |
|---|---|---|---|---|
| cold | 61.5% | 39.4% | 53.3% | $0.028 |
| warm_full | 89.7% | 78.8% | 80.0% | $0.035 |
| warm_routed | 74.4% | 51.5% | 80.0% | $0.022 |
| warm_rag | 76.9% | 48.5% | 86.7% | $0.032 |
| warm_rag_cascade | 72.3% | 45.5% | 80.0% | **$0.018** |
| warm_rag_hyde | **84.6%** | **54.5%** | 80.0% | $0.033 |

## Five failure modes

1. **Routing failure** — Section-level routing systematically drops categories not lexically named in the task. *Fix: bullet-level retrieval (v2).*
2. **Reasoning bottleneck** — Cascade (Haiku planner over RAG) matches Sonnet on retrieval-bottlenecked tasks at half the cost; collapses on reasoning-bottlenecked ones. *Diagnostic: −33pp on customer_expansion vs warm_full.*
3. **Alignment failure** — Queries are narrative ("Bringing on Dr. Costa as an advisor in Brazil…"); bullets are declarative policy ("Pay via Wise NOT Mercury"). HyDE bridges the gap by generating synthetic playbook bullets as queries. *Effect: +6 to +8pp where alignment was the bottleneck.*
4. **Displacement** — HyDE rotates the retrieval distribution. On tasks where retrieval was already saturated, HyDE displaces correctly retrieved bullets and *hurts* recall. *Effect: −6.7pp on intl_contractor_batch.*
5. **Content gap** — When the curator never learned a pattern, no retrieval trick can recover it. Customer expansion Banking & Payments stays at 0% across cold, warm_full, warm_routed, warm_rag, cascade, AND HyDE. *Not yet closed; positive control designed in v5.*

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY and OPENAI_API_KEY
```

## Run

```bash
# Train (produces playbook)
python memory_loop_demo.py --iter v4_hyde

# Evaluate all configs
python eval_harness.py --iter v4_hyde

# Or a subset
python eval_harness.py --iter v4_hyde --configs warm_rag warm_rag_hyde
```

Default sweep: 5 training episodes → markdown playbook; 3 held-out test cases × 6 configs × 3 seeds = 54 eval runs; ~$1.50 cost; ~20 min wall-clock.

## What each iteration tests

| Iter | Question | Config added | Result |
|---|---|---|---|
| v1 | Does section routing work? | warm_routed | Categories drop when not named in task |
| v2 | Does finer-grained retrieval fix it? | warm_rag | Yes, but warm_full still wins; first content-gap signal |
| v3 | Can a smaller planner work over good retrieval? | warm_rag_cascade | Yes if retrieval-bottlenecked, no if reasoning-bottlenecked |
| v4 | Does query-document alignment close the warm_rag gap? | warm_rag_hyde | Partially — and reveals displacement as a side effect |
| v5 | Is the persistent 0% a content gap? | (designed) +T6 training case | TBD |

## Repo structure

```
.
├── memory_loop_demo.py        # Training script (planner / reviewer / curator / grader / router)
├── eval_harness.py            # Eval harness with 6 configs, paired across 3 held-out tests
├── artifacts/
│   ├── v1_baseline/           # memory_final.md, ep snapshots, eval_results.json, eval_summary.txt
│   ├── v2_bullet_rag/
│   ├── v3_cascade/
│   └── v4_hyde/
├── docs/
│   ├── research_arc.md        # Narrative of v1 → v4 with surprises
│   └── v5_proposal.md         # Content-gap positive control (designed, not yet run)
├── requirements.txt
└── .env.example
```

## Methodology

- **Grader pinned to Sonnet, temp 0**, against curated reference items per test (each tagged with kind: action/question/risk and category)
- **3 seeds per (config, test)**, planner at temp 0.7
- **Bullet embeddings cached** by playbook hash (text-embedding-3-small, top-K=10)
- **Per-config cost tracking** including cascade's per-role attribution
- **Retry with exponential backoff** (2s → 60s, max 6) on Anthropic overload

## What's honest about this work

- n=3 seeds is enough for direction, not magnitude. Several deltas in v4 are within 1 std of zero. The displacement finding survives because it's directional across all three tests; the +7.7pp on intl_advisor would need 5+ seeds to defend tightly.
- The "content gap" finding is observational. A positive control (v5) is designed but not yet run: add a sixth training case for customer-billing-via-Mercury, retrain, watch the 0% close (or not). Until then, the claim is "persistent 0% across every retrieval improvement," not "content gap proven."
- The LLM grader hasn't been validated against human labels. I'd want spot-checks before claiming any single config "wins" by a small margin.

## What's next

- v5: content-gap positive control (designed in `docs/v5_proposal.md`)
- Ensemble retrieval: union of warm_rag and warm_rag_hyde top-K, deduplicated — addresses the displacement tradeoff
- Top-K sweep (5/10/15/20) on cached embeddings — cheap follow-up
- Paired-delta reporting and grader noise-floor measurement (statistical hygiene)
- Sleep-time compute: curator runs async between episodes (inspired by Anthropic's framing of memory as a workload)
