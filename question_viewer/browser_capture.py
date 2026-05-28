from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from question_viewer.capture_config import CaptureConfig
from question_viewer.loader import save_question_set
from question_viewer.models import ContentBlock, Question, QuestionSet, Section


StatusCallback = Callable[[str], None]

PLATFORM_ORIGIN = "https://static.xunfeixxj.com"
POOL_ID = 1
POOL_PAGE_URL = f"{PLATFORM_ORIGIN}/videoMachiningPlatform/#/claim/pools/{POOL_ID}"
CLAIM_MODULE_URL = f"{PLATFORM_ORIGIN}/videoMachiningPlatform/assets/claim-DmfQfiCu.js"

_SESSION_QUESTION_CACHE: dict[str, Question] = {}
_SESSION_SIGNATURE_CACHE: dict[str, str] = {}


class CaptureError(Exception):
    pass


def detect_browser_executable(browser_name: str = "auto") -> str:
    browser_name = (browser_name or "auto").strip().lower()
    chrome_candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
    ]
    edge_candidates = [
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path.home() / "AppData/Local/Microsoft/Edge/Application/msedge.exe",
    ]

    if browser_name == "chrome":
        candidates = chrome_candidates
    elif browser_name == "edge":
        candidates = edge_candidates
    else:
        candidates = chrome_candidates + edge_candidates

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise CaptureError("No Chrome or Edge executable was found. Please configure the browser path manually.")


def launch_debug_browser(
    config: CaptureConfig,
    app_home: str | Path,
    status_callback: StatusCallback | None = None,
) -> None:
    port = int(config.debug_port or 9222)
    if _debug_endpoint_ready(port):
        _emit(status_callback, f"Browser debug endpoint is ready on port {port}.")
        return

    browser_path = config.browser_executable_path.strip() or detect_browser_executable(config.browser_name)
    profile_dir = _resolve_profile_dir(config, app_home)
    profile_dir.mkdir(parents=True, exist_ok=True)

    start_url = config.start_url.strip() or POOL_PAGE_URL
    command = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        start_url,
    ]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _emit(status_callback, "Launching browser...")

    for _ in range(40):
        if _debug_endpoint_ready(port):
            _emit(status_callback, "Browser is ready. Please log in once in that browser window.")
            return
        time.sleep(0.5)

    raise CaptureError("The browser was started, but the remote debugging port did not become available.")


def reset_runtime_cache(output_root: str | Path) -> None:
    global _SESSION_QUESTION_CACHE, _SESSION_SIGNATURE_CACHE

    _SESSION_QUESTION_CACHE = {}
    _SESSION_SIGNATURE_CACHE = {}

    output_root = Path(output_root).resolve()
    json_path = output_root / "latest_questions.json"
    assets_dir = output_root / "assets"

    if json_path.exists():
        json_path.unlink()
    if assets_dir.exists():
        shutil.rmtree(assets_dir, ignore_errors=True)


def inspect_current_page(
    config: CaptureConfig,
    status_callback: StatusCallback | None = None,
) -> dict[str, object]:
    _emit(status_callback, "Inspecting browser pages...")

    with sync_playwright() as playwright:
        browser = _connect_browser(playwright, config)
        try:
            page_infos = _scan_browser_pages(browser)
            page = _resolve_platform_page(browser, config, status_callback, ensure_pool_page=False)
            selected_info = _summarize_page(page)
            dom_counts = page.evaluate(
                """
                () => ({
                  listCount: document.querySelectorAll('.left-panel .panel-body .question-card').length,
                  previewCount: document.querySelectorAll('.question-preview .preview-body').length,
                  sectionCount: document.querySelectorAll('.question-preview .preview-section').length,
                  hash: window.location.hash || '',
                })
                """
            )
        finally:
            browser.close()

    diagnostics = {
        "selected_title": selected_info["title"],
        "selected_url": selected_info["url"],
        "selected_reason": "Matched the platform tab",
        "list_item_selector": config.list_item_selector,
        "list_item_count": int(dom_counts.get("listCount") or 0),
        "preview_root_selector": config.preview_root_selector,
        "preview_root_count": int(dom_counts.get("previewCount") or 0),
        "section_selector": config.section_selector,
        "section_count": int(dom_counts.get("sectionCount") or 0),
        "page_count": len(page_infos),
        "candidates": page_infos,
    }
    _emit(status_callback, f"Inspection finished: {diagnostics['list_item_count']} visible question cards.")
    return diagnostics


