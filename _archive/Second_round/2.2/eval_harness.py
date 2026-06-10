"""
eval_harness.py
---------------
Rigorous evaluation of memory configurations for the Helix Labs ops agent.

USAGE
-----
    python eval_harness.py --iter v1_baseline                  # all configs
    python eval_harness.py --iter v2_rag --configs cold warm_rag

Each iteration reads training artifacts from ./artifacts/{iter}/ and writes
its evaluation results to the same directory, so iterations are fully
self-contained for side-by-side comparison.

CONFIGURATIONS
--------------
  cold          : no playbook (baseline — generic LLM only)
  warm_full     : full playbook injected, no routing (upper bound on memory)
  warm_routed   : full playbook + section router (current production)
  warm_rag      : bullet-level RAG via embeddings (top-k nearest bullets)

To add a new config, write a function with signature
    (test_case, playbook, seed) -> (plan, usage_dict, extras)
and register it in CONFIGS.

METRICS
-------
Per (config, test, seed): overall_recall, recall_actions, recall_questions,
recall_risks, recall_by_category, n_covered, n_missing, tokens_in/out,
cost_usd, latency_s, playbook_chars_in_context, sections_in_context,
bullets_retrieved (RAG only), router_section_accuracy.
"""

import argparse
import hashlib
import json
import math
import os
import statistics
import time

from memory_loop_demo import (
    MODEL, DEFAULT_TEMPERATURE,
    make_plan, grade, select_skills, parse_sections, count_bullets,
)

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
N_SEEDS = 3
TOP_K = 10  # bullets retrieved per task in warm_rag

# Embeddings: OpenAI text-embedding-3-small ($0.02/M tokens, very cheap)
# Requires `pip install openai` and OPENAI_API_KEY env var.
# Swap EMBED_MODEL / get_embeddings() to use Voyage or sentence-transformers.
EMBED_MODEL = "text-embedding-3-small"
EMBED_PRICE_PER_M = 0.02

try:
    import openai
    _openai_client = openai.OpenAI()
except Exception:
    _openai_client = None


