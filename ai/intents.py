"""Shared Level 1 intent table for vision labels and voice phrases.

Both hooks call ``resolve_intent`` and then ``CommandGateway.submit_intent``.
Do not add a second mapping table in the UI.
"""

from __future__ import annotations

# Canonical intents. ``estop`` latches the brake until the operator clears it.
INTENT_FORWARD = "forward"
INTENT_STOP = "stop"
INTENT_LEFT = "left"
INTENT_RIGHT = "right"
INTENT_ESTOP = "estop"

KNOWN_INTENTS = frozenset(
    {
        INTENT_FORWARD,
        INTENT_STOP,
        INTENT_LEFT,
        INTENT_RIGHT,
        INTENT_ESTOP,
    }
)

# Motion keeps the car moving. Anything else is a brake / non-motion sample.
MOTION_INTENTS = frozenset({INTENT_FORWARD, INTENT_LEFT, INTENT_RIGHT})

# Exact token or phrase → intent. Vision colors and voice words share this.
INTENT_TABLE = {
    "green": INTENT_FORWARD,
    "forward": INTENT_FORWARD,
    "go": INTENT_FORWARD,
    "red": INTENT_STOP,
    "stop": INTENT_STOP,
    "halt": INTENT_STOP,
    "brake": INTENT_STOP,
    "blue": INTENT_LEFT,
    "left": INTENT_LEFT,
    "yellow": INTENT_RIGHT,
    "right": INTENT_RIGHT,
    "estop": INTENT_ESTOP,
    "emergency": INTENT_ESTOP,
}

# Longer phrases checked before shorter ones inside a sentence.
INTENT_ALIASES = {
    "go forward": INTENT_FORWARD,
    "move forward": INTENT_FORWARD,
    "turn left": INTENT_LEFT,
    "go left": INTENT_LEFT,
    "turn right": INTENT_RIGHT,
    "go right": INTENT_RIGHT,
    "emergency stop": INTENT_ESTOP,
    "e stop": INTENT_ESTOP,
}

_PHRASES_LONGEST = sorted(
    list(INTENT_TABLE.items()) + list(INTENT_ALIASES.items()),
    key=lambda item: len(item[0]),
    reverse=True,
)


def normalize_phrase(text: str | None) -> str:
    """Lowercase, turn hyphens into spaces, collapse whitespace."""
    if text is None:
        return ""
    cleaned = str(text).strip().lower().replace("-", " ")
    return " ".join(cleaned.split())


def resolve_intent(text: str | None) -> str | None:
    """Map a label or transcript to a canonical intent, or None.

    Exact matches win. Otherwise the longest known phrase contained as
    whole words wins, so \"emergency stop\" is e-stop and not merely stop.
    """
    key = normalize_phrase(text)
    if not key:
        return None
    if key in INTENT_TABLE:
        return INTENT_TABLE[key]
    if key in INTENT_ALIASES:
        return INTENT_ALIASES[key]
    padded = f" {key} "
    for phrase, intent in _PHRASES_LONGEST:
        if f" {phrase} " in padded:
            return intent
    return None