def capture_current_question(
    config: CaptureConfig,
    output_root: str | Path,
    status_callback: StatusCallback | None = None,
) -> Path:
    return fetch_pool_questions(
        config=config,
        output_root=output_root,
        status_callback=status_callback,
        question_limit=1,
        title="Current pool question",
    )


def capture_current_page(
    config: CaptureConfig,
    output_root: str | Path,
    status_callback: StatusCallback | None = None,
) -> Path:
    return fetch_pool_questions(
        config=config,
        output_root=output_root,
        status_callback=status_callback,
        question_limit=config.question_limit,
        title="Pool 1 live questions",
    )


def fetch_pool_questions(
    config: CaptureConfig,
    output_root: str | Path,
    status_callback: StatusCallback | None = None,
    question_limit: int = 0,
    title: str = "Pool 1 live questions",
) -> Path:
    _emit(status_callback, "Fetching pool 1 questions from the live site...")
    output_root = Path(output_root).resolve()
    json_path = output_root / "latest_questions.json"

    with sync_playwright() as playwright:
        browser = _connect_browser(playwright, config)
        try:
            page = _resolve_platform_page(browser, config, status_callback, ensure_pool_page=True)
            payload = _fetch_pool_payload(page, status_callback)
        finally:
            browser.close()

    saved_count = save_pool_payload(payload, output_root, question_limit=question_limit, title=title)[1]
    _emit(status_callback, f"Loaded {saved_count} live questions from pool 1.")
    return json_path


def claim_pool_question(
    config: CaptureConfig,
    task_id: str,
    status_callback: StatusCallback | None = None,
) -> None:
    if not task_id.strip():
        raise CaptureError("The current question does not have a task ID, so it cannot be claimed.")

    _emit(status_callback, "Claiming the selected question...")
    with sync_playwright() as playwright:
        browser = _connect_browser(playwright, config)
        try:
            page = _resolve_platform_page(browser, config, status_callback, ensure_pool_page=True)
            module_url = _resolve_claim_module_url(page)
            result = page.evaluate(
                """
                async ({ moduleUrl, poolId, taskId }) => {
                  try {
                    const claimModule = await import(moduleUrl);
                    await claimModule.t.claimQuestion(taskId, { poolId });
                    return { ok: true };
                  } catch (error) {
                    return {
                      ok: false,
                      code: Number(error?.code || 0),
                      message: error?.message || String(error),
                    };
                  }
                }
                """,
                {
                    "moduleUrl": module_url,
                    "poolId": POOL_ID,
                    "taskId": task_id.strip(),
                },
            )
        finally:
            browser.close()

    if not result.get("ok"):
        raise CaptureError(_format_claim_error(int(result.get("code") or 0), str(result.get("message") or "")))

    _emit(status_callback, "Question claimed successfully.")


def save_pool_payload(
    payload: dict[str, object],
    output_root: str | Path,
    *,
    question_limit: int = 0,
    title: str = "Pool 1 live questions",
) -> tuple[Path, int]:
    output_root = Path(output_root).resolve()
    json_path, assets_dir = _prepare_output_root(output_root)

    questions, next_cache, next_signatures = _build_questions_from_payload(payload, assets_dir, question_limit)
    _update_session_cache(next_cache, next_signatures)
    _prune_assets_dir(output_root, questions)

    question_set = QuestionSet(
        title=str(payload.get("pool_name") or title),
        source_path=json_path,
        questions=questions,
    )
    save_question_set(question_set, json_path)
    return json_path, len(questions)


def format_claim_error(code: int, message: str) -> str:
    return _format_claim_error(code, message)


def _connect_browser(playwright, config: CaptureConfig):
    try:
        return playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{config.debug_port}")
    except PlaywrightError as exc:
        raise CaptureError(
            "Could not connect to the browser. Please click 'Open Browser' first and keep that browser window open."
        ) from exc


