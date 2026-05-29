from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ContentBlock:
    block_type: str
    value: str


@dataclass(slots=True)
class Section:
    label: str
    blocks: list[ContentBlock] = field(default_factory=list)


@dataclass(slots=True)
class Question:
    order_id: int
    source_id: str = ""
    task_id: str = ""
    topic_id: str = ""
    pool_id: int = 0
    title: str = ""
    subject_name: str = ""
    phase_name: str = ""
    grade_name: str = ""
    pool_type_name: str = ""
    timeliness_hours: int | None = None
    tags: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    def summary(self, limit: int = 36) -> str:
        for section in self.sections:
            for block in section.blocks:
                if block.block_type == "text" and block.value.strip():
                    text = " ".join(block.value.split())
                    if len(text) > limit:
                        return text[:limit] + "..."
                    return text
        if self.title:
            return self.title[:limit] + ("..." if len(self.title) > limit else "")
        if self.topic_id:
            return self.topic_id[:limit] + ("..." if len(self.topic_id) > limit else "")
        return "Image only"

    @property
    def display_name(self) -> str:
        prefix = f"{self.order_id:03d}"
        if self.title:
            return f"{prefix}  {self.title}"
        return f"{prefix}  {self.summary(24)}"


@dataclass(slots=True)
class QuestionSet:
    title: str
    source_path: Path
    current_user_name: str = ""
    current_holding: int | None = None
    holding_limit: int | None = None
    questions: list[Question] = field(default_factory=list)
