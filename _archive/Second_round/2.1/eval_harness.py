"""
eval_harness.py
---------------
Rigorous evaluation of memory configurations for the Helix Labs ops agent.

Loads the trained playbook from ./artifacts/memory_final.md and evaluates
multiple configurations against multiple held-out test cases, with multiple
seeds per (config, test) pair so that variance is reported, not hidden.

CONFIGURATIONS
--------------
  cold          : no playbook at all (baseline — generic LLM only)
  warm_full     : full playbook injected, no routing (upper bound on memory)
  warm_routed   : full playbook + section router (current production config)

  Easy to extend: add a new function with signature
      (test_case, playbook, seed) -> (plan, usage_dict, extras)
  and register it in CONFIGS.

TEST CASES
----------
  intl_advisor          : intl advisor recurring — requires T1 + T3 + T4 facts
  customer_expansion    : Beacon SSO + ARR upgrade — requires T2 + T5 facts
  intl_contractor_batch : 2 more Indian engineers — requires T1 + T3 facts

METRICS
-------
Per (config, test, seed):
    overall_recall, recall_actions, recall_questions, recall_risks,
    recall_by_category, n_covered, n_missing,
    tokens_in, tokens_out, cost_usd, latency_s,
    playbook_chars, sections_in_context, router_sections_chosen,
    router_sections_correct (when category-tagged refs allow)

Aggregated per (config, test):
    mean ± std for every numeric metric across seeds

Output:
    artifacts/eval_results.json  — full nested results
    artifacts/eval_summary.txt   — human-readable comparison tables
"""

import json
import os
import statistics
import time

from memory_loop_demo import (
    ARTIFACTS_DIR, MODEL, DEFAULT_TEMPERATURE,
    make_plan, grade, select_skills, parse_sections, count_bullets,
)

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
N_SEEDS = 3       # runs per (config, test) — bump to 5 if you have budget
PLAYBOOK_PATH = f"{ARTIFACTS_DIR}/memory_final.md"