# =============================================================================
# HELD-OUT TEST CASES
# =============================================================================
TEST_CASES = [
    {
        "id": "intl_advisor",
        "summary": "International advisor recurring setup (cross-task: T1 + T3 + T4)",
        "message": (
            "Bringing on Dr. Rafael Costa as a scientific advisor — he's based in "
            "Brazil, $3,000/month for 12 months. He just sent over his new bank "
            "account details for payment. Set this up."
        ),
        "reference_items": [
            {"kind": "action", "category": "Contract Templates",
             "text": "Use Helix's advisor agreement template v1.4 (from T4) with the international provisions from the IC template v2.1 — W-8BEN-E and 30-day notice — added as an addendum"},
            {"kind": "action", "category": "Banking & Payments",
             "text": "Pay via Wise, NOT Mercury — Helix's international payment policy (from T3); only US recurring goes through Mercury (from T4)"},
            {"kind": "action", "category": "Banking & Payments",
             "text": "Voice-verify the new bank account details with Dr. Costa on a known phone number — Helix's anti-fraud policy applies to ANY new payee bank info (from T1)"},
            {"kind": "action", "category": "Compliance",
             "text": "Collect W-8BEN-E from Dr. Costa before the first payment (from T3)"},
            {"kind": "action", "category": "Equity & Cap Table",
             "text": "Apply the standard advisor equity grant — 0.05% vesting over 12 months (from T4) — but flag for Marcus since Helix has no precedent for international advisor equity"},
            {"kind": "action", "category": "Approvals & Routing",
             "text": "Route to Marcus for approval — $36K total commitment is well above the $5K threshold (from T1)"},
            {"kind": "action", "category": "Compliance",
             "text": "Flag for 1099-equivalent (or 1042-S) reporting at year end given non-US payee"},
            {"kind": "question", "category": "Contract Templates",
             "text": "Does Dr. Costa hold conflicting advisor positions at other biotechs? Standard non-compete disclosure per the advisor agreement (from T4)"},
            {"kind": "question", "category": "Approvals & Routing",
             "text": "Has Priya reviewed his scientific background? Helix's standard for technical hires (from T3 pattern)"},
            {"kind": "question", "category": "Compliance",
             "text": "Does Brazil's tax/labor regime affect 1099 vs W-2 classification logic? (extrapolated from T3 + T4 caution)"},
            {"kind": "risk", "category": "Banking & Payments",
             "text": "International payment fraud risk: voice-verification policy from T1 applies, especially for a first-time international payee"},
            {"kind": "risk", "category": "Compliance",
             "text": "Brazil's tax law may treat recurring advisor payments differently from US — Helix doesn't manage but should flag"},
            {"kind": "risk", "category": "Equity & Cap Table",
             "text": "Helix has no precedent for international advisor equity — confirm with Marcus before issuing (1099-NEC vs 1042-S complications)"},
        ],
    },
    {
        "id": "customer_expansion",
        "summary": "Beacon SAML SSO + ARR upgrade (cross-task: T2 + T5)",
        "message": (
            "Beacon Labs (our $40K ARR customer) is asking for SAML SSO and "
            "wants to expand their contract to $80K ARR. Daniel routed this to "
            "you. Set up the upgrade."
        ),
        "reference_items": [
            {"kind": "action", "category": "Approvals & Routing",
             "text": "Daniel remains CS owner — Beacon is in the $25K–$100K ARR band per Helix's routing rules (from T2)"},
            {"kind": "action", "category": "Contract Templates",
             "text": "Issue an amended MSA on v3.2 — Beacon's existing MSA is v3.2 (confirmed during the T5 dispute), so use the same version for the upgrade"},
            {"kind": "action", "category": "Compliance",
             "text": "Enable SAML SSO — Beacon at $80K crosses Helix's $50K+ ARR threshold for SSO (from T2)"},
            {"kind": "action", "category": "Vendor & Customer History",
             "text": "Cross-check the Q1 auto-renewal dispute (from T5) is fully resolved and logged before extending — board KPI requirement"},
            {"kind": "action", "category": "Banking & Payments",
             "text": "Update Beacon's recurring ACH in Mercury for the new $80K ARR billing"},
            {"kind": "action", "category": "Approvals & Routing",
             "text": "Update the customer record in HubSpot and sync NetSuite (from T2 onboarding flow)"},
            {"kind": "question", "category": "Compliance",
             "text": "Does Beacon's new ARR tier change data residency requirements? Default is still US-East but worth confirming (from T2)"},
            {"kind": "question", "category": "Contract Templates",
             "text": "Will the amended MSA need re-signing by a VP+ at Beacon? Helix requires VP signature authority on MSAs (from T5)"},
            {"kind": "question", "category": "Vendor & Customer History",
             "text": "Has the previously disputed invoice from T5 been credited or refunded if applicable? Confirm before billing the new tier"},
            {"kind": "risk", "category": "Compliance",
             "text": "Sales tax: Helix only collects in CA and NY per the 2023 settlement — confirm Beacon's billing state given the increased contract size (from T2)"},
            {"kind": "risk", "category": "Vendor & Customer History",
             "text": "Beacon's open dispute (per T5) must be resolved within 14 days per Q1 2025 board KPI — confirm closed before expansion"},
        ],
    },
    {
        "id": "intl_contractor_batch",
        "summary": "Two more Indian engineers, 6 months each (cross-task: T1 + T3)",
        "message": (
            "Marcus wants to expand the Indian engineering team — bring on 2 more "
            "contract engineers from India for 6-month engagements at $9K/month "
            "each. Get them set up quickly."
        ),
        "reference_items": [
            {"kind": "action", "category": "Contract Templates",
             "text": "Use Helix's IC agreement template v2.1 for each engineer — the international version with W-8BEN-E provisions and 30-day notice (from T3)"},
            {"kind": "action", "category": "Banking & Payments",
             "text": "Pay via Wise, NOT Mercury — Helix switched international payments to Wise in Q2 2024 (from T3)"},
            {"kind": "action", "category": "Compliance",
             "text": "Collect W-8BEN-E from each engineer before first payment (from T3)"},
            {"kind": "action", "category": "Approvals & Routing",
             "text": "Loop in Priya to review each engineer's background before contract signing — Helix's standard for engineering hires (from T3)"},
            {"kind": "action", "category": "Approvals & Routing",
             "text": "Route to Marcus for explicit approval — total commitment of ~$108K well exceeds the $5K threshold and is a multi-headcount expansion (from T1 + T3)"},
            {"kind": "action", "category": "Equity & Cap Table",
             "text": "Decide on equity carefully: Helix's policy excludes contractor equity under 6 months (from T3) — these are exactly at the boundary, default exclude unless Marcus directs otherwise"},
            {"kind": "question", "category": "Compliance",
             "text": "Will the contractors need GitHub or customer-data access? If yes, BAA + security training required (from T3)"},
            {"kind": "question", "category": "Approvals & Routing",
             "text": "Has Marcus explicitly approved both headcounts? Deviation from standard contractor template needs his sign-off (from T3)"},
            {"kind": "risk", "category": "Compliance",
             "text": "1099 vs W-2 misclassification — Helix had a misclassification issue in 2023, so independence criteria must be documented for each engineer (from T3)"},
            {"kind": "risk", "category": "Compliance",
             "text": "India FEMA / RBI reporting for the contractors — Helix doesn't manage but should communicate the obligation (from T3)"},
        ],
    },
]


