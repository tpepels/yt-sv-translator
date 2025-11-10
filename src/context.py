from dataclasses import dataclass, field
from typing import List, Dict
from collections import Counter
from .utils import extract_candidate_terms

@dataclass
class RollingContext:
    window_size: int = 4
    max_glossary_terms: int = 40
    last_sources: List[str] = field(default_factory=list)
    last_translations: List[str] = field(default_factory=list)
    last_speakers: List[str] = field(default_factory=list)
    glossary: Dict[str, int] = field(default_factory=dict)

    def update(self, character: str, source_uk: str, source_en: str, sv_out: str):
        combined = " ".join(filter(None, [character, source_uk, source_en]))
        terms = extract_candidate_terms(combined)
        for t in terms:
            self.glossary[t] = self.glossary.get(t, 0) + 1

        if source_uk or source_en:
            snippet = (source_uk or "") + (" / " if source_uk and source_en else "") + (source_en or "")
            self.last_sources.append(snippet)
            if len(self.last_sources) > self.window_size:
                self.last_sources.pop(0)

        if character:
            self.last_speakers.append(character)
            if len(self.last_speakers) > self.window_size:
                self.last_speakers.pop(0)

        if sv_out:
            self.last_translations.append(sv_out)
            if len(self.last_translations) > self.window_size:
                self.last_translations.pop(0)

        if len(self.glossary) > self.max_glossary_terms:
            top = Counter(self.glossary).most_common(self.max_glossary_terms)
            self.glossary = dict(top)

    def build_context_block(self) -> str:
        parts = []
        if self.last_speakers:
            parts.append("Recent speakers:\n" + "\n".join(f"- {s}" for s in self.last_speakers))
        if self.last_sources:
            parts.append("Recent lines (source):\n" + "\n".join(f"- {s}" for s in self.last_sources))
        if self.last_translations:
            parts.append("Recent Swedish lines:\n" + "\n".join(f"- {s}" for s in self.last_translations))
        if self.glossary:
            terms = ", ".join(sorted(self.glossary.keys()))
            parts.append("Names/Terms glossary (keep consistent): " + terms)
        return "\n\n".join(parts)
