from dataclasses import dataclass, field
from typing import List, Dict
from collections import Counter
from .utils import extract_candidate_terms

@dataclass
class RollingContext:
    window_size: int = 4
    max_glossary_terms: int = 40
    last_sources: List[str] = field(default_factory=list)        # full multi-lang source blob per line
    last_outputs: List[str] = field(default_factory=list)        # target text (whatever you're producing)
    last_speakers: List[str] = field(default_factory=list)
    glossary: Dict[str, int] = field(default_factory=dict)

    def update(self, character: str, source_text: str, out_text: str):
        """
        character: speaker name (may be empty)
        source_text: the entire multi-language source blob, e.g. 'russian: ... english: ...'
        out_text: produced translation/output text
        """
        combined = " ".join(filter(None, [character, source_text]))
        for t in extract_candidate_terms(combined):
            self.glossary[t] = self.glossary.get(t, 0) + 1

        if source_text:
            self.last_sources.append(source_text)
            if len(self.last_sources) > self.window_size:
                self.last_sources.pop(0)

        if character:
            self.last_speakers.append(character)
            if len(self.last_speakers) > self.window_size:
                self.last_speakers.pop(0)

        if out_text:
            self.last_outputs.append(out_text)
            if len(self.last_outputs) > self.window_size:
                self.last_outputs.pop(0)

        if len(self.glossary) > self.max_glossary_terms:
            top = Counter(self.glossary).most_common(self.max_glossary_terms)
            self.glossary = dict(top)

    def build_context_block(self) -> str:
        parts = []
        if self.last_speakers:
            parts.append("Recent speakers:\n" + "\n".join(f"- {s}" for s in self.last_speakers))
        if self.last_sources:
            parts.append("Recent lines (source):\n" + "\n".join(f"- {s}" for s in self.last_sources))
        if self.last_outputs:
            parts.append("Recent output lines:\n" + "\n".join(f"- {s}" for s in self.last_outputs))
        if self.glossary:
            terms = ", ".join(sorted(self.glossary.keys()))
            parts.append("Names/Terms glossary (keep consistent): " + terms)
        return "\n\n".join(parts)
