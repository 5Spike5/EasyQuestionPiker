from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from question_viewer.browser_capture import (
    CaptureError,
    claim_pool_question,
    fetch_pool_questions,
    inspect_current_page,
    launch_debug_browser,
    reset_runtime_cache,
)
from question_viewer.capture_config import (
    CaptureConfig,
    load_capture_config,
    normalize_account_index,
    normalize_account_names,
    save_capture_config,
)
from question_viewer.loader import QuestionDataError, load_question_set
from question_viewer.models import Question, QuestionSet
from question_viewer.paths import get_app_home


APP_TITLE = "EasyQuestionPicker"
WINDOW_BG = "#f3f6fb"
CARD_BG = "#ffffff"
PANEL_BG = "#f8fbff"
ACCENT = "#165dff"
ACCENT_HOVER = "#0f52e0"
ACCENT_SOFT = "#eaf1ff"
SECONDARY_BG = "#eef3f9"
SECONDARY_HOVER = "#e1ebf7"
SUCCESS_BG = "#eaf8f0"
SUCCESS_HOVER = "#dbf2e4"
SUCCESS_ACCENT = "#0a7f39"
TEXT_MAIN = "#1c2533"
TEXT_MUTED = "#64748b"
BORDER_SOFT = "#d9e3ef"
BORDER_STRONG = "#c8d5e6"
INPUT_BG = "#fbfdff"
ALT_ROW_BG = "#f5f9ff"
NEW_ROW_BG = "#e9fff2"
BUILT_IN_PROFILE_DIRNAME = ".webview_profile"
WARN_ORANGE = "#d97706"
ERROR_RED = "#c81e1e"
SUCCESS_GREEN = SUCCESS_ACCENT


class ConfigDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: CaptureConfig) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.configure(bg=CARD_BG)
        self.result: CaptureConfig | None = None
        self.initial_config = config

        self.browser_name_var = tk.StringVar(value=config.browser_name)
        self.start_url_var = tk.StringVar(value=config.start_url)
        self.browser_path_var = tk.StringVar(value=config.browser_executable_path)
        self.debug_port_var = tk.StringVar(value=str(config.debug_port))
        self.profile_dir_var = tk.StringVar(value=config.profile_dir)
        self.auto_sync_delay_var = tk.StringVar(value=str(config.auto_sync_delay_ms))
        self.question_limit_var = tk.StringVar(value=str(config.question_limit))
        self.account_name_vars = [tk.StringVar(value=name) for name in config.account_names]

        self._build()
        self.transient(parent)
        self.grab_set()
        self.focus_set()

    def _build(self) -> None:
        container = tk.Frame(self, bg=CARD_BG, padx=20, pady=18)
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text="Browser Settings",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        hint = (
            "Preferred flow: Open Built-in Browser, log in there once, then use Refresh Live.\n"
            "Fallback flow: Open Browser still launches an external browser session if you want it.\n"
            "Each account slot uses its own port and its own login profile."
        )
        tk.Label(
            container,
            text=hint,
            bg=CARD_BG,
            fg=TEXT_MUTED,
            justify="left",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        fields = [
            ("Browser", self._browser_type_widget(container)),
            ("Start URL", self._entry(container, self.start_url_var)),
            ("Browser Path", self._entry(container, self.browser_path_var)),
            ("Base Debug Port", self._entry(container, self.debug_port_var, width=20)),
            ("Browser Profile Root", self._entry(container, self.profile_dir_var)),
            ("Auto Sync Interval (ms)", self._entry(container, self.auto_sync_delay_var, width=20)),
            ("Max Questions", self._entry(container, self.question_limit_var, width=20)),
        ]

        for index, variable in enumerate(self.account_name_vars, start=1):
            fields.append((f"Account {index} Name", self._entry(container, variable, width=40)))

        for row_index, (label, widget) in enumerate(fields, start=2):
            tk.Label(
                container,
                text=label,
                bg=CARD_BG,
                fg=TEXT_MAIN,
                font=("Microsoft YaHei UI", 10),
            ).grid(row=row_index, column=0, sticky="w", pady=6, padx=(0, 12))
            widget.grid(row=row_index, column=1, sticky="ew", pady=6)

        container.grid_columnconfigure(1, weight=1)

        footer = tk.Frame(container, bg=CARD_BG)
        footer.grid(row=len(fields) + 3, column=0, columnspan=2, sticky="e", pady=(14, 0))

        tk.Button(
            footer,
            text="Cancel",
            command=self.destroy,
            bg="#eef2f6",
            fg=TEXT_MAIN,
            relief="flat",
            padx=16,
            pady=7,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            footer,
            text="Save",
            command=self._save,
            bg=ACCENT,
            fg="white",
            relief="flat",
            padx=16,
            pady=7,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="right")

    def _browser_type_widget(self, parent: tk.Widget) -> ttk.Combobox:
        return ttk.Combobox(
            parent,
            textvariable=self.browser_name_var,
            values=["auto", "chrome", "edge"],
            width=18,
            state="readonly",
        )

    def _entry(self, parent: tk.Widget, variable: tk.StringVar, width: int = 72) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d0d8e4",
            highlightcolor=ACCENT,
            font=("Microsoft YaHei UI", 10),
        )

    def _save(self) -> None:
        try:
            config = CaptureConfig(
                start_url=self.start_url_var.get().strip(),
                browser_name=self.browser_name_var.get().strip() or "auto",
                browser_executable_path=self.browser_path_var.get().strip(),
                debug_port=int(self.debug_port_var.get().strip() or "9222"),
                profile_dir=self.profile_dir_var.get().strip() or ".browser_profile",
                list_item_selector=self.initial_config.list_item_selector,
                list_item_title_selector=self.initial_config.list_item_title_selector,
                preview_root_selector=self.initial_config.preview_root_selector,
                section_selector=self.initial_config.section_selector,
                section_label_selector=self.initial_config.section_label_selector,
                section_content_selector=self.initial_config.section_content_selector,
                click_wait_ms=self.initial_config.click_wait_ms,
                auto_sync_delay_ms=max(600, int(self.auto_sync_delay_var.get().strip() or "1500")),
                question_limit=int(self.question_limit_var.get().strip() or "0"),
                active_account_index=normalize_account_index(self.initial_config.active_account_index),
                account_names=normalize_account_names([variable.get() for variable in self.account_name_vars]),
            )
        except ValueError:
            messagebox.showerror(
                APP_TITLE,
                "Base debug port, auto sync interval, and max questions must be integers.",
                parent=self,
            )
            return

        self.result = config
        self.destroy()