# =============================================================================
# REFERENCE-FORMAT CONVERSION
# =============================================================================
def items_to_reference(items):
    ref = {"actions": [], "questions": [], "risks": []}
    bucket = {"action": "actions", "question": "questions", "risk": "risks"}
    for it in items:
        ref[bucket[it["kind"]]].append(it["text"])
    return ref


def lookup_category(text, items):
    for it in items:
        if it["text"] == text:
            return it["category"]
    for it in items:
        if text and text in it["text"]:
            return it["category"]
    return "Unknown"


# =============================================================================
# EMBEDDINGS (for warm_rag)
# =============================================================================
def get_embeddings(texts):
    """Embed a list of strings via OpenAI. Returns list of vectors."""
    if _openai_client is None:
        raise RuntimeError(
            "OpenAI client not initialized. Set OPENAI_API_KEY in .env or "
            "install openai package (pip install openai)."
        )
    response = _openai_client.embeddings.create(
        model=EMBED_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def estimate_embed_cost(texts):
    """Rough cost estimate (1.3 tokens/word avg)."""
    total_tokens = sum(len(t.split()) * 1.3 for t in texts)
    return (total_tokens / 1e6) * EMBED_PRICE_PER_M


def cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def extract_bullets(playbook_md):
    """Pull individual bullet lines with their containing section."""
    bullets = []
    sections = parse_sections(playbook_md)
    for section, lines in sections.items():
        for line in lines:
            text = line.strip()
            if text.startswith(("-", "*")):
                bullets.append({"section": section, "text": text})
    return bullets


def get_or_compute_bullet_embeddings(playbook_md, iter_dir):
    """Compute bullet embeddings once per playbook, cache to disk."""
    cache_path = f"{iter_dir}/embeddings/playbook_bullets.json"
    current_hash = hashlib.md5(playbook_md.encode()).hexdigest()

    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cache = json.load(f)
        if cache.get("playbook_hash") == current_hash:
            return cache["bullets"], 0.0  # cached, no cost

    bullets = extract_bullets(playbook_md)
    if not bullets:
        return [], 0.0

    print(f"  → Computing embeddings for {len(bullets)} bullets...")
    embeddings = get_embeddings([b["text"] for b in bullets])
    for b, emb in zip(bullets, embeddings):
        b["embedding"] = emb

    cost = estimate_embed_cost([b["text"] for b in bullets])

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump({"playbook_hash": current_hash, "bullets": bullets}, f)
    return bullets, cost


# =============================================================================
# CONFIGURATIONS  — each returns (plan, usage, extras)
# =============================================================================
def run_cold(test_case, playbook, seed, iter_dir):
    plan, usage = make_plan(test_case["message"], "")
    extras = {
        "playbook_chars_in_context": 0,
        "sections_in_context": 0,
        "router_sections_chosen": None,
        "bullets_retrieved": None,
    }
    return plan, usage, extras


def run_warm_full(test_case, playbook, seed, iter_dir):
    plan, usage = make_plan(test_case["message"], playbook)
    sections = parse_sections(playbook)
    extras = {
        "playbook_chars_in_context": len(playbook),
        "sections_in_context": len(sections),
        "router_sections_chosen": None,
        "bullets_retrieved": None,
    }
    return plan, usage, extras


def run_warm_routed(test_case, playbook, seed, iter_dir):
    slimmed, chosen, router_usage = select_skills(test_case["message"], playbook)
    plan, plan_usage = make_plan(test_case["message"], slimmed)
    usage = {k: router_usage[k] + plan_usage[k] for k in plan_usage}
    extras = {
        "playbook_chars_in_context": len(slimmed),
        "sections_in_context": len(chosen),
        "router_sections_chosen": chosen,
        "bullets_retrieved": None,
    }
    return plan, usage, extras


def run_warm_rag(test_case, playbook, seed, iter_dir):
    """Bullet-level RAG: embed every playbook bullet, retrieve top-k by
    cosine similarity to the task message, group by section, inject."""
    bullets, embed_cost_setup = get_or_compute_bullet_embeddings(playbook, iter_dir)

    if not bullets:
        # No playbook — fall back to cold
        plan, usage = make_plan(test_case["message"], "")
        usage["cost_usd"] += embed_cost_setup
        extras = {
            "playbook_chars_in_context": 0,
            "sections_in_context": 0,
            "router_sections_chosen": None,
            "bullets_retrieved": 0,
        }
        return plan, usage, extras

    # Embed the task message
    task_emb = get_embeddings([test_case["message"]])[0]
    task_embed_cost = estimate_embed_cost([test_case["message"]])

    # Top-k retrieval
    scored = [(i, cosine_sim(task_emb, b["embedding"])) for i, b in enumerate(bullets)]
    scored.sort(key=lambda x: -x[1])
    top_indices = [i for i, _ in scored[:TOP_K]]
    retrieved = [bullets[i] for i in top_indices]

    # Reconstruct slimmed context, grouped by section (for the planner to see structure)
    by_section = {}
    for b in retrieved:
        by_section.setdefault(b["section"], []).append(b["text"])
    slimmed = "\n\n".join(f"## {s}\n" + "\n".join(bs) for s, bs in by_section.items())

    # Plan
    plan, plan_usage = make_plan(test_case["message"], slimmed)

    # Add embedding costs to this run's accounting
    # (Setup cost is amortized — only charged on first call per iteration)
    plan_usage["cost_usd"] += round(task_embed_cost + embed_cost_setup, 6)

    extras = {
        "playbook_chars_in_context": len(slimmed),
        "sections_in_context": len(by_section),
        "router_sections_chosen": list(by_section.keys()),  # for fuzzy section accuracy
        "bullets_retrieved": len(retrieved),
    }
    return plan, plan_usage, extras


CONFIGS = {
    "cold": run_cold,
    "warm_full": run_warm_full,
    "warm_routed": run_warm_routed,
    "warm_rag": run_warm_rag,
}


# =============================================================================
# METRIC COMPUTATION
# =============================================================================
def compute_metrics(plan, usage, extras, test_case, judgment):
    items = test_case["reference_items"]
    covered = judgment["covered"]
    missing = judgment["missing"]
    total = len(covered) + len(missing)

    by_kind = {"action": [0, 0], "question": [0, 0], "risk": [0, 0]}
    for c in covered:
        k = c.get("kind", "action")
        if k in by_kind:
            by_kind[k][0] += 1
            by_kind[k][1] += 1
    for m in missing:
        k = m.get("kind", "action")
        if k in by_kind:
            by_kind[k][1] += 1

    recall_by_kind = {
        kind: (n_cov / n_tot if n_tot else None)
        for kind, (n_cov, n_tot) in by_kind.items()
    }

    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], [0, 0])[1] += 1
    for c in covered:
        cat = lookup_category(c.get("ref_item", ""), items)
        if cat in by_cat:
            by_cat[cat][0] += 1
    recall_by_category = {
        cat: (n_cov / n_tot if n_tot else None)
        for cat, (n_cov, n_tot) in by_cat.items()
    }

    router_accuracy = None
    if extras.get("router_sections_chosen") is not None:
        needed_categories = {it["category"] for it in items}
        chosen = set(extras["router_sections_chosen"])
        hits = sum(
            1 for need in needed_categories
            if any(need.lower() in c.lower() or c.lower() in need.lower() for c in chosen)
        )
        router_accuracy = hits / len(needed_categories) if needed_categories else None

    return {
        "overall_recall": (len(covered) / total) if total else 0.0,
        "recall_actions": recall_by_kind["action"],
        "recall_questions": recall_by_kind["question"],
        "recall_risks": recall_by_kind["risk"],
        "recall_by_category": recall_by_category,
        "n_covered": len(covered),
        "n_missing": len(missing),
        "n_total_items": total,
        "tokens_in": usage["input_tokens"],
        "tokens_out": usage["output_tokens"],
        "cost_usd": usage["cost_usd"],
        "latency_s": usage["latency_s"],
        "playbook_chars_in_context": extras["playbook_chars_in_context"],
        "sections_in_context": extras["sections_in_context"],
        "router_sections_chosen": extras.get("router_sections_chosen"),
        "bullets_retrieved": extras.get("bullets_retrieved"),
        "router_section_accuracy": router_accuracy,
    }