# =============================================================================
# HELD-OUT TEST CASES — each reference item tagged with a category so we can
# compute per-category recall and detect routing failures.
# =============================================================================
TEST_CASES = [
    {
        "id": "intl_advisor",
        "summary": "International advisor recurring setup (cross-task synthesis: T1 + T3 + T4)",
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
        "summary": "Beacon SAML SSO + ARR upgrade (cross-task: T2 + T5 — accumulated Beacon-specific facts)",
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
        "summary": "Two more Indian engineers, 6 months each (cross-task: T1 + T3 — scaled contractor hire)",
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
    """Convert flat list of {kind, text, category} into grader-expected
    {actions, questions, risks} of strings."""
    ref = {"actions": [], "questions": [], "risks": []}
    bucket = {"action": "actions", "question": "questions", "risk": "risks"}
    for it in items:
        ref[bucket[it["kind"]]].append(it["text"])
    return ref


def lookup_category(text, items):
    """Look up the category of a reference item by its text (exact match)."""
    for it in items:
        if it["text"] == text:
            return it["category"]
    # fallback: substring match
    for it in items:
        if text and text in it["text"]:
            return it["category"]
    return "Unknown"


# =============================================================================
# CONFIGURATIONS — each returns (plan, usage_dict, extras)
# =============================================================================
def run_cold(test_case, playbook, seed):
    """No memory — pure base-model performance."""
    plan, usage = make_plan(test_case["message"], "")
    extras = {
        "playbook_chars_in_context": 0,
        "sections_in_context": 0,
        "router_sections_chosen": None,
    }
    return plan, usage, extras


def run_warm_full(test_case, playbook, seed):
    """Full playbook, no routing — upper bound on what memory can give."""
    plan, usage = make_plan(test_case["message"], playbook)
    sections = parse_sections(playbook)
    extras = {
        "playbook_chars_in_context": len(playbook),
        "sections_in_context": len(sections),
        "router_sections_chosen": None,
    }
    return plan, usage, extras


def run_warm_routed(test_case, playbook, seed):
    """Full playbook + section router — current production config."""
    slimmed, chosen, router_usage = select_skills(test_case["message"], playbook)
    plan, plan_usage = make_plan(test_case["message"], slimmed)
    # Combine usage from router + planner
    usage = {k: router_usage[k] + plan_usage[k] for k in plan_usage}
    extras = {
        "playbook_chars_in_context": len(slimmed),
        "sections_in_context": len(chosen),
        "router_sections_chosen": chosen,
    }
    return plan, usage, extras


CONFIGS = {
    "cold": run_cold,
    "warm_full": run_warm_full,
    "warm_routed": run_warm_routed,
}


# =============================================================================
# METRIC COMPUTATION
# =============================================================================
def compute_metrics(plan, usage, extras, test_case, judgment):
    """Compute all metrics for one (config, test, seed) run."""
    items = test_case["reference_items"]
    covered = judgment["covered"]
    missing = judgment["missing"]
    total = len(covered) + len(missing)

    # Per-kind recall
    by_kind = {"action": [0, 0], "question": [0, 0], "risk": [0, 0]}  # [covered, total]
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

    # Per-category recall
    by_cat = {}  # category -> [covered, total]
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

    # Router section accuracy (if router was used)
    router_accuracy = None
    if extras.get("router_sections_chosen") is not None:
        # "Correct" sections = the set of categories that contain at least one
        # reference item; router should pick at least these (heuristic — section
        # names won't perfectly match category names, but close enough)
        needed_categories = {it["category"] for it in items}
        chosen = set(extras["router_sections_chosen"])
        # Fuzzy match: section is "hit" if its name appears in any needed category or vice versa
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
        "router_section_accuracy": router_accuracy,
    }


# =============================================================================
# AGGREGATION
# =============================================================================
def aggregate(seed_results):
    """Across N seeds: compute mean ± std for every numeric metric."""
    if not seed_results:
        return {}

    numeric_keys = [
        "overall_recall", "recall_actions", "recall_questions", "recall_risks",
        "n_covered", "n_missing", "n_total_items",
        "tokens_in", "tokens_out", "cost_usd", "latency_s",
        "playbook_chars_in_context", "sections_in_context",
        "router_section_accuracy",
    ]
    agg = {}
    for key in numeric_keys:
        values = [r[key] for r in seed_results if r[key] is not None]
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

    # Per-category recall aggregated separately
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
    """Format mean ± std."""
    if d is None:
        return f"{'n/a':>{width}}"
    m = d["mean"] * scale
    s = d["std"] * scale
    return f"{m:5.1f} ± {s:4.1f}{suffix}".rjust(width)


def print_summary(results, n_seeds):
    """Print a human-readable comparison."""
    lines = []
    lines.append("=" * 92)
    lines.append(f"EVAL HARNESS SUMMARY — {n_seeds} seeds per (config, test)")
    lines.append("=" * 92)

    # Per-test comparison
    for test_id, test_results in results.items():
        test_summary = next(t for t in TEST_CASES if t["id"] == test_id)["summary"]
        lines.append(f"\n──── TEST: {test_id}")
        lines.append(f"     {test_summary}")
        lines.append("")
        lines.append(f"  {'Config':<14} {'Recall':>14} {'Actions':>14} {'Questions':>14} {'Risks':>14}")
        lines.append(f"  {'-' * 14} {'-' * 14} {'-' * 14} {'-' * 14} {'-' * 14}")
        for config_name, agg in test_results.items():
            lines.append(
                f"  {config_name:<14}"
                f" {fmt_pm(agg.get('overall_recall'))}"
                f" {fmt_pm(agg.get('recall_actions'))}"
                f" {fmt_pm(agg.get('recall_questions'))}"
                f" {fmt_pm(agg.get('recall_risks'))}"
            )

        # Per-category recall (where applicable)
        lines.append("")
        lines.append("  Per-category recall (mean across seeds):")
        all_cats = sorted({
            cat
            for agg in test_results.values()
            for cat in (agg.get("recall_by_category") or {}).keys()
        })
        header = f"    {'Category':<28}" + "".join(f" {c:>14}" for c in test_results.keys())
        lines.append(header)
        for cat in all_cats:
            row = f"    {cat:<28}"
            for cfg in test_results.keys():
                cat_data = test_results[cfg].get("recall_by_category", {}).get(cat)
                if cat_data is None:
                    row += f" {'n/a':>14}"
                else:
                    row += f" {fmt_pct(cat_data['mean']):>14}"
            lines.append(row)

        # Cost / context table
        lines.append("")
        lines.append("  Cost & context:")
        lines.append(f"    {'Config':<14} {'Cost/run':>12} {'Latency':>12} {'Ctx chars':>12} {'Sections':>12}")
        for cfg, agg in test_results.items():
            cost = agg.get("cost_usd")
            lat = agg.get("latency_s")
            chars = agg.get("playbook_chars_in_context")
            secs = agg.get("sections_in_context")
            cost_s = f"${cost['mean']:.4f}" if cost else "n/a"
            lat_s = f"{lat['mean']:.2f}s" if lat else "n/a"
            chars_s = f"{int(chars['mean'])}" if chars else "0"
            secs_s = f"{secs['mean']:.1f}" if secs else "0"
            lines.append(f"    {cfg:<14} {cost_s:>12} {lat_s:>12} {chars_s:>12} {secs_s:>12}")

    # Overall delta table
    lines.append("\n" + "=" * 92)
    lines.append("HEADLINE: warm vs cold — overall recall delta (mean ± std)")
    lines.append("=" * 92)
    lines.append(f"  {'Test':<26} {'Cold':>16} {'Warm Full':>16} {'Warm Routed':>16} {'Δ (routed-cold)':>18}")
    for test_id, test_results in results.items():
        cold = test_results.get("cold", {}).get("overall_recall")
        wf = test_results.get("warm_full", {}).get("overall_recall")
        wr = test_results.get("warm_routed", {}).get("overall_recall")
        delta_pp = None
        if cold and wr:
            delta_pp = (wr["mean"] - cold["mean"]) * 100
        delta_s = f"{delta_pp:+.1f} pp" if delta_pp is not None else "n/a"
        lines.append(
            f"  {test_id:<26}"
            f" {fmt_pm(cold):>16}"
            f" {fmt_pm(wf):>16}"
            f" {fmt_pm(wr):>16}"
            f" {delta_s:>18}"
        )

    out = "\n".join(lines)
    print(out)
    return out


# =============================================================================
# MAIN
# =============================================================================
def main():
    # Load trained playbook
    if not os.path.exists(PLAYBOOK_PATH):
        print(f"ERROR: {PLAYBOOK_PATH} not found.")
        print("Run `python memory_loop_demo.py` first to build the playbook.")
        return
    with open(PLAYBOOK_PATH) as fh:
        playbook = fh.read()

    sections = parse_sections(playbook)
    n_bullets = count_bullets(playbook)
    print("=" * 72)
    print("EVAL HARNESS")
    print("=" * 72)
    print(f"Loaded playbook: {len(sections)} sections, {n_bullets} bullets, "
          f"{len(playbook)} chars")
    print(f"Configs       : {list(CONFIGS.keys())}")
    print(f"Test cases    : {[t['id'] for t in TEST_CASES]}")
    print(f"Seeds per cell: {N_SEEDS}")
    print(f"Total runs    : {len(CONFIGS) * len(TEST_CASES) * N_SEEDS}")
    print(f"Model         : {MODEL}")
    print()

    # Run: per-test → per-config → per-seed
    raw_results = {}  # test_id -> config_name -> [per-seed metric dict]
    agg_results = {}  # test_id -> config_name -> aggregated metrics

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
        print(f"Reference items: {len(test_case['reference_items'])} "
              f"(actions/questions/risks split: "
              f"{sum(1 for i in test_case['reference_items'] if i['kind']=='action')}/"
              f"{sum(1 for i in test_case['reference_items'] if i['kind']=='question')}/"
              f"{sum(1 for i in test_case['reference_items'] if i['kind']=='risk')})")

        for config_name, run_fn in CONFIGS.items():
            seed_metrics = []
            for seed in range(N_SEEDS):
                print(f"  [{config_name}] seed {seed + 1}/{N_SEEDS}...", end=" ", flush=True)
                plan, usage, extras = run_fn(test_case, playbook, seed)
                judgment, grade_usage = grade(plan, reference)
                # Add grader usage to the run's usage
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

    # Print summary
    print()
    summary_text = print_summary(agg_results, N_SEEDS)
    summary_text += (
        f"\n\nWall-clock: {total_time}s    "
        f"Total cost: ${total_cost:.4f}    "
        f"Runs: {len(CONFIGS) * len(TEST_CASES) * N_SEEDS}\n"
    )

    # Save artifacts
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(f"{ARTIFACTS_DIR}/eval_results.json", "w") as fh:
        json.dump({
            "config": {
                "model": MODEL,
                "temperature_planner": DEFAULT_TEMPERATURE,
                "temperature_grader": 0.0,
                "n_seeds": N_SEEDS,
                "configs": list(CONFIGS.keys()),
                "test_cases": [t["id"] for t in TEST_CASES],
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
                "total_runs": len(CONFIGS) * len(TEST_CASES) * N_SEEDS,
            },
        }, fh, indent=2)
    with open(f"{ARTIFACTS_DIR}/eval_summary.txt", "w") as fh:
        fh.write(summary_text)

    print(f"\nResults saved to:")
    print(f"  • {ARTIFACTS_DIR}/eval_results.json  (full nested data)")
    print(f"  • {ARTIFACTS_DIR}/eval_summary.txt   (human-readable tables)")


if __name__ == "__main__":
    main()
