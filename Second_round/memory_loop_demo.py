"""
memory_loop_demo.py
-------------------
Builds a per-client memory layer for an ops agent serving HELIX LABS,
a fictional Series A biotech startup.

The training loop accumulates Helix-specific knowledge across 5 different
ops task types (vendor invoice, customer onboarding, intl contractor,
advisor setup, customer dispute). Each task type touches different
sections of company knowledge; the curator stitches lessons into a
structured playbook organized by category.

This file is now training-only: it builds the playbook, snapshots each
episode, and tracks all token/latency/cost metrics during the build. The
held-out evaluation lives in eval_harness.py, which loads the saved
playbook and runs configurations × test cases × seeds for proper
statistical rigor.

Outputs (under ./artifacts/):
    memory_final.md          final playbook
    memory_ep{1..5}.md       per-episode snapshots
    training_metrics.json    tokens, latency, cost, lesson counts
"""

import json
import os
import re
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
MODEL = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.7  # introduces real variance across seeds
ARTIFACTS_DIR = "artifacts"

# Pricing per million tokens (USD). Adjust if pricing changes.
PRICE_INPUT_PER_M = 3.00
PRICE_OUTPUT_PER_M = 15.00

client = anthropic.Anthropic()


# =============================================================================
# FICTIONAL CLIENT — HELIX LABS canon
# =============================================================================
# None of this is in the model's training data; it must be learned through the
# loop. Helix is a Series A biotech (~15 employees):
#   - CEO Marcus approves > $5K spend; tech lead Priya reviews eng hires;
#     CS manager Daniel owns $25K–$100K ARR customers.
#   - Banking: Mercury for US; switched intl to Wise in Q2 2024.
#   - 2024 wire fraud -> ACH not wire, voice-verify any new payee bank info.
#   - MSA v3.2 (v3.1 had liability bug; v3.2 added explicit auto-renew opt-in
#     after 2024 Acme Bio dispute).
#   - IC agreement v2.1 (intl, includes W-8BEN-E + 30-day notice).
#   - Advisor agreement v1.4 (IP assignment added after 2024 patent dispute).
#   - Std advisor equity 0.05% / 12mo vesting; contractor equity excluded < 6mo
#     (per 2023 cap table cleanup).
#   - 2023 contractor misclassification -> strict 1099 vs W-2 review.
#   - HubSpot (CRM) / NetSuite (PO + finance) / HelloSign (contracts).
#   - Sales tax CA + NY only (per 2023 settlement).
#   - BioReagents = lab supplies vendor; Q3 2024 pricing dispute; Anna in AP.
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
# PROMPTS  (exported — imported by eval_harness.py)
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
def call(system, user, max_tokens=4096, temperature=DEFAULT_TEMPERATURE):
    """Make an Anthropic API call; return (text, usage_dict).

    usage_dict has keys:
      input_tokens, output_tokens, latency_s, cost_usd
    """
    t0 = time.time()
    r = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    latency = time.time() - t0
    in_tok = r.usage.input_tokens
    out_tok = r.usage.output_tokens
    cost = (in_tok / 1e6) * PRICE_INPUT_PER_M + (out_tok / 1e6) * PRICE_OUTPUT_PER_M
    return r.content[0].text, {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "latency_s": round(latency, 3),
        "cost_usd": round(cost, 6),
    }


def strip_fences(text):
    return re.sub(r"```(?:json|markdown)?\s*|\s*```", "", text).strip()


def extract_json(text, kind="object"):
    """Find the first balanced {...} or [...] in `text` and parse it."""
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
    """Parse a markdown playbook into {section_name: [bullet_lines, ...]}."""
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
    """Count playbook bullets (rough — lines starting with '-' or '*')."""
    return sum(
        1 for line in playbook_md.splitlines()
        if line.lstrip().startswith(("-", "*"))
    )


