"""
memory_loop_demo.py
-------------------
A demo of weight-free LEARNING + SELF-ORGANIZING memory on a substantive task.

THE TASK
--------
The agent is an onboarding specialist for new businesses — the kind of work
Naïve's primitives are built for: incorporation, banking, equity, KYC, tax,
compliance. For each customer message it produces a structured plan with three
parts: actions to take, open questions to ask, and risks to flag.

THE LEARNING LOOP (three agents, not one)
-----------------------------------------
  1) Working agent  — produces the onboarding plan, using whatever playbook
                      exists. Frozen model. No fine-tuning.
  2) Reviewer       — compares the draft to a reference of what thorough
                      coverage would include, and writes ONE crisp lesson per
                      gap, each tagged with a short category label.
  3) Curator        — merges new lessons into a structured markdown playbook.
                      When a tagged category isn't yet a section, it creates
                      one. This is how the playbook self-organizes.

WHAT TO WATCH
-------------
Not a curve. The artifact is memory.md. It starts empty. Each customer
surfaces a new dimension of the work — solo LLC → Incorporation + Banking,
cofounders raising → forces an Equity & cap table section, UK founder →
International / KYC, an existing CA LLC → Conversion / restructuring, already
operating with EU customers → Compliance & tax. By the end the playbook is a
multi-section document the agent built for itself: a generic "onboarding" task
decomposed into the actual sub-tasks of the work.

A held-out test customer at the end combines multiple wrinkles to see whether
the now-organized playbook helps produce a comprehensive cross-category plan
on a case the agent has never seen.

Setup:
    pip install anthropic python-dotenv
    echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
Run:
    python memory_loop_demo.py
Outputs:
    memory.md           — final self-organized playbook (the artifact)
    memory_ep{N}.md     — snapshot after each episode, so you can show the growth
"""

import json
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5"
client = anthropic.Anthropic()


