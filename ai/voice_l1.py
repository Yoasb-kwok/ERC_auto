"""Level 1 voice: phrase table plus a push-to-talk ASR stub.

The UI text box is the Level 1 stand-in. ``listen_once`` is the hook course
work should fill in. It returns None today so a missing microphone cannot
block the window.

TODO(C3): if ``speech_recognition`` or ``vosk`` is installed, record one
utterance (budget ``timeout_s``) and return the transcript string. The UI
already runs that string through :meth:`transcript_to_intent`.
"""

from __future__ import annotations

from ai.intents import resolve_intent


def asr_backend() -> str | None:
    """Name an installed ASR library, without starting a microphone."""
    try:
        import speech_recognition  # noqa: F401
    except ImportError:
        pass
    else:
        return "speech_recognition"
    try:
        import vosk  # noqa: F401
    except ImportError:
        pass
    else:
        return "vosk"
    return None


class VoiceLevel1:
    """Maps transcripts with the same table vision uses."""

    def __init__(self):
        self.backend_name = asr_backend()

    def transcript_to_intent(self, text: str | None) -> str | None:
        return resolve_intent(text)

    def listen_once(self, timeout_s: float = 2.0) -> str | None:
        """Push-to-talk capture. Level 1 returns None (stub).

        ``timeout_s`` is the capture budget for the future implementation.
        """
        self.backend_name = asr_backend()
        # TODO(C3): recognizer.listen(source, timeout=timeout_s) or a Vosk
        # one-shot. Return the transcript only; do not send UDP from here.
        del timeout_s
        return None