# =============================================================================
# AGENT ROLES  (exported — all return (result, usage))
# =============================================================================
def make_plan(message, playbook, temperature=DEFAULT_TEMPERATURE):
    """Working agent: produce ops plan. Returns (plan_dict, usage)."""
    user = (
        f"Helix playbook (accumulated Helix-specific knowledge):\n"
        f"{playbook or '(empty — no prior guidance)'}\n\n"
        f"Request from a Helix team member:\n{message}\n\n"
        f"Produce the ops plan as JSON now."
    )
    raw, usage = call(PLAN_SYSTEM, user, temperature=temperature)
    result = extract_json(raw, kind="object")
    if not result:
        print("  → make_plan: retrying with 8000 max_tokens after parse failure...")
        raw, retry_usage = call(PLAN_SYSTEM, user, max_tokens=8000, temperature=temperature)
        # accumulate usage on retry
        for k in ("input_tokens", "output_tokens", "latency_s", "cost_usd"):
            usage[k] += retry_usage[k]
        result = extract_json(raw, kind="object")
    plan = result or {"actions": [], "questions": [], "risks": []}
    # Defensive shape coercion
    for k in ("actions", "questions", "risks"):
        if not isinstance(plan.get(k), list):
            plan[k] = []
    return plan, usage


def review_and_extract_lessons(message, draft, reference, temperature=DEFAULT_TEMPERATURE):
    """Reviewer: identify gaps, write category-tagged lessons. Returns (lessons, usage)."""
    user = (
        f"Helix request:\n{message}\n\n"
        f"Draft plan:\n{json.dumps(draft, indent=2)}\n\n"
        f"Reference of thorough Helix-specific coverage:\n{json.dumps(reference, indent=2)}\n\n"
        f"Return the JSON array of category-tagged lessons now."
    )
    raw, usage = call(REVIEW_SYSTEM, user, temperature=temperature)
    result = extract_json(raw, kind="array")
    return (result or []), usage


def curate(playbook, new_lessons, temperature=DEFAULT_TEMPERATURE):
    """Curator: merge lessons into structured markdown playbook. Returns (md, usage)."""
    if not new_lessons:
        return playbook, {"input_tokens": 0, "output_tokens": 0, "latency_s": 0.0, "cost_usd": 0.0}
    user = (
        f"Current playbook:\n{playbook or '(empty)'}\n\n"
        f"New lessons to integrate:\n{json.dumps(new_lessons, indent=2)}\n\n"
        f"Return the updated markdown playbook now."
    )
    raw, usage = call(CURATE_SYSTEM, user, temperature=temperature)
    return strip_fences(raw), usage


def grade(draft, reference, temperature=0.0):
    """Judge: how much of `reference` does `draft` cover? Returns (judgement_dict, usage).

    Grader uses temperature=0 by default for stable judgements across seeds.
    """
    user = (
        f"Reference plan (thorough Helix-specific coverage):\n"
        f"{json.dumps(reference, indent=2)}\n\n"
        f"Draft plan to evaluate:\n{json.dumps(draft, indent=2)}\n\n"
        f"Return the JSON judgment now."
    )
    raw, usage = call(GRADE_SYSTEM, user, max_tokens=2000, temperature=temperature)
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


def select_skills(message, playbook_md, temperature=DEFAULT_TEMPERATURE):
    """Router: pick relevant sections. Returns (slimmed_md, chosen_names, usage).

    Falls back to full playbook if routing yields nothing or there's only 1 section.
    """
    no_usage = {"input_tokens": 0, "output_tokens": 0, "latency_s": 0.0, "cost_usd": 0.0}
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
    raw, usage = call(ROUTER_SYSTEM, user, max_tokens=500, temperature=temperature)
    chosen = extract_json(raw, kind="array") or []
    chosen = [s for s in chosen if s in sections]
    if not chosen:
        return playbook_md, names, usage  # safe fallback
    slimmed = "\n\n".join(f"## {n}\n" + "\n".join(sections[n]) for n in chosen)
    return slimmed, chosen, usage