# =========================================================================
# CUSTOMERS — each surfaces a NEW category of consideration. Reference plans
# describe what thorough coverage would include; the reviewer uses them to
# identify gaps in the agent's draft.
# =========================================================================
CUSTOMERS = [
    {
        "id": "C1",
        "summary": "Solo founder, simple DE LLC",
        "message": (
            "Hi, I'm starting a consulting business as a solo founder. "
            "I want to set up an LLC in Delaware. It's just me, working "
            "from home in NYC. Can you help me get set up?"
        ),
        "reference": {
            "actions": [
                "Form LLC in Delaware",
                "Obtain EIN from IRS",
                "Open a business bank account",
                "Set up a registered agent in DE",
            ],
            "questions": [
                "Desired LLC name and availability check",
                "Business mailing address (home OK, or separate?)",
                "Expected revenue and primary business activity",
            ],
            "risks": [
                "Single-member LLC defaults to disregarded entity for tax — confirm desired tax treatment",
                "DE LLC requires annual franchise tax and registered agent fee",
            ],
        },
    },
    {
        "id": "C2",
        "summary": "Two cofounders, planning angel round in ~2 months",
        "message": (
            "My cofounder and I are starting an AI startup. We want to "
            "incorporate properly because we're planning to raise an angel "
            "round in about 2 months. What do we need to set up?"
        ),
        "reference": {
            "actions": [
                "Incorporate as Delaware C-Corp",
                "Issue founder stock with vesting (4yr / 1yr cliff is standard)",
                "File 83(b) elections within 30 days of stock issuance",
                "Draft cofounder agreement and IP assignment",
                "Obtain EIN",
                "Open business bank account",
            ],
            "questions": [
                "Equity split between cofounders",
                "Vesting schedule preferences",
                "Anticipated size and timing of the angel round",
                "Any pre-existing IP that needs assigning to the company",
            ],
            "risks": [
                "83(b) election deadline is 30 days from stock issuance, no extensions — missing it means year-by-year taxation on appreciating equity",
                "C-Corp creates double taxation but is the expected structure for venture-backed companies",
                "Cap table cleanliness matters — investors will scrutinize",
            ],
        },
    },
    {
        "id": "C3",
        "summary": "UK citizen, no US presence yet",
        "message": (
            "I'm a UK citizen and I want to start a US company for my "
            "SaaS product. I don't have a US visa or US address yet. "
            "Can you help?"
        ),
        "reference": {
            "actions": [
                "Incorporate as Delaware C-Corp (no US citizenship required for ownership)",
                "Apply for EIN via Form SS-4 international procedure (no SSN needed but takes longer)",
                "Arrange US registered agent and a US virtual address",
                "Open business bank account at a non-resident-friendly bank (Mercury, Brex, etc.)",
            ],
            "questions": [
                "Plans to obtain an ITIN",
                "Will you hire US employees",
                "Where will you physically be working from",
                "Existing US bank or business relationships",
            ],
            "risks": [
                "Many US banks require physical presence or residency — Mercury / Brex / Wise are common non-resident workarounds",
                "US-UK tax treaty and double-taxation implications — recommend a cross-border tax advisor",
                "Selling to US customers can create sales tax nexus once thresholds are hit",
                "Physical work in the US is a separate visa question",
            ],
        },
    },
    {
        "id": "C4",
        "summary": "Existing CA LLC wants to redomicile to DE C-Corp before fundraising",
        "message": (
            "I have a California LLC I started two years ago. I want to "
            "convert to a Delaware C-Corp before fundraising. What do I "
            "need to do?"
        ),
        "reference": {
            "actions": [
                "Choose conversion structure (statutory conversion, F-reorganization, or merger)",
                "Form new Delaware C-Corp",
                "Execute conversion / merger / asset-transfer paperwork",
                "Dissolve or wind down the CA LLC if applicable",
                "Re-issue equity under the new structure with vesting and 83(b) considerations",
                "Coordinate final tax filings for the LLC and initial for the C-Corp",
                "Transfer contracts, IP, bank accounts, EIN where possible",
            ],
            "questions": [
                "Current equity holders and membership interests",
                "Existing assets, IP, contracts, and customers under the LLC",
                "Tax positions or NOLs to preserve",
                "Employees or contractors under the LLC",
            ],
            "risks": [
                "Tax treatment varies by structure — F-reorganization often preserves attributes; statutory conversion can be taxable",
                "Existing contracts may have anti-assignment clauses requiring counterparty consent",
                "Customers, bank accounts, and payment processors may need to be re-onboarded under the new entity",
                "California franchise tax and exit fees apply on dissolution",
            ],
        },
    },
    {
        "id": "C5",
        "summary": "Already operating informally, EU customers, ~$30k MRR",
        "message": (
            "We've been running our SaaS informally for a year — about "
            "$30k MRR with mostly EU customers. We've never properly "
            "incorporated. We're invoicing through personal Stripe. "
            "Need to get legitimate ASAP."
        ),
        "reference": {
            "actions": [
                "Incorporate (likely DE C-Corp given scale)",
                "Migrate Stripe from personal to business entity",
                "Set up invoicing with proper VAT handling for EU customers",
                "Register for VAT in EU jurisdictions over the threshold, or use the OSS scheme",
                "Backdated accounting and tax cleanup for the unincorporated year",
                "Review GDPR compliance for storing EU customer data",
            ],
            "questions": [
                "EU revenue broken out by country (for VAT thresholds)",
                "What customer data is stored and where",
                "Has prior revenue been reported on personal taxes",
                "Existing contracts that may need migration to the new entity",
                "Payment processor of choice going forward",
            ],
            "risks": [
                "Operating without an entity for a year creates personal tax and liability exposure — recommend a CPA review",
                "EU VAT non-compliance can result in fines and back-taxes",
                "GDPR violations carry significant penalties for handling EU personal data",
                "Migrating Stripe to a new entity can interrupt payments — plan a careful cutover",
            ],
        },
    },
]

# Held-out test combines several wrinkles seen separately above (international
# founder + already-taking-payments). A thorough plan should hit Incorporation,
# International / KYC, AND Compliance & tax categories simultaneously.
TEST_CUSTOMER = {
    "id": "Test",
    "summary": "Indian founder, already accepting wires from US clients",
    "message": (
        "I'm a software developer based in India. I want to start a US "
        "business for my consulting work, and I already have a few US "
        "clients who have been paying me directly via wire transfer over "
        "the past few months. I want to do this properly. Help me?"
    ),
}


# =========================================================================
# PROMPTS — three role-specific system prompts.
# =========================================================================
PLAN_SYSTEM = (
    "You are an onboarding specialist for a service that helps new businesses "
    "get incorporated, banked, and operationally set up. Use any guidance from "
    "your playbook below to produce a THOROUGH plan covering actions, open "
    "questions, and risks.\n\n"
    "Return ONLY valid JSON in this exact shape:\n"
    '{"actions": ["..."], "questions": ["..."], "risks": ["..."]}\n'
    "No prose, no code fences."
)

REVIEW_SYSTEM = (
    "You are a quality reviewer for onboarding plans. You compare a draft plan "
    "against a reference of what thorough coverage would include, and identify "
    "items in the reference that are MISSING, WEAK, or WRONGLY handled by the "
    "draft. For each gap, write ONE concise lesson the onboarding agent should "
    "remember going forward — phrased as a GENERAL principle, not specific to "
    "this customer. Tag each lesson with a short category label such as "
    "'Incorporation', 'Banking', 'Equity & cap table', 'International / KYC', "
    "'Compliance & tax', 'Conversion / restructuring'. Reuse existing category "
    "names when they fit; introduce a new label only when no existing one does.\n\n"
    "Return ONLY a JSON array of objects: "
    '[{"category": "...", "lesson": "..."}, ...]. '
    "Aim for 1-4 lessons total. No prose, no code fences."
)

