from openai import OpenAI
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
from typing import List, Tuple, Sequence
import re

SYSTEM_TEMPLATE = """{base_prompt}

Episode synopsis (if any):
{episode_synopsis}

You may use the context below to resolve references and keep terms consistent.
{context_block}
"""

# Single-line template (unchanged)
USER_TEMPLATE = """Translate the following line into Swedish.
Output Swedish only. Do not include the character name in your output, only output what the character says.

Character: {character}
Russian: {uk}
English: {en}
"""

# Batch template (new)
BATCH_USER_TEMPLATE = """Translate the following lines into Swedish. 
Output Swedish only. Do not include the character name in your output, only what the character says.
Return the answers as a numbered list (1..N), one line per item, with **no extra commentary**.

{items_block}
"""

@dataclass
class TranslatorConfig:
    api_key: str
    model: str
    base_prompt: str = ""
    preserve_cues: bool = True
    approx_length_match: bool = True

class LineTranslator:
    def __init__(self, cfg: TranslatorConfig):
        self.client = OpenAI(api_key=cfg.api_key)
        self.cfg = cfg

    # ----------------------------
    # Existing single-line method
    # ----------------------------
    @retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(initial=1, max=15))
    def translate(self, character, uk, en, context_block, episode_synopsis):
        system_text = SYSTEM_TEMPLATE.format(
            base_prompt=self.cfg.base_prompt,
            episode_synopsis=episode_synopsis or "(none)",
            context_block=context_block or "(none)",
        )
        user_text = USER_TEMPLATE.format(
            character=character or "(unknown)",
            uk=uk or "(empty)",
            en=en or "(empty)",
        )
        try:
            resp = self.client.responses.create(
                model=self.cfg.model,
                reasoning={"effort": "minimal"},  # lower reasoning effort for speed
                input=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
            )
        except Exception as e:
            try:
                print(getattr(e, "response", None).json())
            except Exception:
                print(str(e))
            raise
        return resp.output_text.strip()

    # ----------------------------
    # New: batch method
    # ----------------------------
    @retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(initial=1, max=15))
    def translate_batch(
        self,
        items: Sequence[Tuple[str, str, str]],  # [(character, uk, en), ...]
        context_block: str,
        episode_synopsis: str,
    ) -> List[str]:
        """
        Translate multiple lines in a single request.
        Returns a list of Swedish strings in the same order as inputs.

        items: sequence of (character, uk, en)
        """
        if not items:
            return []

        system_text = SYSTEM_TEMPLATE.format(
            base_prompt=self.cfg.base_prompt,
            episode_synopsis=episode_synopsis or "(none)",
            context_block=context_block or "(none)",
        )

        # Build the numbered block
        # 1) Character: X
        #    Russian: ...
        #    English: ...
        numbered = []
        for i, (ch, uk, en) in enumerate(items, start=1):
            ch = ch or "(unknown)"
            uk = uk or "(empty)"
            en = en or "(empty)"
            numbered.append(
                f"{i}) Character: {ch}\n"
                f"   Russian: {uk}\n"
                f"   English: {en}"
            )
        items_block = "\n\n".join(numbered)

        user_text = BATCH_USER_TEMPLATE.format(items_block=items_block)

        try:
            resp = self.client.responses.create(
                model=self.cfg.model,
                reasoning={"effort": 'minimal'},  # lower reasoning for speed
                input=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                # You can set a cap if needed:
                # max_output_tokens=items * 120
            )
        except Exception as e:
            try:
                print(getattr(e, "response", None).json())
            except Exception:
                print(str(e))
            raise

        raw = resp.output_text.strip()
        parsed = self._parse_batch_output(raw, expected=len(items))
        return parsed

    # ----------------------------
    # Helpers for batch parsing
    # ----------------------------
    def _parse_batch_output(self, text: str, expected: int) -> List[str]:
        """
        Parse a numbered list of outputs "1) ...", "2) ...", etc. into a list[str].
        Tries several strategies to be robust to minor formatting variations.
        """
        lines = text.splitlines()

        # Strategy 1: capture blocks starting with "n)" or "n."
        blocks = []
        current = []
        current_idx = None
        for line in lines:
            m = re.match(r"^\s*(\d+)[\)\.]\s*(.*)$", line)
            if m:
                idx = int(m.group(1))
                content = m.group(2).strip()
                if current and current_idx is not None:
                    blocks.append("\n".join(current).strip())
                    current = []
                current_idx = idx
                current = [content] if content else []
            else:
                if current:
                    current.append(line.strip())
        if current:
            blocks.append("\n".join(current).strip())

        if len(blocks) == expected:
            return blocks

        # Strategy 2: if model returned plain lines without numbering, fall back to non-empty lines
        fallback = [l.strip() for l in lines if l.strip()]
        if len(fallback) == expected:
            return fallback

        # Strategy 3: last resort—return the whole text as the first item if only one expected
        if expected == 1:
            return [text.strip()]

        # If parsing fails, raise to let the retry handle it
        raise ValueError(f"Could not parse batch output into {expected} items. Raw:\n{text}")
