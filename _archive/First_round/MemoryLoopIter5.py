"""
memory_loop_demo.py
-------------------
Per-client memory layer for an ops agent, demonstrated on a fictional company.

THE FRAMING
-----------
The agent is an internal ops assistant for HELIX LABS, a Series A biotech
startup. Across many ops tasks — vendor invoices, customer onboarding,
international contractor hires, advisor setup, customer disputes — it
accumulates HELIX-SPECIFIC knowledge that no general-purpose model could
possibly know cold: Helix's vendors, banking rails, template versions,
approval thresholds, history of past incidents, people-and-routing rules.

These are precisely the facts the base model has no prior on — they live
INSIDE the company. So the playbook's value should not just match the
base model's general knowledge, it should add a layer the model literally
could not have brought on its own.

CROSS-TASK KNOWLEDGE TRANSFER (THE NEW PART)
--------------------------------------------
The five training cases are DIFFERENT TASK TYPES. The held-out test is
designed to require facts learned across multiple of them simultaneously:

  Test case:  international advisor on a recurring contract, with new bank info
  Requires:   - Wise (not Mercury) for international payments  ← from T3 (intl contractor)
              - Advisor template v1.4 with IP language          ← from T4 (advisor)
              - Voice-verify bank changes (anti-fraud)          ← from T1 (invoice)
              - Marcus approval over $5K threshold              ← from T1 (invoice)
              - W-8BEN-E for non-US payee                       ← from T3 (intl contractor)

The skill router (added previously) selects which Helix-knowledge sections to
inject for each task — letting one agent fluently handle many task types by
pulling the right slice of accumulated client knowledge each time.
"""

import json
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
client = anthropic.Anthropic()


# =========================================================================
# FICTIONAL CLIENT — HELIX LABS
# =========================================================================
# Canon (none of this is in the model's training data; it must be learned):
#   - Series A biotech, ~15 employees
#   - CEO/founder Marcus — approves all spend > $5K, sets policies
#   - Tech lead Priya — reviews engineering / technical hires
#   - CS manager Daniel — handles $25K–$100K ARR customers
#   - Banking: Mercury for US, switched intl to Wise in Q2 2024 (fee reasons)
#   - 2024 wire-fraud incident -> ACH not wire policy, voice-verify bank changes
#   - MSA template v3.2 (v3.1 had liability bug; v3.2 added explicit auto-renew opt-in after 2024 Acme Bio dispute)
#   - IC agreement v2.1 (intl version, includes W-8BEN-E and 30-day notice)
#   - Advisor agreement v1.4 (added IP assignment after 2024 patent dispute)
#   - Standard advisor equity grant: 0.05% / 12 months
#   - Contractor equity NOT for < 6 months (set after 2023 cap table cleanup)
#   - 2023 contractor misclassification issue -> strict 1099 vs W-2 review
#   - HubSpot (CRM) / NetSuite (PO + finance) / HelloSign (contracts)
#   - Sales tax collected only in CA and NY (per 2023 settlement)
#   - BioReagents = lab supplies vendor with Q3 2024 pricing dispute; Anna in AP
# =========================================================================
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

# Held-out: deliberately constructed to require facts from T1 (bank verification,
# Marcus $5K threshold), T3 (Wise for intl, W-8BEN-E), and T4 (advisor template
# v1.4, recurring rails, 1099 logic). A generic model can't know Helix's
# specifics; the playbook should now stitch them together across task types.
TEST_CASE = {
    "id": "Test",
    "summary": "International advisor recurring setup (cross-task synthesis)",
    "message": (
        "Bringing on Dr. Rafael Costa as a scientific advisor — he's based in "
        "Brazil, $3,000/month for 12 months. He just sent over his new bank "
        "account details for payment. Set this up."
    ),
    "reference": {
        "actions": [
            "Use Helix's advisor agreement template v1.4 (from T4) with the international provisions from the IC template v2.1 — W-8BEN-E and 30-day notice — added as an addendum",
            "Pay via Wise, NOT Mercury — Helix's international payment policy (from T3); only US recurring goes through Mercury (from T4)",
            "Voice-verify the new bank account details with Dr. Costa on a known phone number — Helix's anti-fraud policy applies to ANY new payee bank info (from T1)",
            "Collect W-8BEN-E from Dr. Costa before the first payment (from T3)",
            "Apply the standard advisor equity grant — 0.05% vesting over 12 months (from T4) — but flag for Marcus since Helix has no precedent for international advisor equity",
            "Route to Marcus for approval — $36K total commitment is well above the $5K threshold (from T1)",
            "Flag for 1099-equivalent (or 1042-S) reporting at year end given non-US payee",
        ],
        "questions": [
            "Does Dr. Costa hold conflicting advisor positions at other biotechs? Standard non-compete disclosure per the advisor agreement (from T4)",
            "Has Priya reviewed his scientific background? Helix's standard for technical hires (from T3 pattern)",
            "Does Brazil's tax/labor regime affect 1099 vs W-2 classification logic? (extrapolated from T3 + T4 caution)",
        ],
        "risks": [
            "International payment fraud risk: voice-verification policy from T1 applies, especially for a first-time international payee",
            "Brazil's tax law may treat recurring advisor payments differently from US — Helix doesn't manage but should flag",
            "Helix has no precedent for international advisor equity — confirm with Marcus before issuing (1099-NEC vs 1042-S complications)",
        ],
    },
}


