from openai import OpenAI
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

SYSTEM_TEMPLATE = """{base_prompt}

Episode synopsis (if any):
{episode_synopsis}

You may use the context below to resolve references and keep terms consistent.
{context_block}
"""

USER_TEMPLATE = """Translate the following line into Swedish.
Keep stage cues. Output Swedish only.

Character: {character}
Ukrainian: {uk}
English: {en}
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
                input=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
            )
        except Exception as e:
            # openai-python raises rich exceptions; print full body
            try:
                print(getattr(e, "response", None).json())
            except Exception:
                print(str(e))
            raise
        return resp.output_text.strip()