def _resolve_platform_page(
    browser,
    config: CaptureConfig,
    status_callback: StatusCallback | None,
    *,
    ensure_pool_page: bool,
):
    candidates = []
    for context in browser.contexts:
        for page in context.pages:
            if page.is_closed():
                continue
            if _is_internal_page(page.url or ""):
                continue
            candidates.append(page)

    if browser.contexts:
        context = browser.contexts[0]
    else:
        raise CaptureError("The browser has no active context. Please open a normal tab first.")

    page = None
    for candidate in candidates:
        url = (candidate.url or "").strip()
        if "/videoMachiningPlatform" in url:
            page = candidate
            break

    if page is None:
        page = context.new_page()

    page.bring_to_front()
    current_url = (page.url or "").strip()
    needs_navigation = not current_url or current_url in {"about:blank", "data:,"}
    if ensure_pool_page and f"/claim/pools/{POOL_ID}" not in current_url:
        needs_navigation = True

    if needs_navigation:
        _emit(status_callback, "Opening the pool 1 page in the logged-in browser session...")
        page.goto(POOL_PAGE_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)

    if "/login" in (page.url or ""):
        raise CaptureError("The browser session is not logged in yet. Please log in once in the opened browser.")

    return page


def _scan_browser_pages(browser) -> list[dict[str, object]]:
    pages: list[dict[str, object]] = []
    for context in browser.contexts:
        for page in context.pages:
            if page.is_closed():
                continue
            if _is_internal_page(page.url or ""):
                continue
            pages.append(_summarize_page(page))
    return pages


def _summarize_page(page) -> dict[str, object]:
    try:
        title = str(page.title() or "").strip()
    except PlaywrightError:
        title = ""
    return {
        "title": title,
        "url": str(page.url or "").strip() or "about:blank",
    }


def _fetch_pool_payload(page, status_callback: StatusCallback | None) -> dict[str, object]:
    module_url = _resolve_claim_module_url(page)
    result = page.evaluate(
        """
        async ({ moduleUrl, poolId }) => {
          try {
            const claimModule = await import(moduleUrl);
            const pools = await claimModule.t.getPoolList();
            const questions = await claimModule.t.getQuestionList(poolId);
            const toText = (html) => {
              if (!html) return '';
              const div = document.createElement('div');
              div.innerHTML = html;
              return (div.innerText || div.textContent || '').trim();
            };
            const pool = Array.isArray(pools)
              ? pools.find((item) => Number(item.poolId) === Number(poolId)) || null
              : null;
            return {
              ok: true,
              poolName: pool?.poolName || '',
              currentHolding: Number(pool?.currentHolding || 0),
              holdingLimit: Number(pool?.holdingLimit || 0),
              questions: Array.isArray(questions)
                ? questions.map((question) => ({
                    taskId: String(question.taskId || ''),
                    topicId: String(question.topicId || ''),
                    poolId: Number(question.poolId || poolId || 0),
                    subjectName: String(question.subjectName || ''),
                    phaseName: String(question.phaseName || ''),
                    gradeName: String(question.gradeName || ''),
                    poolTypeName: String(question.poolTypeName || ''),
                    timeliness: question.timeliness == null ? null : Number(question.timeliness),
                    stemText: toText(question.guidLearnQuestion?.content?.html || ''),
                    stemImg: String(question.guidLearnQuestion?.content?.img || ''),
                  }))
                : [],
            };
          } catch (error) {
            return {
              ok: false,
              code: Number(error?.code || 0),
              message: error?.message || String(error),
            };
          }
        }
        """,
        {
            "moduleUrl": module_url,
            "poolId": POOL_ID,
        },
    )

    if not result.get("ok"):
        raise CaptureError(
            "Live pool fetch failed: " + _format_claim_error(int(result.get("code") or 0), str(result.get("message") or ""))
        )

    count = len(result.get("questions") or [])
    _emit(
        status_callback,
        f"Pool 1 live fetch succeeded. Available questions: {count}. Holding: {result.get('currentHolding', 0)}/{result.get('holdingLimit', 0)}.",
    )
    return {
        "pool_name": result.get("poolName") or "Pool 1 live questions",
        "current_holding": int(result.get("currentHolding") or 0),
        "holding_limit": int(result.get("holdingLimit") or 0),
        "questions": result.get("questions") or [],
    }


def _build_questions_from_payload(
    payload: dict[str, object],
    assets_dir: Path,
    question_limit: int,
) -> tuple[list[Question], dict[str, Question], dict[str, str]]:
    raw_questions = list(payload.get("questions") or [])
    if question_limit > 0:
        raw_questions = raw_questions[:question_limit]

    questions: list[Question] = []
    next_cache: dict[str, Question] = {}
    next_signatures: dict[str, str] = {}
    output_root = assets_dir.parent

    for index, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict):
            continue

        cache_key = _question_cache_key(raw_question)
        signature = _question_signature(raw_question)
        cached_question = _SESSION_QUESTION_CACHE.get(cache_key)
        cached_signature = _SESSION_SIGNATURE_CACHE.get(cache_key)

        if cached_question and cached_signature == signature and _question_cache_usable(cached_question, output_root):
            question = _clone_cached_question(cached_question, raw_question, index)
        else:
            question = _build_question(index, raw_question, assets_dir)

        questions.append(question)
        if cache_key:
            next_cache[cache_key] = _clone_question_for_cache(question)
            next_signatures[cache_key] = signature

    return questions, next_cache, next_signatures