# =========================================================================
# PROMPTS
# =========================================================================
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


# =========================================================================
# LOW-LEVEL HELPERS
# =========================================================================
def call(system, user, max_tokens=4096):
    # 4096 default — Helix plans with the full playbook can be long.
    r = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return r.content[0].text


def strip_fences(text):
    return re.sub(r"```(?:json|markdown)?\s*|\s*```", "", text).strip()


def extract_json(text, kind="object"):
    """Find the first BALANCED {...} or [...] in `text` and parse it. If
    extraction or parsing fails, print a diagnostic so silent failures stop
    quietly returning empty defaults."""
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
                    print(f"    raw: {text[start:i + 1][:300]!r}")
                    return None
    print(f"  ⚠ extract_json: response truncated before closing '{close_c}' "
          "(likely hit max_tokens)")
    print(f"    raw end: {text[-200:]!r}")
    return None


# =========================================================================
# AGENT ROLES
# =========================================================================
def make_plan(message, playbook):
    """Working agent: produce an ops plan for Helix using whatever playbook
    exists. Retries with bigger token budget if first response truncates."""
    user = (f"Helix playbook (accumulated Helix-specific knowledge):\n"
            f"{playbook or '(empty — no prior guidance)'}\n\n"
            f"Request from a Helix team member:\n{message}\n\n"
            f"Produce the ops plan as JSON now.")
    raw = call(PLAN_SYSTEM, user)
    result = extract_json(raw, kind="object")
    if not result:
        print("  → make_plan: retrying with 8000 max_tokens after parse failure...")
        raw = call(PLAN_SYSTEM, user, max_tokens=8000)
        result = extract_json(raw, kind="object")
    return result or {"actions": [], "questions": [], "risks": []}


def review_and_extract_lessons(message, draft, reference):
    """Reviewer: compare draft vs reference, write category-tagged Helix lessons."""
    user = (f"Helix request:\n{message}\n\n"
            f"Draft plan:\n{json.dumps(draft, indent=2)}\n\n"
            f"Reference of thorough Helix-specific coverage:\n{json.dumps(reference, indent=2)}\n\n"
            f"Return the JSON array of category-tagged lessons now.")
    result = extract_json(call(REVIEW_SYSTEM, user), kind="array")
    return result or []


def curate(playbook, new_lessons):
    """Curator: merge new lessons into the structured markdown playbook."""
    if not new_lessons:
        return playbook
    user = (f"Current playbook:\n{playbook or '(empty)'}\n\n"
            f"New lessons to integrate:\n{json.dumps(new_lessons, indent=2)}\n\n"
            f"Return the updated markdown playbook now.")
    return strip_fences(call(CURATE_SYSTEM, user))


def grade(draft, reference):
    """Judge: how much of `reference` does `draft` cover? Returns dict with
    covered/missing item lists and recall ∈ [0,1]."""
    user = (f"Reference plan (thorough Helix-specific coverage):\n"
            f"{json.dumps(reference, indent=2)}\n\n"
            f"Draft plan to evaluate:\n{json.dumps(draft, indent=2)}\n\n"
            f"Return the JSON judgment now.")
    result = extract_json(call(GRADE_SYSTEM, user, max_tokens=2000), kind="object")
    if not result:
        return {"covered": [], "missing": [], "recall": 0.0}
    covered = result.get("covered", []) or []
    missing = result.get("missing", []) or []
    total = len(covered) + len(missing)
    return {
        "covered": covered,
        "missing": missing,
        "recall": (len(covered) / total) if total else 0.0,
    }


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


def select_skills(message, playbook_md):
    """Router: pick which playbook sections are relevant to this task. Returns
    (slimmed_playbook_md, chosen_section_names). If routing yields nothing or
    there's only one section, falls back to the full playbook for safety."""
    if not playbook_md:
        return "", []
    sections = parse_sections(playbook_md)
    names = list(sections.keys())
    if len(names) <= 1:
        return playbook_md, names
    user = (f"Helix task:\n{message}\n\n"
            f"Available skill sections:\n"
            + "\n".join(f"- {n}" for n in names)
            + "\n\nReturn the JSON array of section names relevant to this task now.")
    chosen = extract_json(call(ROUTER_SYSTEM, user, max_tokens=500), kind="array") or []
    chosen = [s for s in chosen if s in sections]
    if not chosen:
        return playbook_md, names           # safe fallback: full playbook
    slimmed = "\n\n".join(f"## {n}\n" + "\n".join(sections[n]) for n in chosen)
    return slimmed, chosen