# =============================================================================
# AGGREGATION
# =============================================================================
def aggregate(seed_results):
    if not seed_results:
        return {}

    numeric_keys = [
        "overall_recall", "recall_actions", "recall_questions", "recall_risks",
        "n_covered", "n_missing", "n_total_items",
        "tokens_in", "tokens_out", "cost_usd", "latency_s",
        "playbook_chars_in_context", "sections_in_context",
        "bullets_retrieved", "router_section_accuracy",
    ]
    agg = {}
    for key in numeric_keys:
        values = [r[key] for r in seed_results if r.get(key) is not None]
        if values:
            agg[key] = {
                "mean": statistics.mean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
                "n": len(values),
            }
        else:
            agg[key] = None

    all_cats = set()
    for r in seed_results:
        all_cats.update((r.get("recall_by_category") or {}).keys())
    cat_agg = {}
    for cat in all_cats:
        vals = [r["recall_by_category"].get(cat) for r in seed_results
                if r.get("recall_by_category") and r["recall_by_category"].get(cat) is not None]
        if vals:
            cat_agg[cat] = {
                "mean": statistics.mean(vals),
                "std": statistics.stdev(vals) if len(vals) > 1 else 0.0,
                "n": len(vals),
            }
    agg["recall_by_category"] = cat_agg

    return agg


