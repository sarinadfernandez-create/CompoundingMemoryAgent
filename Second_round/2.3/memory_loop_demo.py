"""
memory_loop_demo.py  (v3 — cascade-ready)
------------------------------------------
Builds a per-client memory layer for an ops agent serving HELIX LABS.

V3 ADDITION: per-role model selection. Curator and router default to Haiku
(cheaper, simpler tasks), while planner and reviewer stay on Sonnet (quality
matters most). Edit the MODEL_* constants below to experiment.

USAGE
-----
    python memory_loop_demo.py --iter v3_cascade

Each iteration writes to ./artifacts/{iter}/. Per-role token/cost usage is
tracked separately in training_metrics.json so you can see where the cost
shifts under cascade.

Outputs:
    artifacts/{iter}/memory_final.md
    artifacts/{iter}/memory_ep{1..5}.md
    artifacts/{iter}/training_metrics.json
"""

import argparse
import json
import os
import random
import re
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------------------
# MODELS  (edit these to toggle cascade)
# -----------------------------------------------------------------------------
MODEL_OPUS = "claude-opus-4-7"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5"

# CASCADE config — which model each role uses
MODEL_PLANNER = MODEL_SONNET      # Working agent: quality matters most
MODEL_REVIEWER = MODEL_SONNET     # Reviewer: needs to identify subtle gaps
MODEL_CURATOR = MODEL_HAIKU       # Curator: just merges text — Haiku is fine
MODEL_GRADER = MODEL_SONNET       # Grader: keep consistent for stable scoring
MODEL_ROUTER = MODEL_HAIKU        # Router: simple classification task

# Backwards-compat for any code still referencing MODEL
MODEL = MODEL_SONNET

DEFAULT_TEMPERATURE = 0.7

# Pricing per million tokens (USD). Keep in sync with Anthropic's pricing page.
PRICING = {
    MODEL_OPUS:   (15.00, 75.00),
    MODEL_SONNET:  (3.00, 15.00),
    MODEL_HAIKU:   (1.00,  5.00),
}

client = anthropic.Anthropic()


