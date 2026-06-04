"""
memory_loop_demo.py  —  a tiny demo of WEIGHT-FREE, COMPOUNDING improvement
============================================================================

IDEA
------------
We give a frozen LLM a task it CANNOT do correctly on the first try, because
success depends on arbitrary conventions it has no way to guess ("ACME Corp"
wants UPPERCASE names, DDMMYYYY dates, amounts in integer cents, and specific
JSON keys). Every time it gets one wrong, it REFLECTS on the mistake in plain
English and writes a one-line lesson into a markdown "memory". On later tasks
that memory is pasted back into the prompt.

OUTPUTS
-------
    memory_curve.png   the rising-accuracy chart (the thing you screenshot)
    memory.md          the lessons the agent taught itself
"""

import json
import re
import anthropic
import matplotlib.pyplot as plt
from dotenv import load_dotenv

load_dotenv()

# --- Config --------------------------------------------------------------
MODEL = "claude-sonnet-4-6"
EPISODES = 6
client = anthropic.Anthropic()


# === THE HIDDEN CONVENTIONS ==============================================
# This is ACME's arbitrary "secret" formatting standard. the agent must learn this.
def expected_output(f):
    return {
        "customer": f["name"].upper(),                   # rule 1: names UPPERCASE
        "date": _ddmmyyyy(f["iso_date"]),                # rule 2: dates as DDMMYYYY
        "amount_cents": int(round(f["dollars"] * 100)),  # rule 3: amounts in integer cents
    }                                                    # rule 4 (implicit): these exact keys


def _ddmmyyyy(iso):                      # helper: "2026-03-15" -> "15032026"
    y, m, d = iso.split("-")
    return f"{d}{m}{y}"


# different phrasings
TEMPLATES = [
    "Hi, this is {name}. I'd like to confirm my order placed on {iso_date} for ${dollars:.2f}. Thanks!",
    "Order confirmation request - placed {iso_date}, total ${dollars:.2f}. Name on the account is {name}.",
    "Hello! {name} here. Spent ${dollars:.2f} on {iso_date} - can you verify it went through?",
    "Following up on a purchase from {iso_date}. The amount was ${dollars:.2f}, and it's under {name}.",
    "This is {name} writing about my {iso_date} order (${dollars:.2f}). Please confirm receipt.",
    "Quick question about my account ({name}): the ${dollars:.2f} charge dated {iso_date} - is that confirmed?",
]


def message(f):
    # Pick this task's phrasing by its `style` index and fill in the values.
    return TEMPLATES[f["style"]].format(**f)


# === TWO TASK SETS =======================================================
# TRAIN: the agent attempts these AND is shown the correct answer when wrong,
#        so it can learn the rules.
# TEST:  held out. The agent is only ever SCORED on these, never corrected.
#        Improvement here = genuine generalization (it learned the rule), not
#        memorization of specific answers. This split is what makes the demo
#        honest rather than a parlor trick.
TRAIN = [
    {"name": "John Smith",   "iso_date": "2026-03-15", "dollars": 42.50,   "style": 0},
    {"name": "Aisha Khan",   "iso_date": "2025-11-02", "dollars": 9.99,    "style": 1},
    {"name": "Leo Martins",  "iso_date": "2026-01-30", "dollars": 1500.00, "style": 2},
    {"name": "Mei Tanaka",   "iso_date": "2024-07-08", "dollars": 73.10,   "style": 3},
    {"name": "Omar Haddad",  "iso_date": "2026-05-21", "dollars": 250.00,  "style": 4},
    {"name": "Sara Nilsson", "iso_date": "2025-09-14", "dollars": 5.05,    "style": 5},
]
TEST = [
    {"name": "Diego Ramos",  "iso_date": "2026-02-11", "dollars": 19.95,  "style": 5},
    {"name": "Hana Park",    "iso_date": "2025-12-25", "dollars": 100.00, "style": 0},
    {"name": "Ivan Petrov",  "iso_date": "2024-04-04", "dollars": 8.40,   "style": 3},
    {"name": "Grace Lee",    "iso_date": "2026-06-01", "dollars": 333.33, "style": 1},
    {"name": "Tom Becker",   "iso_date": "2025-08-19", "dollars": 60.00,  "style": 4},
]