# =============================================================================
# PRETTY PRINTING
# =============================================================================
def fmt_pct(x):
    if x is None:
        return "  n/a"
    return f"{x * 100:5.1f}%"


def fmt_pm(d, scale=100, suffix="%", width=12):
    if d is None:
        return f"{'n/a':>{width}}"
    m = d["mean"] * scale
    s = d["std"] * scale
    return f"{m:5.1f} ± {s:4.1f}{suffix}".rjust(width)


def print_summary(results, n_seeds, iter_name, config_names):
    lines = []
    lines.append("=" * 100)
    lines.append(f"EVAL HARNESS SUMMARY  —  iter: {iter_name}  —  {n_seeds} seeds per (config, test)")
    lines.append("=" * 100)

    for test_id, test_results in results.items():
        test_summary = next(t for t in TEST_CASES if t["id"] == test_id)["summary"]
        lines.append(f"\n──── TEST: {test_id}")
        lines.append(f"     {test_summary}")
        lines.append("")
        lines.append(f"  {'Config':<14} {'Recall':>14} {'Actions':>14} {'Questions':>14} {'Risks':>14}")
        lines.append(f"  {'-' * 14} {'-' * 14} {'-' * 14} {'-' * 14} {'-' * 14}")
        for config_name in config_names:
            if config_name not in test_results:
                continue
            agg = test_results[config_name]
            lines.append(
                f"  {config_name:<14}"
                f" {fmt_pm(agg.get('overall_recall'))}"
                f" {fmt_pm(agg.get('recall_actions'))}"
                f" {fmt_pm(agg.get('recall_questions'))}"
                f" {fmt_pm(agg.get('recall_risks'))}"
            )

        lines.append("")
        lines.append("  Per-category recall (mean across seeds):")
        all_cats = sorted({
            cat
            for agg in test_results.values()
            for cat in (agg.get("recall_by_category") or {}).keys()
        })
        header = f"    {'Category':<28}" + "".join(
            f" {c:>14}" for c in config_names if c in test_results
        )
        lines.append(header)
        for cat in all_cats:
            row = f"    {cat:<28}"
            for cfg in config_names:
                if cfg not in test_results:
                    continue
                cat_data = test_results[cfg].get("recall_by_category", {}).get(cat)
                if cat_data is None:
                    row += f" {'n/a':>14}"
                else:
                    row += f" {fmt_pct(cat_data['mean']):>14}"
            lines.append(row)

        lines.append("")
        lines.append("  Cost & context:")
        lines.append(f"    {'Config':<14} {'Cost/run':>12} {'Latency':>12} {'Ctx chars':>12} {'Sections':>12} {'Bullets':>10}")
        for cfg in config_names:
            if cfg not in test_results:
                continue
            agg = test_results[cfg]
            cost = agg.get("cost_usd")
            lat = agg.get("latency_s")
            chars = agg.get("playbook_chars_in_context")
            secs = agg.get("sections_in_context")
            bul = agg.get("bullets_retrieved")
            cost_s = f"${cost['mean']:.4f}" if cost else "n/a"
            lat_s = f"{lat['mean']:.2f}s" if lat else "n/a"
            chars_s = f"{int(chars['mean'])}" if chars else "0"
            secs_s = f"{secs['mean']:.1f}" if secs else "0"
            bul_s = f"{bul['mean']:.0f}" if bul else "n/a"
            lines.append(f"    {cfg:<14} {cost_s:>12} {lat_s:>12} {chars_s:>12} {secs_s:>12} {bul_s:>10}")

    # Overall delta table
    lines.append("\n" + "=" * 100)
    lines.append(f"HEADLINE: overall recall by config (mean ± std)  —  iter: {iter_name}")
    lines.append("=" * 100)
    col_header = f"  {'Test':<24}" + "".join(f" {c:>16}" for c in config_names)
    lines.append(col_header)
    for test_id, test_results in results.items():
        row = f"  {test_id:<24}"
        for cfg in config_names:
            if cfg in test_results:
                row += f" {fmt_pm(test_results[cfg].get('overall_recall'), width=16)}"
            else:
                row += f" {'n/a':>16}"
        lines.append(row)

    # Deltas vs cold (if cold ran)
    if "cold" in config_names:
        lines.append("")
        lines.append(f"  {'Test':<24}" + "".join(
            f" {('Δ vs cold (' + c + ')'):>20}"
            for c in config_names if c != "cold"
        ))
        for test_id, test_results in results.items():
            row = f"  {test_id:<24}"
            cold = test_results.get("cold", {}).get("overall_recall")
            for cfg in config_names:
                if cfg == "cold":
                    continue
                if cfg not in test_results or cold is None:
                    row += f" {'n/a':>20}"
                    continue
                other = test_results[cfg].get("overall_recall")
                delta = (other["mean"] - cold["mean"]) * 100
                row += f" {delta:+5.1f} pp".rjust(21)
            lines.append(row)

    out = "\n".join(lines)
    print(out)
    return out


