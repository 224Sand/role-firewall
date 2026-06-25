"""
role-firewall
==============
A tiny deterministic input classifier that runs *before* you spend an LLM call.

The pattern: declare a list of typed rules (reject / allow / allow-with-context)
matched against title + description text. First matching rule wins. Returns a
clear (allowed, reason, confidence) decision so the caller knows what happened.

The use case: any pipeline where a fraction of incoming inputs are obvious
mismatches that don't deserve an LLM call. Support-ticket routing, lead
scoring, content moderation pre-gates, document classification, role/category
matching. Filter the obvious 70-90% with deterministic rules; spend tokens
on the genuinely ambiguous remainder.

Single file. No dependencies. MIT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


__all__ = [
    "Firewall",
    "RejectIf",
    "AllowIf",
    "AllowIfContext",
    "Decision",
]


# ── normalisation ────────────────────────────────────────────────────────


def _norm(s) -> str:
    """Lowercase and collapse whitespace. None-safe."""
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()


def _has(text: str, terms: list[str], mode: str = "substring") -> bool:
    """True if any term appears in text under the given match mode."""
    if not terms:
        return False
    if mode == "substring":
        return any(t in text for t in terms)
    if mode == "word":
        for t in terms:
            if re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", text):
                return True
        return False
    raise ValueError(f"unknown match mode: {mode}")


# ── rule types ───────────────────────────────────────────────────────────


@dataclass
class _BaseRule:
    """Internal base; users instantiate RejectIf / AllowIf / AllowIfContext."""
    title_has: list[str] = field(default_factory=list)
    reason: str = ""
    match_mode: Literal["substring", "word"] = "substring"


@dataclass
class RejectIf(_BaseRule):
    """Reject the input if any `title_has` term appears in the title."""
    pass


@dataclass
class AllowIf(_BaseRule):
    """Allow the input if any `title_has` term appears in the title."""
    confidence: Literal["high", "medium", "low"] = "high"


@dataclass
class AllowIfContext(_BaseRule):
    """Allow only if title matches AND any `description_has` term appears in
    the description. Use for ambiguous categories that are valid only with
    supporting context (e.g. a 'Question' ticket title allowed only when the
    description mentions 'billing' or 'refund')."""
    description_has: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


# ── decision type ────────────────────────────────────────────────────────


@dataclass
class Decision:
    """Outcome of evaluating an input against a Firewall."""
    allowed: bool
    reason: str
    confidence: Literal["high", "medium", "low"] = "high"

    def __iter__(self):
        # So `allowed, reason = fw.evaluate(...)` still works.
        yield self.allowed
        yield self.reason

    def __bool__(self):
        return self.allowed


# ── the firewall ─────────────────────────────────────────────────────────


class Firewall:
    """Evaluate inputs against an ordered list of rules. First match wins.

    Construction:

        fw = Firewall([
            RejectIf(title_has=["spam", "test"], reason="obvious spam"),
            AllowIfContext(
                title_has=["question"],
                description_has=["billing", "refund"],
                reason="billing question — route to billing team",
            ),
            AllowIf(title_has=["bug report"], reason="bug — route to engineering"),
        ])

        decision = fw.evaluate(
            title="My credit card was charged twice",
            description="I need a refund on the duplicate charge",
        )
        # Decision(allowed=True, reason="billing question — route to billing team",
        #         confidence="medium")

    Rules are evaluated in order. First rule whose conditions match returns
    a decision. If no rule matches, the firewall returns `default_action`
    (default: reject with reason "no matching rule").
    """

    def __init__(
        self,
        rules: list[_BaseRule],
        *,
        default_action: Literal["allow", "reject"] = "reject",
        default_reason: str = "no matching rule",
        default_confidence: Literal["high", "medium", "low"] = "low",
    ):
        self.rules = rules
        self.default_action = default_action
        self.default_reason = default_reason
        self.default_confidence = default_confidence

    def evaluate(self, *, title: str, description: str = "") -> Decision:
        t = _norm(title)
        d = _norm(description)

        if not t:
            return Decision(allowed=False, reason="empty title", confidence="high")

        for rule in self.rules:
            if not _has(t, rule.title_has, rule.match_mode):
                continue

            if isinstance(rule, RejectIf):
                return Decision(allowed=False, reason=rule.reason, confidence="high")

            if isinstance(rule, AllowIf):
                return Decision(allowed=True, reason=rule.reason,
                                confidence=rule.confidence)

            if isinstance(rule, AllowIfContext):
                if _has(d, rule.description_has, rule.match_mode):
                    return Decision(allowed=True, reason=rule.reason,
                                    confidence=rule.confidence)
                # Title matched but context didn't — keep walking
                continue

        # No rule matched
        return Decision(
            allowed=(self.default_action == "allow"),
            reason=self.default_reason,
            confidence=self.default_confidence,
        )


if __name__ == "__main__":
    # Example: support-ticket routing. Reject spam, route billing/refund to
    # billing, route bugs to engineering, escalate everything else.
    fw = Firewall(
        [
            RejectIf(title_has=["spam", "test ticket", "asdf"],
                     reason="spam / test"),
            AllowIfContext(
                title_has=["question", "issue", "problem"],
                description_has=["billing", "refund", "invoice", "payment"],
                reason="billing question",
            ),
            AllowIf(title_has=["bug", "crash", "error", "broken"],
                    reason="bug — route to engineering"),
            AllowIf(title_has=["feature request", "would be nice"],
                    reason="feature request", confidence="medium"),
        ],
        default_action="allow",
        default_reason="ambiguous — escalate to human triage",
        default_confidence="low",
    )

    cases = [
        ("Question about my invoice",
         "Why was I charged twice? Need a refund."),     # → AllowIfContext (billing)
        ("Crash on login page", "Stack trace below..."), # → AllowIf (bug)
        ("Spam test", "asdfasdf"),                       # → RejectIf
        ("Feature request: dark mode", "Would love it"), # → AllowIf (low confidence)
        ("Pricing inquiry from a partner", "TBD"),       # → default (no rule matched)
        ("", ""),                                        # → empty title
    ]
    for title, desc in cases:
        d = fw.evaluate(title=title, description=desc)
        verdict = "ALLOW" if d.allowed else "REJECT"
        print(f"[{verdict:6}] ({d.confidence:6}) {title!r:40} → {d.reason}")
