from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


ACCOUNT_SLOT_COUNT = 5
DEFAULT_AUTO_SYNC_DELAY_MS = 1500


def _default_account_names() -> list[str]:
    return [f"Account {index}" for index in range(1, ACCOUNT_SLOT_COUNT + 1)]


def normalize_account_names(names: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    for index in range(ACCOUNT_SLOT_COUNT):
        if names and index < len(names):
            value = str(names[index] or "").strip()
            normalized.append(value or f"Account {index + 1}")
        else:
            normalized.append(f"Account {index + 1}")
    return normalized


def normalize_account_index(index: object) -> int:
    try:
        value = int(index)
    except (TypeError, ValueError):
        value = 0
    return max(0, min(ACCOUNT_SLOT_COUNT - 1, value))


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
    auto_sync_delay_ms: int = DEFAULT_AUTO_SYNC_DELAY_MS
    question_limit: int = 0
    active_account_index: int = 0
    account_names: list[str] = field(default_factory=_default_account_names)


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
    if not payload.get("auto_sync_delay_ms"):
        payload["auto_sync_delay_ms"] = DEFAULT_AUTO_SYNC_DELAY_MS

    defaults = asdict(CaptureConfig())
    defaults.update({key: value for key, value in payload.items() if key in defaults})
    defaults["auto_sync_delay_ms"] = max(600, int(defaults.get("auto_sync_delay_ms") or DEFAULT_AUTO_SYNC_DELAY_MS))
    defaults["active_account_index"] = normalize_account_index(defaults.get("active_account_index"))
    defaults["account_names"] = normalize_account_names(defaults.get("account_names"))
    return CaptureConfig(**defaults)


def save_capture_config(config_path: str | Path, config: CaptureConfig) -> Path:
    path = Path(config_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    config.account_names = normalize_account_names(config.account_names)
    config.active_account_index = normalize_account_index(config.active_account_index)
    config.auto_sync_delay_ms = max(600, int(config.auto_sync_delay_ms or DEFAULT_AUTO_SYNC_DELAY_MS))
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