# =============================================================================
# MAIN
# =============================================================================
def parse_args():
    p = argparse.ArgumentParser(description="Evaluate Helix memory configurations.")
    p.add_argument("--iter", required=True,
                   help="Iteration name (must match training, e.g., 'v2_bullet_rag')")
    p.add_argument("--configs", nargs="+", default=None,
                   help=f"Subset of configs to run (default: all). "
                        f"Available: {list(CONFIGS.keys())}")
    p.add_argument("--seeds", type=int, default=N_SEEDS,
                   help=f"Seeds per (config, test). Default: {N_SEEDS}")
    return p.parse_args()


def main():
    args = parse_args()
    iter_dir = f"artifacts/{args.iter}"
    playbook_path = f"{iter_dir}/memory_final.md"

    if not os.path.exists(playbook_path):
        print(f"ERROR: {playbook_path} not found.")
        print(f"Run `python memory_loop_demo.py --iter {args.iter}` first.")
        return

    with open(playbook_path) as fh:
        playbook = fh.read()

    selected_configs = CONFIGS
    if args.configs:
        invalid = [c for c in args.configs if c not in CONFIGS]
        if invalid:
            print(f"ERROR: unknown configs: {invalid}. Available: {list(CONFIGS.keys())}")
            return
        selected_configs = {k: CONFIGS[k] for k in args.configs}

    # Check OpenAI availability if warm_rag is selected
    if "warm_rag" in selected_configs and _openai_client is None:
        print("ERROR: warm_rag requires OpenAI. Install with `pip install openai` "
              "and set OPENAI_API_KEY.")
        return

    sections = parse_sections(playbook)
    n_bullets = count_bullets(playbook)
    config_names = list(selected_configs.keys())
    n_seeds = args.seeds

    print("=" * 72)
    print(f"EVAL HARNESS  —  iter: {args.iter}")
    print("=" * 72)
    print(f"Loaded playbook: {len(sections)} sections, {n_bullets} bullets, {len(playbook)} chars")
    print(f"Configs       : {config_names}")
    print(f"Test cases    : {[t['id'] for t in TEST_CASES]}")
    print(f"Seeds per cell: {n_seeds}")
    print(f"Total runs    : {len(selected_configs) * len(TEST_CASES) * n_seeds}")
    print(f"Model         : {MODEL}")
    if "warm_rag" in selected_configs:
        print(f"RAG embed     : {EMBED_MODEL}, top-k = {TOP_K}")
    print()

    raw_results = {}
    agg_results = {}

    t_start = time.time()
    total_cost = 0.0

    for test_case in TEST_CASES:
        test_id = test_case["id"]
        raw_results[test_id] = {}
        agg_results[test_id] = {}
        reference = items_to_reference(test_case["reference_items"])

        print(f"\n{'─' * 72}")
        print(f"TEST: {test_id}  —  {test_case['summary']}")
        print(f"{'─' * 72}")
        n_a = sum(1 for i in test_case['reference_items'] if i['kind'] == 'action')
        n_q = sum(1 for i in test_case['reference_items'] if i['kind'] == 'question')
        n_r = sum(1 for i in test_case['reference_items'] if i['kind'] == 'risk')
        print(f"Reference items: {len(test_case['reference_items'])} (a/q/r: {n_a}/{n_q}/{n_r})")

        for config_name, run_fn in selected_configs.items():
            seed_metrics = []
            for seed in range(n_seeds):
                print(f"  [{config_name}] seed {seed + 1}/{n_seeds}...", end=" ", flush=True)
                plan, usage, extras = run_fn(test_case, playbook, seed, iter_dir)
                judgment, grade_usage = grade(plan, reference)
                usage = {k: usage[k] + grade_usage[k] for k in usage}
                metrics = compute_metrics(plan, usage, extras, test_case, judgment)
                metrics["seed"] = seed
                metrics["plan"] = plan
                metrics["judgment"] = {
                    "n_covered": len(judgment["covered"]),
                    "n_missing": len(judgment["missing"]),
                    "missing": [m.get("ref_item", "") for m in judgment["missing"]],
                }
                seed_metrics.append(metrics)
                total_cost += usage["cost_usd"]
                print(f"recall={metrics['overall_recall']*100:.0f}%, "
                      f"cost=${usage['cost_usd']:.4f}")

            raw_results[test_id][config_name] = seed_metrics
            agg_results[test_id][config_name] = aggregate(seed_metrics)

    total_time = round(time.time() - t_start, 1)

    print()
    summary_text = print_summary(agg_results, n_seeds, args.iter, config_names)
    summary_text += (
        f"\n\nWall-clock: {total_time}s    "
        f"Total cost: ${total_cost:.4f}    "
        f"Runs: {len(selected_configs) * len(TEST_CASES) * n_seeds}\n"
    )

    os.makedirs(iter_dir, exist_ok=True)
    with open(f"{iter_dir}/eval_results.json", "w") as fh:
        json.dump({
            "iter": args.iter,
            "config": {
                "model": MODEL,
                "temperature_planner": DEFAULT_TEMPERATURE,
                "temperature_grader": 0.0,
                "n_seeds": n_seeds,
                "configs": config_names,
                "test_cases": [t["id"] for t in TEST_CASES],
                "top_k_rag": TOP_K if "warm_rag" in config_names else None,
                "embed_model": EMBED_MODEL if "warm_rag" in config_names else None,
            },
            "playbook_stats": {
                "sections": len(sections),
                "bullets": n_bullets,
                "chars": len(playbook),
            },
            "raw_results": raw_results,
            "aggregated": agg_results,
            "totals": {
                "wall_clock_s": total_time,
                "total_cost_usd": round(total_cost, 4),
                "total_runs": len(selected_configs) * len(TEST_CASES) * n_seeds,
            },
        }, fh, indent=2)
    with open(f"{iter_dir}/eval_summary.txt", "w") as fh:
        fh.write(summary_text)

    print(f"\nResults saved to:")
    print(f"  • {iter_dir}/eval_results.json")
    print(f"  • {iter_dir}/eval_summary.txt")
    if "warm_rag" in config_names:
        print(f"  • {iter_dir}/embeddings/playbook_bullets.json (cached)")


if __name__ == "__main__":
    main()
