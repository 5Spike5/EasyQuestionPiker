from __future__ import annotations

import json
from pathlib import Path

from question_viewer.models import ContentBlock, Question, QuestionSet, Section


class QuestionDataError(Exception):
    pass


def load_question_set(source_path: str | Path) -> QuestionSet:
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise QuestionDataError(f"Data file not found: {path}")
    if path.suffix.lower() != ".json":
        raise QuestionDataError("Only JSON files are supported.")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QuestionDataError(f"JSON parse failed: {exc}") from exc

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        raise QuestionDataError("JSON is missing a questions array.")

    questions: list[Question] = []
    for index, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict):
            raise QuestionDataError(f"Question #{index} must be an object.")
        questions.append(_parse_question(raw_question, index, path.parent))

    title = str(payload.get("title") or path.stem)
    current_holding_raw = payload.get("current_holding")
    holding_limit_raw = payload.get("holding_limit")
    current_holding = int(current_holding_raw) if isinstance(current_holding_raw, int) else None
    holding_limit = int(holding_limit_raw) if isinstance(holding_limit_raw, int) else None

    return QuestionSet(
        title=title,
        source_path=path,
        current_user_name=str(payload.get("current_user_name") or "").strip(),
        current_holding=current_holding,
        holding_limit=holding_limit,
        questions=questions,
    )


def save_question_set(question_set: QuestionSet, destination: str | Path) -> Path:
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "title": question_set.title,
        "current_user_name": question_set.current_user_name,
        "current_holding": question_set.current_holding,
        "holding_limit": question_set.holding_limit,
        "questions": [
            {
                "source_id": question.source_id,
                "task_id": question.task_id,
                "topic_id": question.topic_id,
                "pool_id": question.pool_id,
                "title": question.title,
                "subject_name": question.subject_name,
                "phase_name": question.phase_name,
                "grade_name": question.grade_name,
                "pool_type_name": question.pool_type_name,
                "timeliness_hours": question.timeliness_hours,
                "tags": question.tags,
                "sections": [
                    {
                        "label": section.label,
                        "blocks": [
                            {
                                "type": block.block_type,
                                "value": block.value,
                            }
                            for block in section.blocks
                        ],
                    }
                    for section in question.sections
                ],
            }
            for question in question_set.questions
        ],
    }

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _parse_question(raw_question: dict, order_id: int, base_dir: Path) -> Question:
    raw_sections = raw_question.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise QuestionDataError(f"Question #{order_id} is missing sections.")

    sections: list[Section] = []
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            raise QuestionDataError(f"Question #{order_id} has an invalid section.")
        sections.append(_parse_section(raw_section, order_id, base_dir))

    tags = raw_question.get("tags") or []
    if not isinstance(tags, list):
        raise QuestionDataError(f"Question #{order_id} tags must be a list.")

    timeliness_raw = raw_question.get("timeliness_hours")
    timeliness_hours = int(timeliness_raw) if isinstance(timeliness_raw, int) else None

    return Question(
        order_id=order_id,
        source_id=str(raw_question.get("source_id") or ""),
        task_id=str(raw_question.get("task_id") or ""),
        topic_id=str(raw_question.get("topic_id") or ""),
        pool_id=int(raw_question.get("pool_id") or 0),
        title=str(raw_question.get("title") or ""),
        subject_name=str(raw_question.get("subject_name") or ""),
        phase_name=str(raw_question.get("phase_name") or ""),
        grade_name=str(raw_question.get("grade_name") or ""),
        pool_type_name=str(raw_question.get("pool_type_name") or ""),
        timeliness_hours=timeliness_hours,
        tags=[str(tag) for tag in tags],
        sections=sections,
    )


def _parse_section(raw_section: dict, order_id: int, base_dir: Path) -> Section:
    label = str(raw_section.get("label") or "Unnamed section").strip()
    blocks: list[ContentBlock] = []

    raw_blocks = raw_section.get("blocks")
    if isinstance(raw_blocks, list) and raw_blocks:
        for raw_block in raw_blocks:
            blocks.append(_parse_block(raw_block, order_id, label, base_dir))
    else:
        text = raw_section.get("text")
        if isinstance(text, str) and text.strip():
            blocks.append(ContentBlock(block_type="text", value=text.strip()))

        image = raw_section.get("image")
        if isinstance(image, str) and image.strip():
            blocks.append(
                ContentBlock(
                    block_type="image",
                    value=str(_resolve_local_image(image.strip(), base_dir)),
                )
            )

        images = raw_section.get("images")
        if isinstance(images, list):
            for image_path in images:
                if isinstance(image_path, str) and image_path.strip():
                    blocks.append(
                        ContentBlock(
                            block_type="image",
                            value=str(_resolve_local_image(image_path.strip(), base_dir)),
                        )
                    )

    if not blocks:
        raise QuestionDataError(f"Question #{order_id} section [{label}] has no displayable content.")

    return Section(label=label, blocks=blocks)


def _parse_block(raw_block: object, order_id: int, section_label: str, base_dir: Path) -> ContentBlock:
    if not isinstance(raw_block, dict):
        raise QuestionDataError(f"Question #{order_id} section [{section_label}] has an invalid block.")

    block_type = str(raw_block.get("type") or "").strip().lower()
    value = str(raw_block.get("value") or "").strip()
    if block_type not in {"text", "image"}:
        raise QuestionDataError(
            f"Question #{order_id} section [{section_label}] block.type must be text or image."
        )
    if not value:
        raise QuestionDataError(f"Question #{order_id} section [{section_label}] block.value cannot be empty.")

    if block_type == "image":
        value = str(_resolve_local_image(value, base_dir))

    return ContentBlock(block_type=block_type, value=value)


def _resolve_local_image(raw_path: str, base_dir: Path) -> Path:
    lowered = raw_path.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        raise QuestionDataError("Remote images are not supported in imported JSON.")

    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    if not path.exists():
        raise QuestionDataError(f"Image not found: {path}")
    return path
