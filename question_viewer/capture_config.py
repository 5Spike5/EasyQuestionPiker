from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class CaptureConfig:
    start_url: str = "https://static.xunfeixxj.com/videoMachiningPlatform/#/claim/pools/1"
    browser_name: str = "auto"
    browser_executable_path: str = ""
    debug_port: int = 9222
    profile_dir: str = ".browser_profile"
    list_item_selector: str = ".left-panel .panel-body .question-card"
    list_item_title_selector: str = ".item-id"
    preview_root_selector: str = ".question-preview .preview-body"
    section_selector: str = ".question-preview .preview-section"
    section_label_selector: str = ".section-label"
    section_content_selector: str = ".section-content"
    click_wait_ms: int = 1200
    question_limit: int = 0


def load_capture_config(config_path: str | Path) -> CaptureConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        config = CaptureConfig()
        save_capture_config(path, config)
        return config

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("start_url"):
        payload["start_url"] = "https://static.xunfeixxj.com/videoMachiningPlatform/#/claim/pools/1"
    if not payload.get("list_item_selector"):
        payload["list_item_selector"] = ".left-panel .panel-body .question-card"
    if not payload.get("list_item_title_selector"):
        payload["list_item_title_selector"] = ".item-id"
    if not payload.get("preview_root_selector"):
        payload["preview_root_selector"] = ".question-preview .preview-body"
    if not payload.get("section_selector"):
        payload["section_selector"] = ".question-preview .preview-section"
    if not payload.get("click_wait_ms"):
        payload["click_wait_ms"] = 1200

    defaults = asdict(CaptureConfig())
    defaults.update({key: value for key, value in payload.items() if key in defaults})
    return CaptureConfig(**defaults)


def save_capture_config(config_path: str | Path, config: CaptureConfig) -> Path:
    path = Path(config_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