# =========================================================================
# MAIN LOOP
# =========================================================================
def main():
    playbook = ""

    print("=" * 72)
    print("HELIX LABS OPS AGENT — accumulating client-specific knowledge")
    print("=" * 72)

    for ep, c in enumerate(CASES, 1):
        print(f"\n{'─' * 72}\nEpisode {ep} [{c['id']}]: {c['summary']}\n{'─' * 72}")
        draft = make_plan(c["message"], playbook)
        lessons = review_and_extract_lessons(c["message"], draft, c["reference"])

        print(f"\nReviewer flagged {len(lessons)} Helix-specific gap(s):")
        for l in lessons:
            cat = l.get("category", "Other") if isinstance(l, dict) else "Other"
            txt = l.get("lesson", "") if isinstance(l, dict) else str(l)
            print(f"  • [{cat}] {txt}")

        playbook = curate(playbook, lessons)

        with open(f"Iter5-memory_ep{ep}.md", "w") as fh:
            fh.write(playbook)

        print(f"\nPlaybook after episode {ep}:")
        print("─" * 72)
        print(playbook or "(still empty)")

    # ---------- Held-out cross-task test: COLD vs WARM with grading ------
    print("\n" + "=" * 72)
    print(f"HELD-OUT TEST — {TEST_CASE['summary']}")
    print("=" * 72)
    print(f"\nRequest:\n  {TEST_CASE['message']}\n")
    print("This test deliberately requires facts learned across multiple")
    print("earlier tasks: intl-payment policy (T3), advisor template (T4),")
    print("bank-verification policy (T1), Marcus approval threshold (T1).")

    # COLD
    print("\n" + "─" * 72)
    print("RUN 1: COLD  (no Helix playbook — model knows only generics)")
    print("─" * 72)
    cold_plan = make_plan(TEST_CASE["message"], "")
    print(json.dumps(cold_plan, indent=2))
    cold_g = grade(cold_plan, TEST_CASE["reference"])
    cold_total = len(cold_g["covered"]) + len(cold_g["missing"])
    print(f"\n  Coverage of Helix reference: {cold_g['recall']*100:.0f}% "
          f"({len(cold_g['covered'])}/{cold_total} items)")

    # WARM with routing
    print("\n" + "─" * 72)
    print("RUN 2: WARM  (self-built Helix playbook + skill routing)")
    print("─" * 72)
    slimmed, chosen = select_skills(TEST_CASE["message"], playbook)
    all_section_names = list(parse_sections(playbook).keys())
    print(f"\n  Router picked {len(chosen)} of {len(all_section_names)} skill sections:")
    for s in all_section_names:
        mark = "✓" if s in chosen else "·"
        print(f"    {mark} {s}")
    if playbook:
        saved = (1 - len(slimmed) / len(playbook)) * 100
        print(f"  Context: {len(playbook)} chars → {len(slimmed)} chars  "
              f"({saved:.0f}% reduction)")
    warm_plan = make_plan(TEST_CASE["message"], slimmed)
    print()
    print(json.dumps(warm_plan, indent=2))
    warm_g = grade(warm_plan, TEST_CASE["reference"])
    warm_total = len(warm_g["covered"]) + len(warm_g["missing"])
    print(f"\n  Coverage of Helix reference: {warm_g['recall']*100:.0f}% "
          f"({len(warm_g['covered'])}/{warm_total} items)")

    # Headline
    print("\n" + "=" * 72)
    print("QUANTIFIED IMPROVEMENT (held-out cross-task case, same model)")
    print("=" * 72)
    delta_pp = (warm_g["recall"] - cold_g["recall"]) * 100
    print(f"  Cold  : {cold_g['recall']*100:5.0f}%  (general LLM knowledge only)")
    print(f"  Warm  : {warm_g['recall']*100:5.0f}%  (general + accumulated Helix-specific facts)")
    print(f"  Δ     : {delta_pp:+5.0f} percentage points  (from learning across 5 cross-domain tasks)")
    if warm_g["missing"]:
        print("\n  What the warm plan still misses:")
        for m in warm_g["missing"]:
            print(f"    • [{m.get('kind','?')}] {m.get('ref_item','')}")

    with open("Iter5-memory.md", "w") as fh:
        fh.write(playbook)
    print("\nSaved final playbook to Iter5-memory.md (per-episode snapshots in Iter5-memory_ep1.md … Iter5-memory_ep5.md)")


if __name__ == "__main__":
    main()