def _build_question(order_id: int, raw_question: dict[str, object], assets_dir: Path) -> Question:
    task_id = str(raw_question.get("taskId") or "").strip()
    topic_id = str(raw_question.get("topicId") or "").strip()
    source_id = topic_id or task_id or f"pool1-{order_id}"
    stem_text = str(raw_question.get("stemText") or "").strip()
    stem_img = str(raw_question.get("stemImg") or "").strip()

    blocks: list[ContentBlock] = []
    if stem_text:
        blocks.append(ContentBlock(block_type="text", value=stem_text))

    if stem_img:
        asset_name = f"{_safe_asset_key(source_id)}_stem{_guess_extension(stem_img)}"
        asset_path = assets_dir / asset_name
        if _download_asset(stem_img, asset_path):
            blocks.append(ContentBlock(block_type="image", value=f"assets/{asset_name}"))
        elif not blocks:
            blocks.append(ContentBlock(block_type="text", value="[Stem image could not be downloaded]"))

    if not blocks:
        blocks.append(ContentBlock(block_type="text", value="[No visible stem content]"))

    title = stem_text.splitlines()[0][:60] if stem_text else (topic_id or task_id or f"Question {order_id}")
    tags = [
        value
        for value in [
            str(raw_question.get("subjectName") or "").strip(),
            str(raw_question.get("phaseName") or "").strip(),
            str(raw_question.get("gradeName") or "").strip(),
            str(raw_question.get("poolTypeName") or "").strip(),
        ]
        if value
    ]

    timeliness = raw_question.get("timeliness")
    timeliness_hours = int(timeliness) if isinstance(timeliness, (int, float)) else None

    return Question(
        order_id=order_id,
        source_id=source_id,
        task_id=task_id,
        topic_id=topic_id,
        pool_id=int(raw_question.get("poolId") or 0),
        title=title,
        subject_name=str(raw_question.get("subjectName") or "").strip(),
        phase_name=str(raw_question.get("phaseName") or "").strip(),
        grade_name=str(raw_question.get("gradeName") or "").strip(),
        pool_type_name=str(raw_question.get("poolTypeName") or "").strip(),
        timeliness_hours=timeliness_hours,
        tags=tags,
        sections=[Section(label="Stem", blocks=blocks)],
    )


def _question_cache_key(raw_question: dict[str, object]) -> str:
    topic_id = str(raw_question.get("topicId") or "").strip()
    task_id = str(raw_question.get("taskId") or "").strip()
    return topic_id or task_id


def _question_signature(raw_question: dict[str, object]) -> str:
    return "|".join(
        [
            str(raw_question.get("topicId") or "").strip(),
            str(raw_question.get("stemText") or "").strip(),
            str(raw_question.get("stemImg") or "").strip(),
        ]
    )


def _question_cache_usable(question: Question, output_root: Path) -> bool:
    for section in question.sections:
        for block in section.blocks:
            if block.block_type != "image":
                continue
            image_path = Path(block.value)
            if not image_path.is_absolute():
                image_path = (output_root / image_path).resolve()
            if not image_path.exists():
                return False
    return True


def _clone_cached_question(cached_question: Question, raw_question: dict[str, object], order_id: int) -> Question:
    timeliness = raw_question.get("timeliness")
    timeliness_hours = int(timeliness) if isinstance(timeliness, (int, float)) else None
    topic_id = str(raw_question.get("topicId") or "").strip()
    task_id = str(raw_question.get("taskId") or "").strip()
    tags = [
        value
        for value in [
            str(raw_question.get("subjectName") or "").strip(),
            str(raw_question.get("phaseName") or "").strip(),
            str(raw_question.get("gradeName") or "").strip(),
            str(raw_question.get("poolTypeName") or "").strip(),
        ]
        if value
    ]

    return Question(
        order_id=order_id,
        source_id=topic_id or task_id or cached_question.source_id,
        task_id=task_id,
        topic_id=topic_id,
        pool_id=int(raw_question.get("poolId") or cached_question.pool_id or 0),
        title=cached_question.title,
        subject_name=str(raw_question.get("subjectName") or "").strip(),
        phase_name=str(raw_question.get("phaseName") or "").strip(),
        grade_name=str(raw_question.get("gradeName") or "").strip(),
        pool_type_name=str(raw_question.get("poolTypeName") or "").strip(),
        timeliness_hours=timeliness_hours,
        tags=tags,
        sections=_clone_sections(cached_question.sections),
    )


