"""Level 1 AI skeleton for the ERC PC controller.

Vision and voice both resolve to the same intents. ``CommandGateway`` is the
only AI path onto the existing ``L:,R:,B:,S:`` datagram. See
``docs/AI_MVP_L1.md``.
"""

from ai.command_gateway import CommandGateway
from ai.intents import resolve_intent
from ai.vision_l1 import VisionLevel1
from ai.voice_l1 import VoiceLevel1

__all__ = [
    "CommandGateway",
    "VisionLevel1",
    "VoiceLevel1",
    "resolve_intent",
]
