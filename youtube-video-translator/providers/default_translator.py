"""
Default translator provider.

Uses the configured session runner and fails fast when delegated translation
is unavailable. Implements the TranslatorProvider protocol.
"""
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from providers.base import TranslatorProvider, TranslationError
from translation_runtime import (
    resolve_translation_provider,
    run_subagent,
)


PROMPT_TEMPLATE = """你是专业字幕翻译器。请把下面字幕片段翻译为简体中文。

硬性要求：
1) 保留每个字幕块的时间轴原样不变。
2) 每个块只输出中文译文，不要保留英文原文。
3) 不要删块、并块、拆块。
4) 不要输出任何解释，只输出SRT格式内容（序号+时间轴+译文）。
{glossary_section}{context_section}
待翻译片段：
{batch_content}
"""


def _build_prompt(text: str, glossary: list[dict] | None = None, context: str = "") -> str:
    glossary_section = ""
    if glossary:
        lines = ["参考术语："]
        for t in glossary:
            lines.append(f"  {t.get('term', '')} -> {t.get('translation', '')}")
        glossary_section = "\n".join(lines)
    else:
        glossary_section = "无术语表。"

    context_section = ""
    if context:
        context_section = f"\n前文参考（最后一块）：\n{context.strip()}"

    return PROMPT_TEMPLATE.format(
        glossary_section=glossary_section,
        context_section=context_section,
        batch_content=text,
    )


class DefaultTranslator(TranslatorProvider):
    """
    Dispatches translation via the configured subagent runner.
    """

    def __init__(self, model_id: str | None = None):
        self._agent_def = SKILL_ROOT / "agents" / "translator.md"

    def name(self) -> str:
        return resolve_translation_provider()

    def translate(
        self,
        text: str,
        glossary: list[dict] | None = None,
        context: str = "",
    ) -> str:
        """
        Translate text via subagent.

        Writes prompt to temp/, invokes the configured runner, and reads result.
        """
        prompt = _build_prompt(text, glossary, context)

        # Write prompt to temp for subagent
        # Use a fixed temp location within the current translation
        prompt_file = SKILL_ROOT / "temp_translation_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        translated_file = SKILL_ROOT / "temp_translation_output.txt"

        try:
            succeeded, error, runner = run_subagent(
                task="Translate this subtitle chunk to Chinese",
                prompt_file=prompt_file,
                translated_file=translated_file,
                agent_def=self._agent_def,
            )
            if succeeded:
                return translated_file.read_text(encoding="utf-8").strip()
            raise TranslationError(error or f"{runner} runner failed")
        except RuntimeError as exc:
            raise TranslationError(str(exc)) from exc