# =============================================================================
# HELIX LABS canon (training cases) — unchanged from v2
# =============================================================================
CASES = [
    {
        "id": "T1",
        "summary": "Vendor invoice — BioReagents asking for payment to a new bank account",
        "message": (
            "Got an invoice from BioReagents Inc for $8,400 in lab supplies, "
            "dated 30 days ago. They emailed asking for immediate payment to a "
            "new bank account they sent over. Should we pay?"
        ),
        "reference": {
            "actions": [
                "Pay via ACH from Helix's Mercury business account — NOT wire (Helix policy after the 2024 wire fraud incident)",
                "Voice-verify the new bank account details with BioReagents' AP contact Anna at the known phone number — never the contact info on the invoice",
                "Match the invoice against the open PO in NetSuite before payment (Helix policy after the Q3 2024 BioReagents pricing dispute over contract rates)",
                "Route to Marcus for CEO approval — any spend over the $5K threshold requires his sign-off",
            ],
            "questions": [
                "Is this against an existing PO or net-new spend? Required for NetSuite matching",
                "Was the bank-change request out-of-band verified with the known contact?",
            ],
            "risks": [
                "Bank account change requests are a common fraud vector — Helix policy mandates voice verification on a known channel",
                "BioReagents had a pricing dispute with Helix in Q3 2024 — verify line items against contracted rates before approval",
            ],
        },
    },
    {
        "id": "T2",
        "summary": "New customer onboarding — Beacon Labs at $40K ARR",
        "message": (
            "We just signed Beacon Labs — $40K/yr ARR, biotech in the Bay Area. "
            "Get them onboarded and billed."
        ),
        "reference": {
            "actions": [
                "Use Helix's MSA template v3.2 — NOT v3.1 (v3.1 had the limitation-of-liability bug; v3.2 added explicit opt-in auto-renewal language after the 2024 Acme Bio dispute)",
                "Assign Daniel as CS owner — Helix routes $25K–$100K ARR to him (under $25K → Priya, over $100K → Marcus is directly involved)",
                "Create the customer record in HubSpot and sync to NetSuite for billing",
                "Set up payment via the Mercury customer ACH portal",
                "Schedule the mandatory 14-day customer success check-in (Helix's churn-mitigation policy added after the 2024 first-month churn issue)",
            ],
            "questions": [
                "Will Beacon need SAML SSO? Helix only enables it for $50K+ ARR customers",
                "Data residency requirements? Default is US-East",
            ],
            "risks": [
                "Sales tax: Helix only collects in CA and NY per the 2023 settlement — confirm Beacon's billing state and any nexus implications",
            ],
        },
    },
    {
        "id": "T3",
        "summary": "International contractor — Indian engineer, 3 months",
        "message": (
            "Marcus wants to bring on a contract engineer from India for 3 "
            "months at $8K/month. Set up the hire."
        ),
        "reference": {
            "actions": [
                "Use Helix's IC agreement template v2.1 — the international version that includes W-8BEN-E provisions and the 30-day notice clause Helix's legal team requires",
                "Pay via Wise — NOT Mercury (Helix switched international payments to Wise in Q2 2024 due to Mercury's intl transfer fees)",
                "Collect W-8BEN-E before the first payment (Helix policy — withholding-risk avoidance)",
                "Loop in Priya (tech lead) to review the engineer's background before contract signing",
                "Do NOT include equity in the agreement — Helix's contractor equity policy excludes anyone under 6 months (set after the 2023 cap table cleanup)",
            ],
            "questions": [
                "Will the contractor need GitHub or customer-data access? If yes, BAA + security training required",
                "Has Marcus explicitly approved? Any hire deviating from the standard contractor template needs his sign-off",
            ],
            "risks": [
                "1099 vs W-2 misclassification — Helix had a misclassification issue in 2023, so independence criteria must be documented",
                "India FEMA / RBI reporting on the contractor's side — Helix doesn't manage but should communicate the issue",
            ],
        },
    },
    {
        "id": "T4",
        "summary": "Advisor setup — Dr. Anita Sharma, US-based, recurring",
        "message": (
            "Bringing on Dr. Anita Sharma as a scientific advisor — $2,500/month "
            "for 12 months, US-based. Set up the agreement and payments."
        ),
        "reference": {
            "actions": [
                "Use Helix's advisor agreement template v1.4 — includes the IP assignment language Marcus added after the 2024 patent dispute",
                "Set up the recurring monthly ACH via Mercury (Helix's preferred rail for US recurring)",
                "Issue the standard advisor equity grant: 0.05% vesting over 12 months — Helix's default for SAB members",
                "Flag for 1099-NEC issuance at year end ($30K total well over the $600 threshold)",
            ],
            "questions": [
                "Does Dr. Sharma hold conflicting advisor positions at other biotechs? Helix requires non-compete disclosure per the advisor agreement",
                "Will she access confidential research? If yes, the separate IP/confidentiality addendum (not the default v1.4) is required",
            ],
            "risks": [
                "1099 vs W-2 classification — advisors are 1099 only if truly independent (Helix's 2023 misclassification issue applies)",
            ],
        },
    },
    {
        "id": "T5",
        "summary": "Customer dispute — Beacon claiming no agreement to auto-renewal",
        "message": (
            "Beacon Labs (the customer we onboarded last month) is disputing "
            "their first invoice — they claim they didn't agree to the "
            "auto-renewal clause. How do we handle?"
        ),
        "reference": {
            "actions": [
                "Pull Beacon's signed MSA from Helix's HelloSign archive",
                "Confirm the MSA version is v3.2 (not v3.1) — v3.2 has the explicit opt-in auto-renewal language that v3.1 lacked",
                "Escalate to Daniel as Beacon's CS owner (per Helix's $25K–$100K ARR routing)",
                "If the dispute is valid, issue refund or credit via Mercury and log under the customer issues tracker required for board reporting",
            ],
            "questions": [
                "Was the MSA signed by a VP+ at Beacon? Helix requires VP-level signature authority on MSAs",
                "Has this been logged in Helix's customer issues tracker? Board KPI reports require it",
            ],
            "risks": [
                "Helix's board flagged customer disputes as a KPI in Q1 2025 — must be resolved within 14 days",
                "If the MSA turns out to be v3.1, the auto-renewal clause is less defensible — escalate to legal",
            ],
        },
    },
]