# =============================================================================
# TRAINING LOOP  (saves all artifacts)
# =============================================================================
def main():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    playbook = ""
    episode_metrics = []
    cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "latency_s": 0.0, "cost_usd": 0.0}

    print("=" * 72)
    print("HELIX LABS OPS AGENT — TRAINING LOOP")
    print("=" * 72)
    print(f"Model: {MODEL}  |  Temperature: {DEFAULT_TEMPERATURE}")
    print(f"Cases: {len(CASES)}  |  Artifacts dir: {ARTIFACTS_DIR}/")

    for ep, c in enumerate(CASES, 1):
        ep_t0 = time.time()
        print(f"\n{'─' * 72}")
        print(f"Episode {ep} [{c['id']}]: {c['summary']}")
        print(f"{'─' * 72}")

        ep_usage = {"input_tokens": 0, "output_tokens": 0, "latency_s": 0.0, "cost_usd": 0.0}

        # Plan
        draft, plan_usage = make_plan(c["message"], playbook)
        for k in ep_usage:
            ep_usage[k] += plan_usage[k]

        # Review
        lessons, rev_usage = review_and_extract_lessons(c["message"], draft, c["reference"])
        for k in ep_usage:
            ep_usage[k] += rev_usage[k]

        print(f"\nReviewer flagged {len(lessons)} Helix-specific gap(s):")
        for l in lessons:
            cat = l.get("category", "Other") if isinstance(l, dict) else "Other"
            txt = l.get("lesson", "") if isinstance(l, dict) else str(l)
            print(f"  • [{cat}] {txt}")

        # Curate
        playbook, cur_usage = curate(playbook, lessons)
        for k in ep_usage:
            ep_usage[k] += cur_usage[k]

        with open(f"{ARTIFACTS_DIR}/memory_ep{ep}.md", "w") as fh:
            fh.write(playbook)

        ep_wall = round(time.time() - ep_t0, 2)
        n_sections = len(parse_sections(playbook))
        n_bullets = count_bullets(playbook)
        playbook_chars = len(playbook)

        print(f"\nEpisode {ep} metrics:")
        print(f"  Lessons added : {len(lessons)}")
        print(f"  Playbook now  : {n_sections} sections, {n_bullets} bullets, {playbook_chars} chars")
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

    # Save final playbook
    with open(f"{ARTIFACTS_DIR}/memory_final.md", "w") as fh:
        fh.write(playbook)

    # Save training metrics
    training_metrics = {
        "model": MODEL,
        "temperature": DEFAULT_TEMPERATURE,
        "n_episodes": len(CASES),
        "final_playbook_sections": len(parse_sections(playbook)),
        "final_playbook_bullets": count_bullets(playbook),
        "final_playbook_chars": len(playbook),
        "cumulative_usage": cumulative_usage,
        "per_episode": episode_metrics,
    }
    with open(f"{ARTIFACTS_DIR}/training_metrics.json", "w") as fh:
        json.dump(training_metrics, fh, indent=2)

    # Headline
    print("\n" + "=" * 72)
    print("TRAINING COMPLETE")
    print("=" * 72)
    print(f"  Final playbook: {len(parse_sections(playbook))} sections, "
          f"{count_bullets(playbook)} bullets")
    print(f"  Total tokens  : {cumulative_usage['input_tokens']:,} in, "
          f"{cumulative_usage['output_tokens']:,} out")
    print(f"  Total cost    : ${cumulative_usage['cost_usd']:.4f}")
    print(f"  Total time    : {cumulative_usage['latency_s']:.1f}s in API")
    print(f"\nArtifacts saved to ./{ARTIFACTS_DIR}/")
    print(f"  • memory_final.md")
    print(f"  • memory_ep1.md … memory_ep{len(CASES)}.md")
    print(f"  • training_metrics.json")
    print("\nNext: run `python eval_harness.py` to evaluate configurations.")


if __name__ == "__main__":
    main()
