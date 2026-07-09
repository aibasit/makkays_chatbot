"""Tier 1 deterministic intent rules — the router's first, cheapest pass."""

from __future__ import annotations

import re

from app.shared.intent_context import IntentResult

BASE_TIER1_RULES: dict[str, list[str]] = {
    "sales_inquiry": [
        r"\blooking for\b",
        r"\bdo you have\b",
        r"\brecommend (a |an )?product\b",
        r"\binterested in\b",
        r"\bwhich (model|product) (should|would)\b",
    ],
    "quote_request": [
        r"\bquote\b",
        r"\bpricing\b",
        r"\bprice\b",
        r"\bhow much (is|does|for)\b",
        r"\bcost estimate\b",
        r"\bproposal\b",
    ],
    "technical_support": [
        r"\bnot working\b",
        r"\bbroken\b",
        r"\berror\b",
        r"\bdoesn.t work\b",
        r"\btroubleshoot\b",
        r"\bissue with my\b",
    ],
    "escalation_request": [
        r"\bspeak (to|with) a (human|person|representative)\b",
        r"\btalk to (someone|a real person)\b",
        r"\bescalate\b",
        r"\bcustomer service\b",
    ],
}

# v4.2 taxonomy extension (Module 00 section 34), copied verbatim from the spec.
TIER1_RULES_V42: dict[str, list[str]] = {
    "product_comparison": [r"\bcompare\b", r"\bvs\.?\b", r"\bdifference between\b", r"\bside.by.side\b"],
    "product_compatibility": [r"\bcompatible with\b", r"\bworks with\b", r"\bwill .+ work with\b"],
    "accessory_recommendation": [r"\baccessor(y|ies)\b", r"\badd.on\b", r"\bwhat .+ need with\b"],
    "product_finder_by_problem": [r"\bmy .+ (is|keeps|won.t)\b", r"\bproblem with\b", r"\bsolution for\b"],
    "product_alternative": [r"\breplacement for\b", r"\balternative to\b", r"\bsubstitute\b"],
    "specification_explainer": [
        r"\bwhat (is|does|are)\b .+(PoE|SFP|PoE\+|UPS|rack|watt)",
        r"\bexplain\b",
    ],
    "product_recommendation_wizard": [r"\bhelp me choose\b", r"\bguide me\b", r"\bwhat should I (get|buy)\b"],
    "use_case_recommendation": [
        r"\bfor (a |the )?(school|hospital|office|data.?center|cctv|enterprise|smb)\b"
    ],
    "installation_guidance": [r"\bhow (do I|to) install\b", r"\bsetup (guide|steps|instructions)\b"],
    "troubleshooting": [r"\bnot working\b", r"\berror code\b", r"\bfault\b", r"\bbroken\b"],
    "warranty_information": [r"\bwarranty\b", r"\brma\b", r"\brepair\b", r"\bguarantee\b"],
    "pdf_documentation_search": [r"\b(manual|datasheet|brochure|installation guide)\b", r"\bshow me the doc\b"],
    "availability_inquiry": [r"\bin.?stock\b", r"\bavailable\b", r"\bstock check\b", r"\bwhen can I get\b"],
    "solution_builder": [r"\bbuild (a |the )?solution\b", r"\bbom\b", r"\bbill of materials\b", r"\bfull setup\b"],
    "human_handoff": [r"\bspeak to\b", r"\btalk to\b", r"\bconnect me to\b", r"\bhuman\b", r"\bagent\b"],
}

TIER1_RULES: dict[str, list[str]] = {**BASE_TIER1_RULES, **TIER1_RULES_V42}

# Intents whose keyword sets overlap heavily with a sibling intent; Tier 1 only
# fires for these when at least two distinct patterns match, per Module 00
# section 34's confidence-behaviour note.
MIN_PATTERN_MATCHES: dict[str, int] = {
    "sales_inquiry": 2,
    "product_finder_by_problem": 2,
    "product_alternative": 2,
}

SPEC_QUESTION_PATTERNS: list[str] = [
    r"\bwhat (is|does|are)\b",
    r"\bspec(s|ification)?\b",
    r"\bhow many (ports|watts|amps)\b",
    r"\bexplain\b",
]

# Intents whose Tier1 keywords (compare, vs, compatible with, accessory, replacement
# for, ...) are generic English phrasing that says nothing about *which* product is
# being discussed — "compare the MacBook Air vs Pro" matches `\bcompare\b` just as
# well as a legitimate switch/UPS comparison. For these, Tier1 only trusts its own
# match if the message also mentions something plausibly in Makkays' catalog;
# otherwise it defers (returns None) to Tier2, which has the domain-scoping
# instructions to correctly classify unrelated products as out_of_scope instead of
# confidently misrouting into a plan that will fail against an empty catalog match.
_DOMAIN_SENSITIVE_INTENTS: frozenset[str] = frozenset(
    {
        "product_comparison",
        "product_compatibility",
        "accessory_recommendation",
        "product_alternative",
        "specification_explainer",
    }
)

_DOMAIN_KEYWORD_PATTERN = re.compile(
    r"\b(switch(?:es)?|router|access point|wi-?fi|ups|avr|voltage regulator|"
    r"battery|batteries|rack|cabinet|network(?:ing)?|poe|sfp|data ?center|"
    r"makkays|i-?power|i-?connect)\b",
    re.IGNORECASE,
)


class Tier1RuleEngine:
    """Deterministic keyword/regex rules producing a confident `(intent, 1.0)` or nothing."""

    def match(self, message: str) -> IntentResult | None:
        """Return a confident IntentResult only when exactly one intent is unambiguous."""
        lowered = message.lower()
        hits: dict[str, int] = {}
        for intent, patterns in TIER1_RULES.items():
            count = sum(1 for pattern in patterns if re.search(pattern, lowered))
            if count:
                hits[intent] = count

        confident = [intent for intent, count in hits.items() if count >= MIN_PATTERN_MATCHES.get(intent, 1)]
        if len(confident) != 1:
            return None

        intent = confident[0]
        if intent in _DOMAIN_SENSITIVE_INTENTS and not _DOMAIN_KEYWORD_PATTERN.search(lowered):
            return None
        return IntentResult(
            intent=intent,
            confidence=1.0,
            source="tier1",
            candidates=[intent],
            spec_question_detected=self.detect_spec_question(message),
        )

    def detect_spec_question(self, message: str) -> bool:
        """Return whether the message reads as a technical spec-type question."""
        lowered = message.lower()
        return any(re.search(pattern, lowered) for pattern in SPEC_QUESTION_PATTERNS)