# =============================================================================
# PROMPTS (unchanged)
# =============================================================================
PLAN_SYSTEM = (
    "You are an internal ops assistant for Helix Labs, a Series A biotech "
    "startup. Each request comes from a Helix team member and must be handled "
    "in a way that's consistent with Helix's specific policies, vendors, "
    "templates, and history. Use any guidance from your playbook (accumulated "
    "Helix-specific knowledge) to produce a thorough plan with actions, open "
    "questions, and risks. Be concrete — reference Helix's actual tools, "
    "templates, people, and rules where the playbook supplies them.\n\n"
    "Return ONLY valid JSON in this exact shape:\n"
    '{"actions": ["..."], "questions": ["..."], "risks": ["..."]}\n'
    "No prose, no code fences."
)

REVIEW_SYSTEM = (
    "You are a quality reviewer for an ops agent serving Helix Labs. You "
    "compare a draft plan against a reference of what thorough Helix-specific "
    "coverage requires, and identify items in the reference that are MISSING, "
    "WEAK, or WRONGLY handled. For each gap, write ONE concise lesson the "
    "agent should remember going forward — phrased as a GENERAL Helix-specific "
    "rule (about Helix's policy, vendor, template, threshold, history), not "
    "specific to this one task. Tag each lesson with a short category label "
    "such as 'Banking & Payments', 'Contract Templates', 'Approvals & "
    "Routing', 'Vendor & Customer History', 'Compliance', 'Equity & Cap "
    "Table'. Reuse existing category names when they fit; introduce a new "
    "label only when nothing existing applies.\n\n"
    "Return ONLY a JSON array of objects: "
    '[{"category": "...", "lesson": "..."}, ...]. '
    "Aim for 1-4 lessons total. No prose, no code fences."
)

CURATE_SYSTEM = (
    "You are the playbook curator for Helix Labs's ops agent. You maintain a "
    "structured markdown playbook organized by category. When new lessons "
    "arrive, you:\n"
    "  (1) consolidate them into existing sections when they belong there,\n"
    "  (2) CREATE a new ## section when a lesson's category isn't yet a section,\n"
    "  (3) merge or deduplicate overlapping bullets,\n"
    "  (4) keep each bullet to ONE line and phrased as a general Helix-specific rule.\n"
    "Preserve all useful prior guidance — don't drop existing bullets unless "
    "you are explicitly consolidating duplicates.\n\n"
    "Return ONLY the updated playbook as markdown with ## section headings. "
    "No prose outside the playbook, no code fences."
)

GRADE_SYSTEM = (
    "You are evaluating how well a draft ops plan covers a reference of what "
    "thorough Helix-specific coverage requires. For each reference item across "
    "actions, questions, and risks, decide whether the draft covers it (loose "
    "match — synonyms, paraphrases, and slightly broader phrasings count as "
    "covered, BUT generic guidance does not satisfy a Helix-SPECIFIC reference "
    "item — e.g. 'use a payment processor' does NOT cover 'use Wise for "
    "international per Helix's Q2 2024 switch'). Every reference item must "
    "appear in EXACTLY ONE of 'covered' or 'missing'.\n\n"
    "Return ONLY JSON with this shape:\n"
    '{"covered": [{"kind": "action|question|risk", "ref_item": "..."}, ...], '
    '"missing": [{"kind": "action|question|risk", "ref_item": "..."}, ...]}\n'
    "No prose, no code fences."
)

ROUTER_SYSTEM = (
    "You are a skill router. Given an incoming ops task at Helix Labs and a "
    "list of available skill sections (each is a body of accumulated "
    "Helix-specific guidance), return ONLY the subset of sections relevant to "
    "handling this task. Include every section that meaningfully applies — "
    "broad coverage matters since tasks often cross multiple knowledge areas. "
    "Omit sections that don't apply at all.\n\n"
    "Return ONLY a JSON array of section names as strings. No prose, no code fences."
)