@dataclass(slots=True)
class AccountViewState:
    question_set: QuestionSet | None = None
    last_source_path: Path | None = None
    highlight_question_ids: set[str] = field(default_factory=set)
    current_user_name: str = ""
    current_holding: int | None = None
    holding_limit: int | None = None


class QuestionViewerApp:
    def __init__(self) -> None:
        self.app_home = get_app_home()
        self.config_path = self.app_home / "capture_config.json"
        self.capture_output_dir = self.app_home / "captured"
        self.capture_config = load_capture_config(self.config_path)
        self.capture_config.account_names = normalize_account_names(self.capture_config.account_names)
        self.capture_config.active_account_index = normalize_account_index(self.capture_config.active_account_index)
        self.built_in_profile_root = self.app_home / BUILT_IN_PROFILE_DIRNAME
        self.built_in_processes: dict[int, subprocess.Popen] = {}
        self.external_browser_processes: dict[int, subprocess.Popen] = {}
        self.account_views: list[AccountViewState] = [AccountViewState() for _ in range(len(self.capture_config.account_names))]
        self.public_pool_snapshot: QuestionSet | None = None

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1280x860")
        self.root.minsize(1040, 720)
        self.root.configure(bg=WINDOW_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(
            "Treeview",
            rowheight=40,
            font=("Microsoft YaHei UI", 10),
            background=CARD_BG,
            fieldbackground=CARD_BG,
            foreground=TEXT_MAIN,
            borderwidth=0,
        )
        self.style.configure(
            "Treeview.Heading",
            font=("Microsoft YaHei UI", 10, "bold"),
            background=PANEL_BG,
            foreground=TEXT_MAIN,
            relief="flat",
            borderwidth=0,
        )
        self.style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT_MAIN)])
        self.style.map(
            "Treeview.Heading",
            background=[("active", PANEL_BG)],
            relief=[("active", "flat")],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT_MAIN,
            borderwidth=0,
            arrowsize=14,
            padding=6,
        )

        self.current_set: QuestionSet | None = None
        self.filtered_questions: list[Question] = []
        self.selected_question: Question | None = None
        self.last_source_path: Path | None = None
        self.highlight_question_ids: set[str] = set()
        self.preview_images: list[ImageTk.PhotoImage] = []
        self.busy = False
        self.ui_queue: queue.Queue = queue.Queue()
        self.account_selector_updating = False
        self.auto_sync_after_ids: dict[int, str] = {}
        self.auto_sync_in_progress_slots: set[int] = set()

        self.search_var = tk.StringVar()
        self.account_var = tk.StringVar()
        self.account_slot_info_var = tk.StringVar()
        self.account_user_info_var = tk.StringVar()
        self.account_holding_info_var = tk.StringVar()
        self.account_session_info_var = tk.StringVar()
        self.auto_sync_info_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Open Built-in Browser, log in once, then click Refresh Live."
        )
        self.title_var = tk.StringVar(value=self._default_pool_title())

        self.action_buttons: list[tk.Button] = []
        self.action_button_styles: dict[tk.Button, dict[str, str]] = {}
        self.claim_button: tk.Button | None = None
        self.account_slot_value_label: tk.Label | None = None
        self.account_user_value_label: tk.Label | None = None
        self.account_holding_value_label: tk.Label | None = None
        self.account_session_value_label: tk.Label | None = None
        self.search_entry: tk.Entry | None = None
        reset_runtime_cache(self.capture_output_dir)
        self._build_layout()
        self._refresh_account_selector()
        self.root.after(120, self._process_ui_queue)

    def _build_layout(self) -> None:
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        header_shell = tk.Frame(self.root, bg=WINDOW_BG, padx=18, pady=18)
        header_shell.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header_shell.grid_columnconfigure(0, weight=1)

        toolbar = tk.Frame(
            header_shell,
            bg=CARD_BG,
            padx=18,
            pady=18,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)

        top_row = tk.Frame(toolbar, bg=CARD_BG)
        top_row.grid(row=0, column=0, sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)

        title_frame = tk.Frame(top_row, bg=CARD_BG)
        title_frame.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_frame,
            text=APP_TITLE,
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_frame,
            text="Pool 1 assistant with multi-account cache, live polling, and direct claim actions.",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(6, 0))

        account_frame = tk.Frame(
            top_row,
            bg=PANEL_BG,
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        account_frame.grid(row=0, column=1, sticky="e", padx=(18, 0))
        account_frame.grid_columnconfigure(1, weight=1)

        tk.Label(
            account_frame,
            text="Active Account",
            bg=PANEL_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.account_selector = ttk.Combobox(
            account_frame,
            textvariable=self.account_var,
            state="readonly",
            width=28,
        )
        self.account_selector.grid(row=0, column=1, sticky="ew")
        self.account_selector.bind("<<ComboboxSelected>>", self._on_account_selected)

        actions_frame = tk.Frame(toolbar, bg=CARD_BG)
        actions_frame.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        for column in range(7):
            actions_frame.grid_columnconfigure(column, weight=1)

        self._add_action_button(actions_frame, "Built-in", self.open_built_in_browser, 0, variant="primary")
        self._add_action_button(actions_frame, "Browser", self.open_browser, 1, variant="secondary")
        self._add_action_button(actions_frame, "Refresh", self.refresh_live, 2, variant="primary")
        self._add_action_button(actions_frame, "Claim", self.claim_selected, 3, variant="success")
        self._add_action_button(actions_frame, "Inspect", self.inspect_page, 4, variant="secondary")
        self._add_action_button(actions_frame, "Import", self.open_json, 5, variant="secondary")
        self._add_action_button(actions_frame, "Settings", self.open_settings, 6, variant="secondary")

        self._build_account_status_bar(toolbar)

        search_frame = tk.Frame(
            toolbar,
            bg=PANEL_BG,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        search_frame.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        search_frame.grid_columnconfigure(1, weight=1)

        tk.Label(
            search_frame,
            text="Search",
            bg=PANEL_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            relief="flat",
            bg=INPUT_BG,
            fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN,
            highlightthickness=1,
            highlightbackground=BORDER_STRONG,
            highlightcolor=ACCENT,
            font=("Microsoft YaHei UI", 10),
        )
        self.search_entry.grid(row=0, column=1, sticky="ew", ipady=7)
        self.search_entry.bind("<KeyRelease>", lambda _event: self.apply_filter())

        auto_sync_badge = tk.Label(
            search_frame,
            textvariable=self.auto_sync_info_var,
            bg=ACCENT_SOFT,
            fg=ACCENT,
            padx=12,
            pady=7,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        auto_sync_badge.grid(row=0, column=2, sticky="e", padx=(12, 0))

        body = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            bg=WINDOW_BG,
            bd=0,
            relief="flat",
        )
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))

        left_panel = tk.Frame(
            body,
            bg=CARD_BG,
            padx=16,
            pady=16,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        right_panel = tk.Frame(
            body,
            bg=CARD_BG,
            padx=0,
            pady=0,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )

        body.add(left_panel, minsize=320, width=380)
        body.add(right_panel, minsize=580)

        self._build_question_list(left_panel)
        self._build_preview_panel(right_panel)

        status_bar = tk.Frame(
            self.root,
            bg=CARD_BG,
            padx=18,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        status_bar.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        tk.Label(
            status_bar,
            textvariable=self.status_var,
            bg=CARD_BG,
            fg=TEXT_MUTED,
            anchor="w",
            justify="left",
            font=("Microsoft YaHei UI", 10),
        ).pack(fill="x")

    def _add_action_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        column: int,
        row: int = 0,
        sticky: str = "w",
        variant: str = "secondary",
    ) -> None:
        palette = self._action_button_palette(variant)
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=palette["bg"],
            fg=palette["fg"],
            activebackground=palette["hover"],
            activeforeground=palette["fg"],
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=("Microsoft YaHei UI", 9, "bold"),
            cursor="hand2",
            highlightthickness=0,
        )
        button.grid(row=row, column=column, padx=4, pady=0, sticky="ew")
        button.bind("<Enter>", lambda _event, current=button: self._set_action_button_hover(current, hovered=True))
        button.bind("<Leave>", lambda _event, current=button: self._set_action_button_hover(current, hovered=False))
        self.action_buttons.append(button)
        self.action_button_styles[button] = palette
        if text == "Claim":
            self.claim_button = button

    def _action_button_palette(self, variant: str) -> dict[str, str]:
        if variant == "primary":
            return {"bg": ACCENT, "hover": ACCENT_HOVER, "fg": "white"}
        if variant == "success":
            return {"bg": SUCCESS_ACCENT, "hover": "#086a30", "fg": "white"}
        return {"bg": SECONDARY_BG, "hover": SECONDARY_HOVER, "fg": TEXT_MAIN}

    def _set_action_button_hover(self, button: tk.Button, *, hovered: bool) -> None:
        if str(button.cget("state")) != "normal":
            return
        palette = self.action_button_styles.get(button)
        if not palette:
            return
        button.configure(bg=palette["hover"] if hovered else palette["bg"])

    def _build_question_list(self, parent: tk.Frame) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        tk.Label(
            parent,
            text="Pool 1 Questions",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            parent,
            textvariable=self.title_var,
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(6, 10))

        tree_wrap = tk.Frame(parent, bg=CARD_BG)
        tree_wrap.grid(row=2, column=0, sticky="nsew")
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_wrap,
            columns=("index", "topic", "summary"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("index", text="#")
        self.tree.heading("topic", text="Topic ID")
        self.tree.heading("summary", text="Stem")
        self.tree.column("index", width=60, anchor="center", stretch=False)
        self.tree.column("topic", width=110, anchor="center", stretch=False)
        self.tree.column("summary", width=220, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.tag_configure("even", background=CARD_BG)
        self.tree.tag_configure("odd", background=ALT_ROW_BG)
        self.tree.tag_configure("new", background=NEW_ROW_BG)

        scrollbar = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

    def _build_preview_panel(self, parent: tk.Frame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        header = tk.Frame(parent, bg=CARD_BG, padx=18, pady=16)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="Live Preview",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.preview_subtitle = tk.Label(
            header,
            text="After Refresh Live, select a question on the left to preview it.",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 10),
        )
        self.preview_subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

        canvas_wrap = tk.Frame(parent, bg=CARD_BG)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.grid_rowconfigure(0, weight=1)
        canvas_wrap.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(canvas_wrap, bg=PANEL_BG, bd=0, highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew", padx=16, pady=(0, 16))

        preview_scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.preview_canvas.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns", pady=(0, 16))
        self.preview_canvas.configure(yscrollcommand=preview_scroll.set)

        self.preview_inner = tk.Frame(self.preview_canvas, bg=PANEL_BG)
        self.preview_window = self.preview_canvas.create_window((0, 0), window=self.preview_inner, anchor="nw")
        self.preview_inner.bind("<Configure>", self._sync_preview_scroll)
        self.preview_canvas.bind("<Configure>", self._resize_preview_inner)
        self.preview_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._draw_empty_state()

    def _build_account_status_bar(self, parent: tk.Frame) -> None:
        status_card = tk.Frame(
            parent,
            bg=CARD_BG,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        status_card.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for column in range(4):
            status_card.grid_columnconfigure(column, weight=1)

        self.account_slot_value_label = self._build_account_status_item(
            status_card,
            column=0,
            title="Active Slot",
            value_var=self.account_slot_info_var,
            value_color=ACCENT,
        )
        self.account_user_value_label = self._build_account_status_item(
            status_card,
            column=1,
            title="User",
            value_var=self.account_user_info_var,
        )
        self.account_holding_value_label = self._build_account_status_item(
            status_card,
            column=2,
            title="Holding",
            value_var=self.account_holding_info_var,
        )
        self.account_session_value_label = self._build_account_status_item(
            status_card,
            column=3,
            title="Session",
            value_var=self.account_session_info_var,
        )

    def _build_account_status_item(
        self,
        parent: tk.Frame,
        *,
        column: int,
        title: str,
        value_var: tk.StringVar,
        value_color: str = TEXT_MAIN,
    ) -> tk.Label:
        item = tk.Frame(
            parent,
            bg=PANEL_BG,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        item.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0))

        tk.Label(
            item,
            text=title,
            bg=PANEL_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")

        value_label = tk.Label(
            item,
            textvariable=value_var,
            bg=PANEL_BG,
            fg=value_color,
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        value_label.pack(anchor="w", pady=(4, 0))
        return value_label

    def _account_display_values(self) -> list[str]:
        values: list[str] = []
        for index, name in enumerate(normalize_account_names(self.capture_config.account_names)):
            state = self._account_view_state(index)
            user_text = f" ({state.current_user_name})" if state.current_user_name else ""
            values.append(f"{index + 1}. {name}{user_text}")
        return values

    def _active_account_index(self) -> int:
        return normalize_account_index(self.capture_config.active_account_index)

    def _active_account_name(self) -> str:
        return normalize_account_names(self.capture_config.account_names)[self._active_account_index()]

    def _account_view_state(self, slot_index: int | None = None) -> AccountViewState:
        slot = self._active_account_index() if slot_index is None else normalize_account_index(slot_index)
        return self.account_views[slot]

    def _slot_debug_port(self, slot_index: int) -> int:
        return int(self.capture_config.debug_port or 9222) + slot_index

    def _slot_browser_profile_dir(self, slot_index: int) -> Path:
        base_profile_dir = Path(self.capture_config.profile_dir.strip() or ".browser_profile")
        if not base_profile_dir.is_absolute():
            base_profile_dir = self.app_home / base_profile_dir
        return base_profile_dir.resolve() / f"account_{slot_index + 1}"

    def _slot_webview_profile_dir(self, slot_index: int) -> Path:
        return (self.built_in_profile_root / f"account_{slot_index + 1}").resolve()

    def _slot_capture_config(self, slot_index: int | None = None) -> CaptureConfig:
        slot = self._active_account_index() if slot_index is None else normalize_account_index(slot_index)
        return replace(
            self.capture_config,
            debug_port=self._slot_debug_port(slot),
            profile_dir=str(self._slot_browser_profile_dir(slot)),
            active_account_index=slot,
            account_names=normalize_account_names(self.capture_config.account_names),
        )

    def _default_pool_title(self) -> str:
        return f"{self._active_account_name()}  |  Pool 1 not loaded"

    def _auto_sync_base_delay_ms(self) -> int:
        return max(600, int(self.capture_config.auto_sync_delay_ms or 1500))

    def _auto_sync_delay_ms(self, multiplier: float = 1.0, minimum: int = 600) -> int:
        return max(minimum, int(self._auto_sync_base_delay_ms() * multiplier))

    def _format_delay_label(self, delay_ms: int) -> str:
        seconds = delay_ms / 1000
        return f"{seconds:.1f}".rstrip("0").rstrip(".")

    def _update_auto_sync_info(self) -> None:
        self.auto_sync_info_var.set(f"Live Poll {self._format_delay_label(self._auto_sync_base_delay_ms())}s")

    def _resume_auto_sync_if_session_active(self, slot_index: int | None = None, delay_ms: int | None = None) -> None:
        slot = self._active_account_index() if slot_index is None else normalize_account_index(slot_index)
        if self._current_session_text(slot).startswith("Idle"):
            return
        self._schedule_auto_sync_for_slot(slot, delay_ms=delay_ms)

    def _current_holding_text(self, slot_index: int | None = None) -> str:
        state = self._account_view_state(slot_index)
        if state.current_holding is None or state.holding_limit is None:
            return "--/--"
        return f"{state.current_holding}/{state.holding_limit}"

    def _current_session_text(self, slot_index: int | None = None) -> str:
        slot = self._active_account_index() if slot_index is None else normalize_account_index(slot_index)
        built_in_process = self.built_in_processes.get(slot)
        if built_in_process and built_in_process.poll() is None:
            return f"Built-in / {self._slot_debug_port(slot)}"
        external_process = self.external_browser_processes.get(slot)
        if external_process and external_process.poll() is None:
            return f"Browser / {self._slot_debug_port(slot)}"
        return f"Idle / {self._slot_debug_port(slot)}"

    def _update_pool_title(self) -> None:
        if self.current_set:
            self.title_var.set(
                f"{self._active_account_name()}  |  {self.current_set.title}  |  {len(self.current_set.questions)} questions"
            )
        else:
            self.title_var.set(self._default_pool_title())

    def _refresh_account_selector(self) -> None:
        self.capture_config.account_names = normalize_account_names(self.capture_config.account_names)
        self.capture_config.active_account_index = self._active_account_index()
        values = self._account_display_values()
        self.account_selector_updating = True
        self.account_selector.configure(values=values)
        self.account_selector.current(self._active_account_index())
        self.account_var.set(values[self._active_account_index()])
        self.account_selector_updating = False
        active_state = self._account_view_state()
        self.account_slot_info_var.set(f"Slot {self._active_account_index() + 1} - {self._active_account_name()}")
        self.account_user_info_var.set(active_state.current_user_name or "not detected")
        self.account_holding_info_var.set(self._current_holding_text())
        self.account_session_info_var.set(self._current_session_text())
        self._update_auto_sync_info()
        self._update_account_status_colors()
        self._update_pool_title()

    def _update_account_status_colors(self) -> None:
        state = self._account_view_state()
        if self.account_slot_value_label:
            self.account_slot_value_label.configure(fg=ACCENT)

        if self.account_user_value_label:
            self.account_user_value_label.configure(
                fg=TEXT_MAIN if state.current_user_name else TEXT_MUTED
            )

        if self.account_holding_value_label:
            holding_color = TEXT_MUTED
            if state.current_holding is not None and state.holding_limit is not None:
                if state.holding_limit > 0 and state.current_holding >= state.holding_limit:
                    holding_color = ERROR_RED
                elif state.holding_limit > 0 and state.current_holding >= max(
                    state.holding_limit - 2,
                    int(state.holding_limit * 0.8),
                ):
                    holding_color = WARN_ORANGE
                else:
                    holding_color = TEXT_MAIN
            self.account_holding_value_label.configure(fg=holding_color)

        if self.account_session_value_label:
            session_text = self._current_session_text()
            if session_text.startswith("Built-in"):
                session_color = SUCCESS_GREEN
            elif session_text.startswith("Browser"):
                session_color = ACCENT
            else:
                session_color = TEXT_MUTED
            self.account_session_value_label.configure(fg=session_color)

    def _on_account_selected(self, _event=None) -> None:
        if self.account_selector_updating:
            return
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Please wait for the current task to finish before switching account.")
            self._refresh_account_selector()
            return

        selected_index = self.account_selector.current()
        if selected_index < 0:
            self._refresh_account_selector()
            return

        selected_index = normalize_account_index(selected_index)
        if selected_index == self._active_account_index():
            return

        self._cancel_auto_sync(self._active_account_index())
        self._store_active_account_view()
        self.capture_config.active_account_index = selected_index
        save_capture_config(self.config_path, self.capture_config)
        self._refresh_account_selector()
        self._restore_active_account_view()
        if not self._current_session_text().startswith("Idle"):
            self._schedule_auto_sync_for_slot(
                self._active_account_index(),
                delay_ms=self._auto_sync_delay_ms(0.8, minimum=900),
            )

    def _reset_loaded_questions(self, message: str) -> None:
        self.current_set = None
        self.filtered_questions = []
        self.selected_question = None
        self.last_source_path = None
        self.highlight_question_ids = set()
        self.search_var.set("")
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self._update_pool_title()
        self.preview_subtitle.configure(text="After Refresh Live, select a question on the left to preview it.")
        self._draw_empty_state(message)
        self.status_var.set(message)

    def _question_set_for_public_pool_cache(self, question_set: QuestionSet) -> QuestionSet:
        snapshot = deepcopy(question_set)
        snapshot.current_user_name = ""
        snapshot.current_holding = None
        snapshot.holding_limit = None
        return snapshot

    def _store_active_account_view(self) -> None:
        state = self._account_view_state()
        state.question_set = deepcopy(self.current_set) if self.current_set else None
        state.last_source_path = self.last_source_path
        state.highlight_question_ids = set(self.highlight_question_ids)
        if self.current_set:
            state.current_user_name = self.current_set.current_user_name
            state.current_holding = self.current_set.current_holding
            state.holding_limit = self.current_set.holding_limit

    def _apply_question_set_to_view(self, question_set: QuestionSet, highlight_question_ids: set[str] | None = None) -> None:
        self.current_set = deepcopy(question_set)
        self.last_source_path = self.current_set.source_path
        self.highlight_question_ids = set(highlight_question_ids or set())
        self.search_var.set("")
        self._update_pool_title()
        self.apply_filter(select_first=True)
        if self.current_set.questions:
            self.status_var.set(
                f"Showing cached pool for {self._active_account_name()}. Click Refresh if you want the latest live state."
            )
        else:
            self._draw_empty_state(f"No available questions are cached for {self._active_account_name()}.")

    def _restore_active_account_view(self) -> None:
        state = self._account_view_state()
        if state.question_set:
            self._apply_question_set_to_view(state.question_set, state.highlight_question_ids)
            self._refresh_account_selector()
            return

        if self.public_pool_snapshot:
            fallback = deepcopy(self.public_pool_snapshot)
            fallback.current_user_name = state.current_user_name
            fallback.current_holding = state.current_holding
            fallback.holding_limit = state.holding_limit
            self._apply_question_set_to_view(fallback, set())
            self.status_var.set(
                f"Switched to {self._active_account_name()}. Showing shared cached pool data; click Refresh to sync this account."
            )
            self._refresh_account_selector()
            return

        self._reset_loaded_questions(
            f"Switched to {self._active_account_name()}. Open or reuse its browser session, then click Refresh."
        )
        self._refresh_account_selector()

    def _schedule_auto_sync_for_slot(self, slot: int, delay_ms: int | None = None) -> None:
        slot = normalize_account_index(slot)
        self._cancel_auto_sync(slot)
        if not self.root.winfo_exists():
            return
        actual_delay = self._auto_sync_base_delay_ms() if delay_ms is None else max(600, int(delay_ms))
        self.auto_sync_after_ids[slot] = self.root.after(actual_delay, lambda: self._attempt_auto_sync(slot))

    def _cancel_auto_sync(self, slot: int | None = None) -> None:
        slot_indexes = list(self.auto_sync_after_ids) if slot is None else [normalize_account_index(slot)]
        for slot_index in slot_indexes:
            after_id = self.auto_sync_after_ids.pop(slot_index, None)
            if after_id and self.root.winfo_exists():
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
            self.auto_sync_in_progress_slots.discard(slot_index)

    def _attempt_auto_sync(self, slot: int) -> None:
        slot = normalize_account_index(slot)
        self.auto_sync_after_ids.pop(slot, None)

        if slot != self._active_account_index():
            return
        if self.busy:
            self._schedule_auto_sync_for_slot(slot, delay_ms=self._auto_sync_delay_ms(1.2))
            return
        if slot in self.auto_sync_in_progress_slots:
            return

        self.auto_sync_in_progress_slots.add(slot)
        config = self._slot_capture_config(slot)

        def wrapped() -> None:
            try:
                json_path = fetch_pool_questions(
                    config,
                    self.capture_output_dir,
                    None,
                    question_limit=self.capture_config.question_limit,
                    title="Pool 1 live questions",
                )
            except Exception as exc:
                self.ui_queue.put(("auto_sync_error", {"slot": slot, "exc": exc}, None))
            else:
                self.ui_queue.put(("auto_sync_done", {"slot": slot, "json_path": json_path}, None))

        threading.Thread(target=wrapped, daemon=True).start()

    def _handle_auto_sync_success(self, slot: int, json_path: Path) -> None:
        self.auto_sync_in_progress_slots.discard(slot)
        if slot != self._active_account_index():
            return
        self._load_file(json_path)
        self.status_var.set(
            f"Live poll updated {self._active_account_name()}. Username and pool cache are current."
        )
        self._schedule_auto_sync_for_slot(slot)

    def _handle_auto_sync_error(self, slot: int, exc: Exception) -> None:
        self.auto_sync_in_progress_slots.discard(slot)
        if slot != self._active_account_index():
            return

        message = str(exc).strip()
        lower_message = message.lower()
        retriable = isinstance(exc, CaptureError) and (
            "not logged in yet" in lower_message
            or "could not connect to the browser" in lower_message
            or "browser has no active context" in lower_message
        )

        if retriable:
            self.status_var.set(
                f"Waiting for login on {self._active_account_name()}... automatic sync will continue in the background."
            )
            self._schedule_auto_sync_for_slot(slot, delay_ms=self._auto_sync_delay_ms(1.5))
            return

        self.status_var.set(
            f"Automatic sync is waiting on {self._active_account_name()}: {message or 'temporary issue'}"
        )
        self._schedule_auto_sync_for_slot(slot, delay_ms=self._auto_sync_delay_ms(2.0))

    def open_settings(self) -> None:
        dialog = ConfigDialog(self.root, self.capture_config)
        self.root.wait_window(dialog)
        if dialog.result:
            previous_debug_port = self.capture_config.debug_port
            previous_profile_dir = self.capture_config.profile_dir
            previous_auto_sync_delay = self.capture_config.auto_sync_delay_ms
            self.capture_config = dialog.result
            save_capture_config(self.config_path, self.capture_config)
            self._refresh_account_selector()
            if (
                self.capture_config.debug_port != previous_debug_port
                or self.capture_config.profile_dir != previous_profile_dir
            ):
                self._stop_built_in_browser()
                self._stop_external_browser()
                self._refresh_account_selector()
                self.status_var.set("Settings saved. Reopen Built-in or Browser for the current account.")
            else:
                self.status_var.set(f"Settings saved: {self.config_path}")
            if self.capture_config.auto_sync_delay_ms != previous_auto_sync_delay and not self._current_session_text().startswith("Idle"):
                self._schedule_auto_sync_for_slot(self._active_account_index())

    def open_browser(self) -> None:
        self._cancel_auto_sync(self._active_account_index())
        self._run_background(
            start_message=f"Preparing browser for {self._active_account_name()}...",
            worker=self._launch_external_browser,
            on_success=lambda diagnostics: self._after_browser_ready("Browser", diagnostics),
        )

    def open_built_in_browser(self) -> None:
        self._cancel_auto_sync(self._active_account_index())
        self._run_background(
            start_message=f"Starting the built-in browser for {self._active_account_name()}...",
            worker=self._launch_built_in_browser,
            on_success=lambda diagnostics: self._after_browser_ready("Built-in browser", diagnostics),
        )

    def refresh_live(self) -> None:
        self._cancel_auto_sync(self._active_account_index())
        self._run_background(
            start_message=f"Refreshing pool 1 for {self._active_account_name()}...",
            worker=lambda: fetch_pool_questions(
                self._effective_capture_config(),
                self.capture_output_dir,
                self._threadsafe_status,
                question_limit=self.capture_config.question_limit,
                title="Pool 1 live questions",
            ),
            on_success=self._load_after_capture,
        )

    def claim_selected(self) -> None:
        question = self.selected_question
        if not question:
            messagebox.showinfo(APP_TITLE, "Select a question first.")
            return
        if not question.task_id:
            messagebox.showerror(APP_TITLE, "The selected question has no task ID and cannot be claimed.")
            return

        prompt = f"Claim question {question.topic_id or question.task_id} from pool 1?"
        if not messagebox.askyesno(APP_TITLE, prompt):
            return

        self._run_background(
            start_message="Claiming selected question...",
            worker=lambda: claim_pool_question(self._effective_capture_config(), question.task_id, self._threadsafe_status),
            on_success=lambda _result: self._after_claim(question),
        )

    def inspect_page(self) -> None:
        self._run_background(
            start_message="Inspecting current browser tab...",
            worker=lambda: inspect_current_page(self._effective_capture_config(), self._threadsafe_status),
            on_success=self._show_page_diagnostics,
        )

    def open_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose Question JSON",
            filetypes=[("JSON Files", "*.json")],
        )
        if path:
            self._load_file(Path(path))

    def _load_after_capture(self, json_path: Path) -> None:
        self._cancel_auto_sync(self._active_account_index())
        self._load_file(json_path)
        self.status_var.set(f"{self._active_account_name()} refresh finished. Live cache is up to date.")
        self._resume_auto_sync_if_session_active()

    def _after_claim(self, claimed_question: Question) -> None:
        if self.current_set:
            self.current_set.questions = [item for item in self.current_set.questions if item.task_id != claimed_question.task_id]
            if self.current_set.current_holding is not None:
                next_holding = self.current_set.current_holding + 1
                if self.current_set.holding_limit is not None:
                    next_holding = min(next_holding, self.current_set.holding_limit)
                self.current_set.current_holding = next_holding
            state = self._account_view_state()
            state.current_user_name = self.current_set.current_user_name
            state.current_holding = self.current_set.current_holding
            state.holding_limit = self.current_set.holding_limit
            self._store_active_account_view()
            self._update_pool_title()
            self._refresh_account_selector()
        self.apply_filter(select_first=True)
        self.status_var.set(
            f"Claim succeeded for {self._active_account_name()}. Refreshing live list to pull in new questions..."
        )
        self._run_background(
            start_message=f"Refreshing pool 1 for {self._active_account_name()}...",
            worker=lambda: fetch_pool_questions(
                self._effective_capture_config(),
                self.capture_output_dir,
                self._threadsafe_status,
                question_limit=self.capture_config.question_limit,
                title="Pool 1 live questions",
            ),
            on_success=lambda json_path: self._after_claim_refresh(claimed_question, json_path),
        )

    def _after_claim_refresh(self, claimed_question: Question, json_path: Path) -> None:
        self._load_file(json_path)
        messagebox.showinfo(
            APP_TITLE,
            f"Claim succeeded: {claimed_question.topic_id or claimed_question.task_id}\n"
            "The live list has been refreshed.",
        )
        self.status_var.set(f"Claim succeeded for {self._active_account_name()} and the live list has been refreshed.")
        self._resume_auto_sync_if_session_active(delay_ms=self._auto_sync_delay_ms(1.2))

    def _show_page_diagnostics(self, diagnostics: dict[str, object]) -> None:
        detected_user_name = str(diagnostics.get("current_user_name") or "").strip()
        if detected_user_name:
            state = self._account_view_state()
            state.current_user_name = detected_user_name
            if self.current_set:
                self.current_set.current_user_name = detected_user_name
                self._store_active_account_view()
            self._refresh_account_selector()

        lines = [
            "Current browser page",
            f"Title: {diagnostics.get('selected_title') or '(untitled)'}",
            f"URL: {diagnostics.get('selected_url') or 'about:blank'}",
            f"User: {diagnostics.get('current_user_name') or 'not detected'}",
            "",
            f"Question cards on page: {diagnostics.get('list_item_count')}",
            f"Preview roots on page: {diagnostics.get('preview_root_count')}",
            f"Preview sections on page: {diagnostics.get('section_count')}",
        ]

        candidates = diagnostics.get("candidates") or []
        if candidates:
            lines.append("")
            lines.append("Open tabs")
            for index, candidate in enumerate(candidates, start=1):
                lines.append(f"{index}. {candidate.get('title') or '(untitled)'}")
                lines.append(f"   {candidate.get('url') or 'about:blank'}")

        messagebox.showinfo(APP_TITLE, "\n".join(lines))
        self.status_var.set("Browser inspection finished.")

    def _after_browser_ready(self, label: str, diagnostics: dict[str, object] | None) -> None:
        detected_user_name = ""
        if diagnostics:
            detected_user_name = str(diagnostics.get("current_user_name") or "").strip()
        if detected_user_name:
            state = self._account_view_state()
            state.current_user_name = detected_user_name
            self._refresh_account_selector()
            self.status_var.set(
                f"{label} is ready for {self._active_account_name()} ({detected_user_name}). Automatic sync is starting..."
            )
        else:
            self.status_var.set(
                f"{label} is ready for {self._active_account_name()}. Log in there once and automatic sync will fetch data."
            )
        self._refresh_account_selector()
        self._schedule_auto_sync_for_slot(
            self._active_account_index(),
            delay_ms=self._auto_sync_delay_ms(0.8, minimum=900),
        )

    def _load_file(self, path: Path) -> None:
        previous_ids = (
            {self._question_key(question) for question in self.current_set.questions}
            if self.current_set
            else set()
        )
        try:
            question_set = load_question_set(path)
        except QuestionDataError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            self.status_var.set(f"Load failed: {exc}")
            return
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Unexpected error: {exc}")
            self.status_var.set(f"Load failed: {exc}")
            return

        self.current_set = question_set
        self.last_source_path = question_set.source_path
        current_ids = {self._question_key(question) for question in question_set.questions}
        self.highlight_question_ids = {question_id for question_id in current_ids - previous_ids if question_id}
        state = self._account_view_state()
        state.current_user_name = question_set.current_user_name
        state.current_holding = question_set.current_holding
        state.holding_limit = question_set.holding_limit
        self.public_pool_snapshot = self._question_set_for_public_pool_cache(question_set)
        self._store_active_account_view()
        self._update_pool_title()
        self.search_var.set("")
        self.apply_filter(select_first=True)
        self._refresh_account_selector()

    def apply_filter(self, select_first: bool = False) -> None:
        if not self.current_set:
            return

        keyword = self.search_var.get().strip().lower()
        if not keyword:
            self.filtered_questions = list(self.current_set.questions)
        else:
            self.filtered_questions = [
                question
                for question in self.current_set.questions
                if self._question_matches(question, keyword)
            ]

        self._refresh_tree()
        if self.filtered_questions and select_first:
            self._select_question_by_index(0)
        elif not self.filtered_questions:
            self.selected_question = None
            if keyword:
                self.preview_subtitle.configure(text="No matching result")
                self._draw_empty_state("No question matches the current search keyword.")
            else:
                self.preview_subtitle.configure(
                    text=f"User: {self._account_view_state().current_user_name or 'not detected'}  |  Holding: {self._current_holding_text()}"
                )
                self._draw_empty_state(f"No available questions are cached for {self._active_account_name()}.")

    def _question_matches(self, question: Question, keyword: str) -> bool:
        haystack = [
            question.title,
            question.source_id,
            question.task_id,
            question.topic_id,
            question.subject_name,
            question.phase_name,
            question.grade_name,
            " ".join(question.tags),
            question.summary(200),
        ]
        for section in question.sections:
            haystack.append(section.label)
            for block in section.blocks:
                if block.block_type == "text":
                    haystack.append(block.value)
        return keyword in " ".join(haystack).lower()

    def _refresh_tree(self) -> None:
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        for index, question in enumerate(self.filtered_questions):
            row_tag = "even" if index % 2 == 0 else "odd"
            tags = (row_tag, "new") if self._question_key(question) in self.highlight_question_ids else (row_tag,)
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(question.order_id, question.topic_id or "-", question.summary()),
                tags=tags,
            )

    def _select_question_by_index(self, index: int) -> None:
        if not self.filtered_questions:
            return
        index = max(0, min(index, len(self.filtered_questions) - 1))
        item_id = str(index)
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.tree.see(item_id)
        self._show_question(self.filtered_questions[index])

    def _on_tree_select(self, _event) -> None:
        selection = self.tree.selection()
        if selection:
            self._show_question(self.filtered_questions[int(selection[0])])

    def _show_question(self, question: Question) -> None:
        self.selected_question = question
        subtitle_parts = [f"Question #{question.order_id}"]
        if question.topic_id:
            subtitle_parts.append(f"Topic ID: {question.topic_id}")
        if question.task_id:
            subtitle_parts.append(f"Task ID: {question.task_id}")
        if self._question_key(question) in self.highlight_question_ids:
            subtitle_parts.append("NEW")
        self.preview_subtitle.configure(text="  |  ".join(subtitle_parts))
        self._clear_preview()
        self.preview_images.clear()

        header_card = self._make_card(self.preview_inner, pady=18)
        header_card.pack(fill="x", padx=18, pady=(18, 10))

        tk.Label(
            header_card,
            text=question.topic_id or f"Question #{question.order_id}",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")

        if question.title:
            tk.Label(
                header_card,
                text=question.title,
                bg=CARD_BG,
                fg=TEXT_MAIN,
                font=("Microsoft YaHei UI", 12),
                wraplength=780,
                justify="left",
            ).pack(anchor="w", pady=(10, 0))

        if self._question_key(question) in self.highlight_question_ids:
            tk.Label(
                header_card,
                text="Newly added in the latest refresh",
                bg=SUCCESS_BG,
                fg=SUCCESS_ACCENT,
                padx=10,
                pady=4,
                font=("Microsoft YaHei UI", 10, "bold"),
            ).pack(anchor="w", pady=(8, 0))

        meta_parts = [
            value
            for value in [question.subject_name, question.phase_name, question.grade_name, question.pool_type_name]
            if value
        ]
        if meta_parts:
            tk.Label(
                header_card,
                text=" / ".join(meta_parts),
                bg=CARD_BG,
                fg=TEXT_MUTED,
                font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w", pady=(10, 0))

        if question.timeliness_hours is not None:
            tk.Label(
                header_card,
                text=f"Timeliness: {question.timeliness_hours} hours",
                bg=CARD_BG,
                fg=TEXT_MUTED,
                font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w", pady=(6, 0))

        for section in question.sections:
            card = self._make_card(self.preview_inner)
            card.pack(fill="x", padx=18, pady=10)

            tk.Label(
                card,
                text=section.label,
                bg=CARD_BG,
                fg=ACCENT,
                font=("Microsoft YaHei UI", 11, "bold"),
            ).pack(anchor="w")

            for block in section.blocks:
                if block.block_type == "text":
                    self._render_text_block(card, block.value)
                elif block.block_type == "image":
                    self._render_image_block(card, Path(block.value))

        self.preview_canvas.yview_moveto(0.0)

    def _render_text_block(self, parent: tk.Frame, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=CARD_BG,
            fg=TEXT_MAIN,
            wraplength=800,
            justify="left",
            anchor="w",
            font=("Microsoft YaHei UI", 11),
        ).pack(fill="x", anchor="w", pady=(12, 0))

    def _render_image_block(self, parent: tk.Frame, image_path: Path) -> None:
        full_path = image_path if image_path.is_absolute() else (self.last_source_path.parent / image_path).resolve()
        try:
            image = Image.open(full_path)
            display_image = self._fit_image(image, max_width=800)
            photo = ImageTk.PhotoImage(display_image)
            self.preview_images.append(photo)

            image_label = tk.Label(parent, image=photo, bg=CARD_BG, bd=0)
            image_label.pack(anchor="w", pady=(12, 0))

            tk.Label(
                parent,
                text=str(full_path),
                bg=CARD_BG,
                fg=TEXT_MUTED,
                font=("Microsoft YaHei UI", 9),
                wraplength=800,
                justify="left",
            ).pack(anchor="w", pady=(8, 0))
        except Exception as exc:
            tk.Label(
                parent,
                text=f"Image load failed: {full_path} ({exc})",
                bg=CARD_BG,
                fg="#b42318",
                wraplength=800,
                justify="left",
                font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w", pady=(12, 0))

    def _fit_image(self, image: Image.Image, max_width: int) -> Image.Image:
        image = image.convert("RGBA")
        if image.width <= max_width:
            return image
        ratio = max_width / image.width
        return image.resize((max_width, int(image.height * ratio)), Image.Resampling.LANCZOS)

    def _clear_preview(self) -> None:
        for child in self.preview_inner.winfo_children():
            child.destroy()

    def _draw_empty_state(
        self,
        message: str = "Open the browser, log in, then refresh pool 1 live data here.",
    ) -> None:
        self._clear_preview()
        self.preview_images.clear()

        card = self._make_card(self.preview_inner, pady=28)
        card.pack(fill="x", padx=18, pady=18)

        tk.Label(
            card,
            text="Ready",
            bg=CARD_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(anchor="w")

        tk.Label(
            card,
            text=message,
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 11),
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

    def _question_key(self, question: Question) -> str:
        return question.task_id or question.topic_id or question.source_id

    def _on_close(self) -> None:
        try:
            self._cancel_auto_sync()
            self._stop_external_browser()
            self._stop_built_in_browser()
            reset_runtime_cache(self.capture_output_dir)
        finally:
            self.root.destroy()

    def _launch_external_browser(self) -> dict[str, object] | None:
        slot = self._active_account_index()
        config = self._slot_capture_config(slot)
        self._stop_built_in_browser(slot)

        existing_process = self.external_browser_processes.get(slot)
        if existing_process and existing_process.poll() is None:
            try:
                return inspect_current_page(config, None)
            except Exception:
                self._stop_external_browser(slot)

        launched_process = launch_debug_browser(config, self.app_home, self._threadsafe_status)
        if launched_process:
            self.external_browser_processes[slot] = launched_process
        try:
            return inspect_current_page(config, None)
        except Exception:
            return None

    def _launch_built_in_browser(self) -> dict[str, object] | None:
        slot = self._active_account_index()
        profile_dir = self._slot_webview_profile_dir(slot)
        config = self._slot_capture_config(slot)

        self._stop_external_browser(slot)
        existing_process = self.built_in_processes.get(slot)
        if existing_process and existing_process.poll() is None:
            try:
                return inspect_current_page(config, None)
            except Exception:
                self._stop_built_in_browser(slot)

        profile_dir.mkdir(parents=True, exist_ok=True)

        if getattr(sys, "frozen", False):
            command = [
                str(Path(sys.executable).resolve()),
                "--webview-host",
                "--url",
                config.start_url.strip(),
                "--debug-port",
                str(config.debug_port),
                "--profile-dir",
                str(profile_dir),
            ]
        else:
            command = [
                str(Path(sys.executable).resolve()),
                str((self.app_home / "app.py").resolve()),
                "--webview-host",
                "--url",
                config.start_url.strip(),
                "--debug-port",
                str(config.debug_port),
                "--profile-dir",
                str(profile_dir),
            ]

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        process = subprocess.Popen(
            command,
            cwd=str(self.app_home),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self.built_in_processes[slot] = process

        for _ in range(60):
            if process.poll() is not None:
                raise CaptureError("The built-in browser exited unexpectedly during startup.")
            try:
                return inspect_current_page(config, None)
            except Exception:
                pass
            threading.Event().wait(0.5)

        raise CaptureError("The built-in browser started, but its debug connection did not become ready.")

    def _stop_tracked_process(self, process: subprocess.Popen | None) -> None:
        if not process:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def _stop_external_browser(self, slot: int | None = None) -> None:
        slot_indexes = list(self.external_browser_processes) if slot is None else [slot]
        for slot_index in slot_indexes:
            process = self.external_browser_processes.pop(slot_index, None)
            self._stop_tracked_process(process)

    def _stop_built_in_browser(self, slot: int | None = None) -> None:
        slot_indexes = list(self.built_in_processes) if slot is None else [slot]
        for slot_index in slot_indexes:
            process = self.built_in_processes.pop(slot_index, None)
            self._stop_tracked_process(process)

    def _effective_capture_config(self) -> CaptureConfig:
        return self._slot_capture_config()

    def _make_card(self, parent: tk.Widget, pady: int = 16) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=CARD_BG,
            padx=18,
            pady=pady,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )

    def _run_background(self, start_message: str, worker, on_success) -> None:
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Another task is still running. Please wait a moment.")
            return

        self.busy = True
        self._set_action_buttons_state(False)
        self.status_var.set(start_message)

        def wrapped() -> None:
            try:
                result = worker()
            except Exception as exc:
                self.ui_queue.put(("error", exc, None))
            else:
                self.ui_queue.put(("done", result, on_success))

        threading.Thread(target=wrapped, daemon=True).start()

    def _finish_background(self, result=None, on_success=None, exc: Exception | None = None) -> None:
        self.busy = False
        self._set_action_buttons_state(True)

        if exc:
            if isinstance(exc, CaptureError):
                message = str(exc)
            else:
                message = f"Task failed: {exc}"
            messagebox.showerror(APP_TITLE, message)
            self.status_var.set(message)
            return

        if on_success:
            on_success(result)

    def _set_action_buttons_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self.action_buttons:
            palette = self.action_button_styles.get(button, {"bg": ACCENT, "hover": ACCENT_HOVER, "fg": "white"})
            if enabled:
                button.configure(
                    state=state,
                    cursor="hand2",
                    bg=palette["bg"],
                    fg=palette["fg"],
                    activebackground=palette["hover"],
                    activeforeground=palette["fg"],
                    disabledforeground=palette["fg"],
                )
            else:
                button.configure(
                    state=state,
                    cursor="arrow",
                    bg="#dfe7f2",
                    fg="#8a98ab",
                    activebackground="#dfe7f2",
                    activeforeground="#8a98ab",
                    disabledforeground="#8a98ab",
                )

    def _threadsafe_status(self, message: str) -> None:
        self.ui_queue.put(("status", message, None))

    def _process_ui_queue(self) -> None:
        try:
            while True:
                kind, payload, extra = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "error":
                    self._finish_background(exc=payload)
                elif kind == "done":
                    self._finish_background(result=payload, on_success=extra)
                elif kind == "auto_sync_done":
                    self._handle_auto_sync_success(payload["slot"], payload["json_path"])
                elif kind == "auto_sync_error":
                    self._handle_auto_sync_error(payload["slot"], payload["exc"])
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(120, self._process_ui_queue)

    def _sync_preview_scroll(self, _event) -> None:
        self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all"))

    def _resize_preview_inner(self, event) -> None:
        self.preview_canvas.itemconfigure(self.preview_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if self.preview_canvas.winfo_exists():
            self.preview_canvas.yview_scroll(int(-event.delta / 120), "units")

    def run(self) -> None:
        self.root.mainloop()


def run() -> None:
    QuestionViewerApp().run()