# The system prompt tells the agent to follow ACME's conventions but never says what they ARE.
SYSTEM = ("You are an intake agent for ACME Corp. Read the customer message and output "
          "ONLY a JSON object with the extracted order details, following ACME's "
          "formatting conventions exactly. No prose, no code fences.")


# === LOW-LEVEL HELPERS ===================================================
def call(prompt, system=""):
    r = client.messages.create(
        model=MODEL, max_tokens=400, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text


def parse_json(text):
    text = re.sub(r"```(json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


# === Core Ops: ATTEMPT and REFLECT ========================
def attempt(f, memory):
    prompt = f"{memory}\n\nCustomer message:\n{message(f)}\n\nOutput the JSON object now."
    return parse_json(call(prompt, SYSTEM))


def reflect(f, got, expected):
    prompt = (f"Customer message:\n{message(f)}\n\n"
              f"You output:\n{json.dumps(got)}\n\n"
              f"The correct answer ACME wanted:\n{json.dumps(expected)}\n\n"
              "In ONE short bullet, state the GENERAL formatting rule to remember so "
              "you get this right next time — about the convention, not this one example.")
    return "- " + call(prompt).strip().lstrip("-").strip()


# === MEMORY MANAGEMENT ===================================================
def memory_block(lessons):
    if not lessons:
        return ""
    return "Lessons learned about ACME's conventions:\n" + "\n".join(lessons) + "\n"


def dedupe(lessons):
    # Two jobs: drop duplicate lessons (the agent often re-derives the same rule),
    # and CAP the memory at the 12 most recent lessons --- NEED TO FIX THIS TO CUT TEH LEAST USEFUL NOT JUST OLDEST or summarized (just put example)
    seen, out = set(), []
    for l in lessons:
        if l.lower() not in seen:
            seen.add(l.lower())
            out.append(l)
    return out[-12:]


# === SCORING =============================================================
def evaluate(memory):
    # Run the held-out TEST set with a given memory and return the fraction the
    # agent gets EXACTLY right. Exact match is deliberately strict: it forces the
    return sum(attempt(f, memory) == expected_output(f) for f in TEST) / len(TEST)


# === THE MAIN LOOP =======================================================
def main():
    lessons = []                        # the memory starts EMPTY

    # 1) Baseline: score the test set with no memory at all. This is the agent
    #    at "day zero" — it should be near 0% because it can't guess ACME's rules.
    cold = evaluate("")
    print(f"cold baseline (no memory): {cold:.0%}")

    # 2) Episodes. Each episode = practice-and-learn on TRAIN, then score on TEST.
    accs = []
    for ep in range(1, EPISODES + 1):
        mem = memory_block(lessons)     # snapshot of current memory for this pass
        for f in TRAIN:
            got = attempt(f, mem)       # try the training task with current memory
            exp = expected_output(f)
            if got != exp:              # got it wrong -> LEARN from the correction
                lessons.append(reflect(f, got, exp))
                lessons = dedupe(lessons)
                mem = memory_block(lessons)   # refresh memory so later tasks this
                                              # episode already benefit from it
        acc = evaluate(mem)             # score the held-out TEST set with new memory
        accs.append(acc)
        print(f"episode {ep}: held-out test acc = {acc:.0%}  | lessons stored = {len(lessons)}")
    # Across episodes: memory goes from empty -> contains all four conventions,
    # so test accuracy climbs from ~0% toward ~100%. Same model, same test tasks,
    # only the memory changed.

    with open("memory.md", "w") as fh:
        fh.write("# Agent memory (self-taught)\n\n" + "\n".join(lessons) + "\n")
    plot(cold, accs)


# === THE CHART ===========================================================
def plot(cold, accs):
    xs = list(range(1, len(accs) + 1))
    plt.figure(figsize=(7, 4.5))
    plt.plot(xs, [a * 100 for a in accs], "-o", linewidth=2, label="with compounding memory")
    plt.axhline(cold * 100, ls="--", color="gray", label=f"cold baseline ({cold:.0%})")
    plt.ylim(0, 105)
    plt.xlabel("episode")
    plt.ylabel("held-out test accuracy (%)")
    plt.title("Weight-free compounding: the agent teaches itself\nthe conventions and gets better — model never fine-tuned")
    plt.legend()
    plt.tight_layout()
    plt.savefig("memory_curve.png", dpi=130)
    print("saved memory_curve.png and memory.md")


if __name__ == "__main__":
    main()