CURATE_SYSTEM = (
    "You are the playbook curator for an onboarding agent. You maintain a "
    "structured markdown playbook organized by category. When new lessons "
    "arrive, you:\n"
    "  (1) consolidate them into existing sections when they belong there,\n"
    "  (2) CREATE a new ## section when a lesson's category isn't yet a section,\n"
    "  (3) merge or deduplicate overlapping bullets,\n"
    "  (4) keep each bullet to ONE line and phrased as a general principle.\n"
    "Preserve all useful prior guidance — don't drop existing bullets unless "
    "you are explicitly consolidating duplicates.\n\n"
    "Return ONLY the updated playbook as markdown with ## section headings. "
    "No prose outside the playbook, no code fences."
)


# =========================================================================
# LOW-LEVEL HELPERS
# =========================================================================
def call(system, user, max_tokens=1500):
    r = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return r.content[0].text


def strip_fences(text):
    return re.sub(r"```(?:json|markdown)?\s*|\s*```", "", text).strip()


def extract_json(text, kind="object"):
    text = strip_fences(text)
    pattern = r"\{.*\}" if kind == "object" else r"\[.*\]"
    m = re.search(pattern, text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# =========================================================================
# THE THREE AGENT ROLES
# =========================================================================
def make_plan(message, playbook):
    """Working agent: produce an onboarding plan using whatever playbook exists."""
    user = (f"Playbook (your accumulated guidance):\n"
            f"{playbook or '(empty — no prior guidance)'}\n\n"
            f"Customer message:\n{message}\n\n"
            f"Produce the onboarding plan as JSON now.")
    result = extract_json(call(PLAN_SYSTEM, user), kind="object")
    return result or {"actions": [], "questions": [], "risks": []}


def review_and_extract_lessons(message, draft, reference):
    """Reviewer: compare draft vs reference, write category-tagged lessons for each gap."""
    user = (f"Customer message:\n{message}\n\n"
            f"Draft plan:\n{json.dumps(draft, indent=2)}\n\n"
            f"Reference of thorough coverage:\n{json.dumps(reference, indent=2)}\n\n"
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


# =========================================================================
# MAIN LOOP
# =========================================================================
def main():
    playbook = ""

    print("=" * 72)
    print("ONBOARDING AGENT — building its own categorized playbook from cases")
    print("=" * 72)

    for ep, c in enumerate(CUSTOMERS, 1):
        print(f"\n{'─' * 72}\nEpisode {ep}: {c['summary']}\n{'─' * 72}")
        draft = make_plan(c["message"], playbook)
        lessons = review_and_extract_lessons(c["message"], draft, c["reference"])

        # Show what the reviewer flagged this round (this is the "synthesis" signal)
        print(f"\nReviewer flagged {len(lessons)} gap(s):")
        for l in lessons:
            cat = l.get("category", "Other") if isinstance(l, dict) else "Other"
            txt = l.get("lesson", "") if isinstance(l, dict) else str(l)
            print(f"  • [{cat}] {txt}")

        playbook = curate(playbook, lessons)

        # Snapshot per-episode so you can show the playbook GROWING over time
        with open(f"memory_ep{ep}.md", "w") as fh:
            fh.write(playbook)

        # Show the playbook after this episode
        print(f"\nPlaybook after episode {ep}:")
        print("─" * 72)
        print(playbook or "(still empty)")

    # ---------- Held-out test: combines multiple wrinkles -----------------
    print("\n" + "=" * 72)
    print(f"HELD-OUT TEST CUSTOMER — {TEST_CUSTOMER['summary']}")
    print("=" * 72)
    print(f"\nCustomer message:\n  {TEST_CUSTOMER['message']}\n")
    test_plan = make_plan(TEST_CUSTOMER["message"], playbook)
    print("Plan produced using the SELF-ORGANIZED playbook:")
    print("─" * 72)
    print(json.dumps(test_plan, indent=2))
    print("─" * 72)
    print("\nNote which categories from the playbook show up in this plan —")
    print("Incorporation + International/KYC + Compliance & tax should all appear,")
    print("even though the agent has never seen this exact case.")

    with open("memory2.md", "w") as fh:
        fh.write(playbook)
    print("\nSaved final playbook to memory.md (and per-episode snapshots to memory_ep1.md … memory_ep5.md)")


if __name__ == "__main__":
    main()