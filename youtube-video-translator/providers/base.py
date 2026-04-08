"""
Base provider interface definitions.

Each provider implements one of:
  - CaptionProvider: acquire source subtitle segments
  - ASRProvider: transcribe audio to segments
  - TranslatorProvider: translate text with glossary and context
  - TTSProvider: text-to-speech voiceover

All providers must be stateless (read from disk, write to disk).
State is managed by the orchestrator via temp/ files.
"""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


class CaptionProvider(Protocol):
    """
    Official caption acquisition provider.

    Responsibilities:
      - Fetch official subtitles from a video URL
      - Normalize to source_segments.json format
      - Return (exit_code, source_segments_file_path)
    """

    def fetch(self, url: str, output_dir: str) -> tuple[int, str]:
        """Fetch and normalize official subtitles."""
        ...


class ASRProvider(Protocol):
    """
    Automatic Speech Recognition provider.

    Responsibilities:
      - Extract audio from video
      - Transcribe audio to segments
      - Output asr_segments.json
      - Return (exit_code, asr_segments_file_path)
    """

    def transcribe(self, video_path: str, output_dir: str, model: str = "medium") -> tuple[int, str]:
        """Run ASR on video and write asr_segments.json."""
        ...


@runtime_checkable
class TranslatorProvider(Protocol):
    """
    Translation provider.

    Responsibilities:
      - Translate a single chunk's text to Chinese
      - Inject glossary_terms and context into prompt
      - Return translated text (str)

    The orchestrator handles parallelism, retry, and state writing.
    """

    def translate(
        self,
        text: str,
        glossary: list[dict] | None = None,
        context: str = "",
    ) -> str:
        """
        Translate `text` to Chinese.

        Args:
            text: The chunk's original text (may contain multiple SRT blocks)
            glossary: List of {term, translation} dicts for consistency
            context: Previous chunk's text for context continuity

        Returns:
            Translated SRT text (blocks with Chinese text)

        Raises:
            TranslationError: on failure
        """
        ...

    def name(self) -> str:
        """Provider name (e.g. 'subagent_claude', 'subagent_gemini', 'openai')."""
        ...


class TTSProvider(Protocol):
    """
    Text-to-Speech provider.

    Responsibilities:
      - Convert translated SRT to voiceover audio
      - Output audio file (mp3/wav)
      - Return (exit_code, audio_file_path)
    """

    def synthesize(self, srt_path: str, output_path: str) -> tuple[int, str]:
        """Generate voiceover audio from SRT."""
        ...


class TranslationError(Exception):
    """Raised when translation fails."""
    pass