# =============================================================================
# LOW-LEVEL HELPERS  (exported)
# =============================================================================
def call(system, user, max_tokens=4096, temperature=DEFAULT_TEMPERATURE,
         model=None, max_retries=6):
    """Make an Anthropic API call with exponential backoff on transient errors.
    Returns (text, usage) where usage includes model, tokens, cost, latency.
    """
    model = model or MODEL_SONNET
    if model not in PRICING:
        raise ValueError(f"Unknown model {model!r}. Add pricing to PRICING dict.")
    price_in, price_out = PRICING[model]

    delay = 2.0
    for attempt in range(max_retries):
        try:
            t0 = time.time()
            r = client.messages.create(
                model=model, max_tokens=max_tokens, temperature=temperature,
                system=system, messages=[{"role": "user", "content": user}],
            )
            latency = time.time() - t0
            in_tok = r.usage.input_tokens
            out_tok = r.usage.output_tokens
            cost = (in_tok / 1e6) * price_in + (out_tok / 1e6) * price_out
            return r.content[0].text, {
                "model": model,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "latency_s": round(latency, 3),
                "cost_usd": round(cost, 6),
            }
        except (anthropic.OverloadedError,
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.InternalServerError) as e:
            if attempt == max_retries - 1:
                print(f"  ✗ API error after {max_retries} retries: {type(e).__name__}")
                raise
            wait = min(delay * (2 ** attempt) + random.uniform(0, 1), 60.0)
            print(f"  ⚠ {type(e).__name__} on {model} — backing off {wait:.1f}s "
                  f"(retry {attempt + 1}/{max_retries})")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def strip_fences(text):
    return re.sub(r"```(?:json|markdown)?\s*|\s*```", "", text).strip()


def extract_json(text, kind="object"):
    text = strip_fences(text)
    open_c, close_c = ("{", "}") if kind == "object" else ("[", "]")
    start = text.find(open_c)
    if start == -1:
        print(f"  ⚠ extract_json: no opening '{open_c}' in response")
        print(f"    raw start: {text[:200]!r}")
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_c:
            depth += 1
        elif text[i] == close_c:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as e:
                    print(f"  ⚠ extract_json: JSON parse error: {e}")
                    return None
    print(f"  ⚠ extract_json: response truncated before closing '{close_c}' "
          "(likely hit max_tokens)")
    return None


def parse_sections(playbook_md):
    sections = {}
    current = None
    for line in playbook_md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            sections[current] = []
        elif current is not None and line.strip():
            sections[current].append(line)
    return sections


def count_bullets(playbook_md):
    return sum(
        1 for line in playbook_md.splitlines()
        if line.lstrip().startswith(("-", "*"))
    )


# =============================================================================
# AGENT ROLES — each accepts a `model` override (defaults to its MODEL_* constant)
# =============================================================================
def make_plan(message, playbook, temperature=DEFAULT_TEMPERATURE, model=None):
    model = model or MODEL_PLANNER
    user = (
        f"Helix playbook (accumulated Helix-specific knowledge):\n"
        f"{playbook or '(empty — no prior guidance)'}\n\n"
        f"Request from a Helix team member:\n{message}\n\n"
        f"Produce the ops plan as JSON now."
    )
    raw, usage = call(PLAN_SYSTEM, user, temperature=temperature, model=model)
    result = extract_json(raw, kind="object")
    if not result:
        print("  → make_plan: retrying with 8000 max_tokens after parse failure...")
        raw, retry_usage = call(PLAN_SYSTEM, user, max_tokens=8000,
                                temperature=temperature, model=model)
        for k in ("input_tokens", "output_tokens", "latency_s", "cost_usd"):
            usage[k] += retry_usage[k]
        result = extract_json(raw, kind="object")
    plan = result or {"actions": [], "questions": [], "risks": []}
    for k in ("actions", "questions", "risks"):
        if not isinstance(plan.get(k), list):
            plan[k] = []
    return plan, usage


def review_and_extract_lessons(message, draft, reference,
                                temperature=DEFAULT_TEMPERATURE, model=None):
    model = model or MODEL_REVIEWER
    user = (
        f"Helix request:\n{message}\n\n"
        f"Draft plan:\n{json.dumps(draft, indent=2)}\n\n"
        f"Reference of thorough Helix-specific coverage:\n{json.dumps(reference, indent=2)}\n\n"
        f"Return the JSON array of category-tagged lessons now."
    )
    raw, usage = call(REVIEW_SYSTEM, user, temperature=temperature, model=model)
    result = extract_json(raw, kind="array")
    return (result or []), usage


