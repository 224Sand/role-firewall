# role-firewall / Deterministic AI Model Pre-Filter & Governance Cost Optimization 

![python](https://img.shields.io/badge/python-3.10+-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![stdlib only](https://img.shields.io/badge/deps-stdlib%20only-orange)

**A deterministic input classifier that runs before you spend an LLM call.**

Declare a list of typed rules — reject, allow, allow-with-context — match them against incoming title + description text, return a clear `(allowed, reason, confidence)` decision. First matching rule wins. No LLM, no embeddings, no external calls.

```python
from role_firewall import Firewall, RejectIf, AllowIf, AllowIfContext

fw = Firewall([
    RejectIf(title_has=["spam", "test ticket"], reason="spam / test"),
    AllowIfContext(
        title_has=["question", "issue"],
        description_has=["billing", "refund", "invoice"],
        reason="billing question",
    ),
    AllowIf(title_has=["bug", "crash"], reason="bug — route to engineering"),
])

decision = fw.evaluate(title="Question about my invoice",
                       description="Why was I charged twice?")
# Decision(allowed=True, reason="billing question", confidence="medium")
```

Single file. Standard library only. MIT.

---

## Why this exists

Any pipeline that calls an LLM in a loop has the same hidden cost: a fraction of incoming inputs are obvious mismatches that don't deserve a token. A spam ticket. A wrong-domain support request. A category that's plainly off-target. Letting those through to the LLM means you pay tokens *and* latency *and* rate-limit budget on inputs you'd reject in 5 ms of pattern matching.

The naive fix is a single `if ... and ... and ... and ...` cascade. That works once. By the fifth category, the cascade becomes unmaintainable, the *why* of each branch is lost, and adding a sixth rule breaks the third. Worse: nobody can answer "why did we reject input X?" because the function returns a boolean.

This library is the small abstraction that fixes both:

- **Rules are typed objects, not branches.** `RejectIf`, `AllowIf`, `AllowIfContext`. Each carries its own reason string. Reading the rule list reads like a policy document.
- **The output is a `Decision`, not a bool.** You get back `(allowed, reason, confidence)` so the call site can log, sample, or escalate based on the *why*, not just the yes/no.
- **Order matters and is explicit.** First matching rule wins. The order of the rule list IS the policy precedence — no hidden tiebreaks.

## Rule types

| Rule | Behaviour |
|---|---|
| `RejectIf(title_has=[...], reason=...)` | If any term matches the title, immediately reject with the reason. |
| `AllowIf(title_has=[...], reason=..., confidence="high"|"medium"|"low")` | If any term matches the title, allow with the reason and confidence. |
| `AllowIfContext(title_has=[...], description_has=[...], reason=..., confidence="medium")` | Allow only if title matches AND any context term appears in the description. Use for ambiguous categories that are only valid with supporting evidence. |

All matching is case-insensitive. Switch to whole-word matching per-rule with `match_mode="word"`.

## What it isn't

- It isn't a full rules engine. No DSL, no priorities other than list order, no derived facts.
- It isn't a replacement for an LLM judge — it's the *cheap gate before* one.
- It doesn't learn from data. It's exactly as good as the rule list you write.

When you have ~3-30 rules that change quarterly and need to be readable by a human, this is the right level of abstraction. When you have 500+ rules that change weekly, you've outgrown it; go reach for a real rules engine.

## What I learned operating this in production

This library was extracted from the input-filter stage of an autonomous content pipeline that processed ~600 records per run. Three lessons drove the final shape:

- **A deterministic pre-filter is the single highest-ROI optimisation in any LLM pipeline.** Filtering ~88% of inputs before any token spend turned a 4-hour run into a 45-minute run on the same cloud budget. The LLM-judge passes that survived were also higher quality — the model spent its attention on borderline cases instead of obvious rejects. Pre-filter first, then prompt.
- **"Ambiguous" must be a different decision from "no".** The first version of this returned `True / False`. The next morning we had no idea why 30% of inputs were rejected. Adding a `reason` and a `confidence` level turned a black box into a debuggable system. The `confidence="low"` cases became the queue we sampled into LLM judgement; the `confidence="high"` cases became the rules we trusted blindly.
- **Order is the policy.** The original was a giant nested if/elif with implicit precedence. Two engineers reading the same code disagreed about which rule fires first. Restructuring to "ordered list of typed rules, first match wins" made precedence explicit in the data, not the control flow. Reordering became a one-line diff anyone could review.

The pattern across all three: **the value of a pre-filter is in its readability and its diagnostics, not its cleverness.** Boring deterministic rules with good reasons beat clever heuristics with bad ones.

## Run it

```bash
python role_firewall.py
```

The module's `__main__` block runs a support-ticket routing demo that hits every rule type. No install needed — standard library only.

## License

MIT — see [LICENSE](LICENSE).

---

*Part of a small set of single-file LLM-pipeline utilities: see also [resilient-llm-router](https://github.com/224Sand/resilient-llm-router) and [ground-truth-lock](https://github.com/224Sand/ground-truth-lock).*