def _clone_question_for_cache(question: Question) -> Question:
    return Question(
        order_id=question.order_id,
        source_id=question.source_id,
        task_id=question.task_id,
        topic_id=question.topic_id,
        pool_id=question.pool_id,
        title=question.title,
        subject_name=question.subject_name,
        phase_name=question.phase_name,
        grade_name=question.grade_name,
        pool_type_name=question.pool_type_name,
        timeliness_hours=question.timeliness_hours,
        tags=list(question.tags),
        sections=_clone_sections(question.sections),
    )


def _clone_sections(sections: list[Section]) -> list[Section]:
    return [
        Section(
            label=section.label,
            blocks=[ContentBlock(block_type=block.block_type, value=block.value) for block in section.blocks],
        )
        for section in sections
    ]


def _update_session_cache(next_cache: dict[str, Question], next_signatures: dict[str, str]) -> None:
    global _SESSION_QUESTION_CACHE, _SESSION_SIGNATURE_CACHE
    _SESSION_QUESTION_CACHE = next_cache
    _SESSION_SIGNATURE_CACHE = next_signatures


def _prune_assets_dir(output_root: Path, questions: list[Question]) -> None:
    assets_dir = output_root / "assets"
    if not assets_dir.exists():
        return

    keep_paths: set[Path] = set()
    for question in questions:
        for section in question.sections:
            for block in section.blocks:
                if block.block_type != "image":
                    continue
                image_path = Path(block.value)
                if not image_path.is_absolute():
                    image_path = (output_root / image_path).resolve()
                keep_paths.add(image_path)

    for file_path in assets_dir.iterdir():
        if file_path.is_file() and file_path.resolve() not in keep_paths:
            file_path.unlink(missing_ok=True)


def _format_claim_error(code: int, message: str) -> str:
    if code == 42001:
        return "This question was already claimed by another teacher. Please refresh and try another one."
    if code == 42002:
        return "You have reached the holding limit for this pool. Finish existing questions first."
    if code == 42003:
        return "This question no longer exists or has been removed."
    if code == 42004:
        return "The pool is currently closed."
    if message:
        return message
    return "Unknown claim error."


def _resolve_claim_module_url(page) -> str:
    return str(
        page.evaluate(
            """
            async (fallbackUrl) => {
              const moduleScript = Array.from(document.scripts).find((script) => {
                return script.type === 'module' && script.src && /index-[A-Za-z0-9_-]+\\.js/.test(script.src);
              });
              if (!moduleScript?.src) {
                return fallbackUrl;
              }
              try {
                const source = await fetch(moduleScript.src, { credentials: 'include' }).then((response) => response.text());
                const match = source.match(/\\.\\/((?:claim|claim-[A-Za-z0-9_-]+)\\.js)/);
                if (match?.[1]) {
                  return new URL(match[1], moduleScript.src).href;
                }
              } catch (error) {
              }
              return fallbackUrl;
            }
            """,
            CLAIM_MODULE_URL,
        )
    )


def _prepare_output_root(output_root: Path) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    assets_dir = output_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "latest_questions.json"
    return json_path, assets_dir


def _resolve_profile_dir(config: CaptureConfig, app_home: str | Path) -> Path:
    profile_dir = Path(config.profile_dir.strip() or ".browser_profile")
    if profile_dir.is_absolute():
        return profile_dir
    return Path(app_home).resolve() / profile_dir


def _safe_asset_key(value: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in value).strip("_")
    return safe[:60] or "question"


def _guess_extension(url: str) -> str:
    lowered = url.lower()
    for extension in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"):
        if lowered.endswith(extension):
            return extension
    return ".png"


def _download_asset(url: str, destination: Path) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            destination.write_bytes(response.read())
        return True
    except Exception:
        return False


def _emit(status_callback: StatusCallback | None, message: str) -> None:
    if status_callback:
        status_callback(message)


def _debug_endpoint_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _is_internal_page(url: str) -> bool:
    return url.startswith(("chrome://", "edge://", "devtools://"))