def curate(playbook, new_lessons, temperature=DEFAULT_TEMPERATURE, model=None):
    model = model or MODEL_CURATOR
    if not new_lessons:
        return playbook, {"model": model, "input_tokens": 0, "output_tokens": 0,
                          "latency_s": 0.0, "cost_usd": 0.0}
    user = (
        f"Current playbook:\n{playbook or '(empty)'}\n\n"
        f"New lessons to integrate:\n{json.dumps(new_lessons, indent=2)}\n\n"
        f"Return the updated markdown playbook now."
    )
    raw, usage = call(CURATE_SYSTEM, user, temperature=temperature, model=model)
    return strip_fences(raw), usage


def grade(draft, reference, temperature=0.0, model=None):
    model = model or MODEL_GRADER
    user = (
        f"Reference plan (thorough Helix-specific coverage):\n"
        f"{json.dumps(reference, indent=2)}\n\n"
        f"Draft plan to evaluate:\n{json.dumps(draft, indent=2)}\n\n"
        f"Return the JSON judgment now."
    )
    raw, usage = call(GRADE_SYSTEM, user, max_tokens=2000,
                      temperature=temperature, model=model)
    result = extract_json(raw, kind="object")
    if not result:
        return {"covered": [], "missing": [], "recall": 0.0}, usage
    covered = result.get("covered", []) or []
    missing = result.get("missing", []) or []
    total = len(covered) + len(missing)
    return {
        "covered": covered,
        "missing": missing,
        "recall": (len(covered) / total) if total else 0.0,
    }, usage


def select_skills(message, playbook_md, temperature=DEFAULT_TEMPERATURE, model=None):
    model = model or MODEL_ROUTER
    no_usage = {"model": model, "input_tokens": 0, "output_tokens": 0,
                "latency_s": 0.0, "cost_usd": 0.0}
    if not playbook_md:
        return "", [], no_usage
    sections = parse_sections(playbook_md)
    names = list(sections.keys())
    if len(names) <= 1:
        return playbook_md, names, no_usage
    user = (
        f"Helix task:\n{message}\n\n"
        f"Available skill sections:\n"
        + "\n".join(f"- {n}" for n in names)
        + "\n\nReturn the JSON array of section names relevant to this task now."
    )
    raw, usage = call(ROUTER_SYSTEM, user, max_tokens=500,
                      temperature=temperature, model=model)
    chosen = extract_json(raw, kind="array") or []
    chosen = [s for s in chosen if s in sections]
    if not chosen:
        return playbook_md, names, usage
    slimmed = "\n\n".join(f"## {n}\n" + "\n".join(sections[n]) for n in chosen)
    return slimmed, chosen, usage


# =============================================================================
# TRAINING LOOP
# =============================================================================
def parse_args():
    p = argparse.ArgumentParser(description="Train Helix Labs memory playbook.")
    p.add_argument("--iter", required=True,
                   help="Iteration name (e.g., 'v3_cascade'). "
                        "Artifacts go to ./artifacts/{iter}/")
    return p.parse_args()


def add_role_usage(role_totals, role_name, usage):
    """Accumulate per-role usage including model and dollar cost."""
    if role_name not in role_totals:
        role_totals[role_name] = {
            "model": usage.get("model"),
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_s": 0.0,
            "cost_usd": 0.0,
            "n_calls": 0,
        }
    role_totals[role_name]["input_tokens"] += usage["input_tokens"]
    role_totals[role_name]["output_tokens"] += usage["output_tokens"]
    role_totals[role_name]["latency_s"] += usage["latency_s"]
    role_totals[role_name]["cost_usd"] += usage["cost_usd"]
    role_totals[role_name]["n_calls"] += 1


