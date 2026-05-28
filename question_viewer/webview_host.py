from __future__ import annotations

import argparse
from pathlib import Path

import webview


MASK_BYPASS_CSS = """
html, body, * {
  user-select: text !important;
  -webkit-user-select: text !important;
}

.preview-mask,
[class*="preview-mask"],
.is-masked,
[class*="is-masked"] {
  display: none !important;
  visibility: hidden !important;
  opacity: 0 !important;
  pointer-events: none !important;
}

.question-preview,
.preview-body,
.preview-body *,
.section-content,
.section-content * {
  filter: none !important;
  -webkit-filter: none !important;
  mask: none !important;
  -webkit-mask: none !important;
}
"""


MASK_BYPASS_JS = """
(() => {
  const reveal = () => {
    document.querySelectorAll('.preview-mask, [class*="preview-mask"]').forEach((node) => node.remove());
    document.querySelectorAll('.is-masked, [class*="is-masked"]').forEach((node) => {
      node.classList.remove('is-masked');
      node.style.filter = 'none';
      node.style.webkitFilter = 'none';
      node.style.mask = 'none';
      node.style.webkitMask = 'none';
      node.style.userSelect = 'text';
      node.style.webkitUserSelect = 'text';
    });
  };

  reveal();

  if (!window.__eqpMaskBypassInstalled) {
    window.__eqpMaskBypassInstalled = true;
    window.addEventListener('hashchange', () => setTimeout(reveal, 150));
    document.addEventListener('readystatechange', reveal);
    window.__eqpMaskBypassTimer = setInterval(reveal, 1000);
  }

  return true;
})()
"""


def run_webview_host(start_url: str, debug_port: int, profile_dir: str | Path) -> None:
    profile_path = Path(profile_dir).expanduser().resolve()
    profile_path.mkdir(parents=True, exist_ok=True)

    webview.settings["REMOTE_DEBUGGING_PORT"] = int(debug_port)
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    window = webview.create_window(
        title="EasyQuestionPicker Browser",
        url=start_url,
        width=1360,
        height=900,
        min_size=(980, 680),
        background_color="#ffffff",
        text_select=True,
    )

    def apply_bypass(loaded_window: webview.Window) -> None:
        try:
            loaded_window.load_css(MASK_BYPASS_CSS)
        except Exception:
            pass

        try:
            loaded_window.evaluate_js(MASK_BYPASS_JS)
        except Exception:
            pass

    window.events.loaded += apply_bypass

    webview.start(
        gui="edgechromium",
        private_mode=False,
        storage_path=str(profile_path),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--webview-host", action="store_true")
    parser.add_argument("--url", required=True)
    parser.add_argument("--debug-port", type=int, required=True)
    parser.add_argument("--profile-dir", required=True)
    args = parser.parse_args(argv)
    run_webview_host(args.url, args.debug_port, args.profile_dir)