def main():
    args = parse_args()
    artifacts_dir = f"artifacts/{args.iter}"
    os.makedirs(artifacts_dir, exist_ok=True)

    playbook = ""
    episode_metrics = []
    cumulative_usage = {"input_tokens": 0, "output_tokens": 0,
                        "latency_s": 0.0, "cost_usd": 0.0}
    role_totals = {}  # role_name -> {model, tokens, cost, n_calls}

    print("=" * 72)
    print(f"HELIX LABS OPS AGENT — TRAINING  (iter: {args.iter})")
    print("=" * 72)
    print(f"Cases: {len(CASES)}  |  Artifacts: {artifacts_dir}/")
    print(f"Models:")
    print(f"  Planner  : {MODEL_PLANNER}")
    print(f"  Reviewer : {MODEL_REVIEWER}")
    print(f"  Curator  : {MODEL_CURATOR}")
    print(f"  Router   : {MODEL_ROUTER}  (not used in training)")
    print(f"  Grader   : {MODEL_GRADER}  (not used in training)")

    for ep, c in enumerate(CASES, 1):
        ep_t0 = time.time()
        print(f"\n{'─' * 72}")
        print(f"Episode {ep} [{c['id']}]: {c['summary']}")
        print(f"{'─' * 72}")

        ep_usage = {"input_tokens": 0, "output_tokens": 0,
                    "latency_s": 0.0, "cost_usd": 0.0}

        draft, plan_usage = make_plan(c["message"], playbook)
        add_role_usage(role_totals, "planner", plan_usage)
        for k in ep_usage:
            ep_usage[k] += plan_usage[k]

        lessons, rev_usage = review_and_extract_lessons(c["message"], draft, c["reference"])
        add_role_usage(role_totals, "reviewer", rev_usage)
        for k in ep_usage:
            ep_usage[k] += rev_usage[k]

        print(f"\nReviewer flagged {len(lessons)} Helix-specific gap(s):")
        for l in lessons:
            cat = l.get("category", "Other") if isinstance(l, dict) else "Other"
            txt = l.get("lesson", "") if isinstance(l, dict) else str(l)
            print(f"  • [{cat}] {txt}")

        playbook, cur_usage = curate(playbook, lessons)
        add_role_usage(role_totals, "curator", cur_usage)
        for k in ep_usage:
            ep_usage[k] += cur_usage[k]

        with open(f"{artifacts_dir}/memory_ep{ep}.md", "w") as fh:
            fh.write(playbook)

        ep_wall = round(time.time() - ep_t0, 2)
        n_sections = len(parse_sections(playbook))
        n_bullets = count_bullets(playbook)
        playbook_chars = len(playbook)

        print(f"\nEpisode {ep} metrics:")
        print(f"  Lessons added : {len(lessons)}")
        print(f"  Playbook now  : {n_sections} sections, {n_bullets} bullets, "
              f"{playbook_chars} chars")
        print(f"  Tokens (in/out): {ep_usage['input_tokens']:,} / {ep_usage['output_tokens']:,}")
        print(f"  Cost          : ${ep_usage['cost_usd']:.4f}")
        print(f"  Wall-clock    : {ep_wall}s")

        episode_metrics.append({
            "episode": ep,
            "case_id": c["id"],
            "summary": c["summary"],
            "lessons_added": len(lessons),
            "playbook_sections": n_sections,
            "playbook_bullets": n_bullets,
            "playbook_chars": playbook_chars,
            "usage": ep_usage,
            "wall_clock_s": ep_wall,
        })
        for k in cumulative_usage:
            cumulative_usage[k] += ep_usage[k]

    with open(f"{artifacts_dir}/memory_final.md", "w") as fh:
        fh.write(playbook)

    training_metrics = {
        "iter": args.iter,
        "models": {
            "planner": MODEL_PLANNER,
            "reviewer": MODEL_REVIEWER,
            "curator": MODEL_CURATOR,
        },
        "temperature": DEFAULT_TEMPERATURE,
        "n_episodes": len(CASES),
        "final_playbook_sections": len(parse_sections(playbook)),
        "final_playbook_bullets": count_bullets(playbook),
        "final_playbook_chars": len(playbook),
        "cumulative_usage": cumulative_usage,
        "per_role": role_totals,           # NEW: cascade visibility
        "per_episode": episode_metrics,
    }
    with open(f"{artifacts_dir}/training_metrics.json", "w") as fh:
        json.dump(training_metrics, fh, indent=2)

    print("\n" + "=" * 72)
    print(f"TRAINING COMPLETE  (iter: {args.iter})")
    print("=" * 72)
    print(f"  Playbook: {len(parse_sections(playbook))} sections, "
          f"{count_bullets(playbook)} bullets")
    print(f"\n  Per-role breakdown:")
    for role, totals in role_totals.items():
        print(f"    {role:<10} ({totals['model']:<25}) "
              f"{totals['n_calls']:>2} calls, "
              f"${totals['cost_usd']:.4f}")
    print(f"\n  Total cost    : ${cumulative_usage['cost_usd']:.4f}")
    print(f"  Total time    : {cumulative_usage['latency_s']:.1f}s in API")
    print(f"\nNext: python eval_harness.py --iter {args.iter}")


if __name__ == "__main__":
    main()
