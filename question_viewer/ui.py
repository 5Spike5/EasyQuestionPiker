from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from question_viewer.browser_capture import (
    CaptureError,
    capture_current_page,
    claim_pool_question,
    fetch_pool_questions,
    inspect_current_page,
    launch_debug_browser,
    reset_runtime_cache,
)
from question_viewer.capture_config import CaptureConfig, load_capture_config, save_capture_config
from question_viewer.loader import QuestionDataError, load_question_set
from question_viewer.models import Question, QuestionSet
from question_viewer.paths import get_app_home


APP_TITLE = "EasyQuestionPicker"
WINDOW_BG = "#edf2f7"
CARD_BG = "#ffffff"
ACCENT = "#1662dd"
TEXT_MAIN = "#17212f"
TEXT_MUTED = "#667085"
BUILT_IN_PROFILE_DIRNAME = ".webview_profile"


class ConfigDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: CaptureConfig) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.configure(bg=CARD_BG)
        self.result: CaptureConfig | None = None

        self.browser_name_var = tk.StringVar(value=config.browser_name)
        self.start_url_var = tk.StringVar(value=config.start_url)
        self.browser_path_var = tk.StringVar(value=config.browser_executable_path)
        self.debug_port_var = tk.StringVar(value=str(config.debug_port))
        self.profile_dir_var = tk.StringVar(value=config.profile_dir)
        self.question_limit_var = tk.StringVar(value=str(config.question_limit))

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
            "Fallback flow: Open Browser still launches an external browser session if you want it."
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
            ("Debug Port", self._entry(container, self.debug_port_var, width=20)),
            ("Profile Dir", self._entry(container, self.profile_dir_var)),
            ("Max Questions", self._entry(container, self.question_limit_var, width=20)),
        ]

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
                list_item_selector="",
                list_item_title_selector="",
                preview_root_selector="",
                section_selector="",
                section_label_selector="",
                section_content_selector="",
                click_wait_ms=1200,
                question_limit=int(self.question_limit_var.get().strip() or "0"),
            )
        except ValueError:
            messagebox.showerror(APP_TITLE, "Debug port and max questions must be integers.", parent=self)
            return

        self.result = config
        self.destroy()


class QuestionViewerApp:
    def __init__(self) -> None:
        self.app_home = get_app_home()
        self.config_path = self.app_home / "capture_config.json"
        self.capture_output_dir = self.app_home / "captured"
        self.capture_config = load_capture_config(self.config_path)
        self.built_in_profile_dir = self.app_home / BUILT_IN_PROFILE_DIRNAME
        self.built_in_process: subprocess.Popen | None = None

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1280x860")
        self.root.minsize(1040, 720)
        self.root.configure(bg=WINDOW_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Treeview", rowheight=36, font=("Microsoft YaHei UI", 10))
        self.style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        self.style.map("Treeview", background=[("selected", "#dbe7ff")], foreground=[("selected", TEXT_MAIN)])

        self.current_set: QuestionSet | None = None
        self.filtered_questions: list[Question] = []
        self.selected_question: Question | None = None
        self.last_source_path: Path | None = None
        self.highlight_question_ids: set[str] = set()
        self.preview_images: list[ImageTk.PhotoImage] = []
        self.busy = False
        self.ui_queue: queue.Queue = queue.Queue()

        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Open Built-in Browser, log in once, then click Refresh Live."
        )
        self.title_var = tk.StringVar(value="Pool 1 not loaded")

        self.action_buttons: list[tk.Button] = []
        self.claim_button: tk.Button | None = None
        reset_runtime_cache(self.capture_output_dir)
        self._build_layout()
        self.root.after(120, self._process_ui_queue)

    def _build_layout(self) -> None:
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        toolbar = tk.Frame(self.root, bg=WINDOW_BG, padx=18, pady=14)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(1, weight=1)

        tk.Label(
            toolbar,
            text=APP_TITLE,
            bg=WINDOW_BG,
            fg=TEXT_MAIN,
            font=("Microsoft YaHei UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        actions_frame = tk.Frame(toolbar, bg=WINDOW_BG)
        actions_frame.grid(row=0, column=1, sticky="e")

        self._add_action_button(actions_frame, "Built-in", self.open_built_in_browser, 0)
        self._add_action_button(actions_frame, "Browser", self.open_browser, 1)
        self._add_action_button(actions_frame, "Refresh", self.refresh_live, 2)
        self._add_action_button(actions_frame, "Claim", self.claim_selected, 3)
        self._add_action_button(actions_frame, "Inspect", self.inspect_page, 4)
        self._add_action_button(actions_frame, "Import", self.open_json, 5)
        self._add_action_button(actions_frame, "Settings", self.open_settings, 6)

        search_frame = tk.Frame(toolbar, bg=WINDOW_BG)
        search_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        search_frame.grid_columnconfigure(1, weight=1)
        tk.Label(
            search_frame,
            text="Search",
            bg=WINDOW_BG,
            fg=TEXT_MUTED,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c7d3e3",
            highlightcolor=ACCENT,
            font=("Microsoft YaHei UI", 10),
        )
        search_entry.grid(row=0, column=1, sticky="ew", ipady=5)
        search_entry.bind("<KeyRelease>", lambda _event: self.apply_filter())

        body = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            bg=WINDOW_BG,
            bd=0,
            relief="flat",
        )
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))

        left_panel = tk.Frame(body, bg=CARD_BG, padx=14, pady=14)
        right_panel = tk.Frame(body, bg=CARD_BG, padx=0, pady=0)

        body.add(left_panel, minsize=320, width=380)
        body.add(right_panel, minsize=580)

        self._build_question_list(left_panel)
        self._build_preview_panel(right_panel)

        status_bar = tk.Frame(self.root, bg=CARD_BG, padx=18, pady=12)
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
    ) -> None:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=ACCENT,
            fg="white",
            activebackground="#2459c8",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=10,
            pady=7,
            font=("Microsoft YaHei UI", 9, "bold"),
            cursor="hand2",
        )
        button.grid(row=row, column=column, padx=4, pady=0, sticky=sticky)
        self.action_buttons.append(button)
        if text == "Claim":
            self.claim_button = button

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
        self.tree.tag_configure("new", background="#e8fff1")

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

        self.preview_canvas = tk.Canvas(canvas_wrap, bg=WINDOW_BG, bd=0, highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew", padx=16, pady=(0, 16))

        preview_scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.preview_canvas.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns", pady=(0, 16))
        self.preview_canvas.configure(yscrollcommand=preview_scroll.set)

        self.preview_inner = tk.Frame(self.preview_canvas, bg=WINDOW_BG)
        self.preview_window = self.preview_canvas.create_window((0, 0), window=self.preview_inner, anchor="nw")
        self.preview_inner.bind("<Configure>", self._sync_preview_scroll)
        self.preview_canvas.bind("<Configure>", self._resize_preview_inner)
        self.preview_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._draw_empty_state()

    def open_settings(self) -> None:
        dialog = ConfigDialog(self.root, self.capture_config)
        self.root.wait_window(dialog)
        if dialog.result:
            self.capture_config = dialog.result
            save_capture_config(self.config_path, self.capture_config)
            self.status_var.set(f"Settings saved: {self.config_path}")

    def open_browser(self) -> None:
        self._run_background(
            start_message="Preparing browser...",
            worker=lambda: launch_debug_browser(self.capture_config, self.app_home, self._threadsafe_status),
            on_success=lambda _result: self.status_var.set(
                "Browser is ready. Log in there once, then come back and click Refresh Live."
            ),
        )

    def open_built_in_browser(self) -> None:
        self._run_background(
            start_message="Starting the built-in browser...",
            worker=self._launch_built_in_browser,
            on_success=lambda _result: self.status_var.set(
                "Built-in browser is ready. Log in there once, then come back and click Refresh Live."
            ),
        )

    def refresh_live(self) -> None:
        self._run_background(
            start_message="Refreshing live pool 1 questions...",
            worker=lambda: fetch_pool_questions(
                self.capture_config,
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
            worker=lambda: claim_pool_question(self.capture_config, question.task_id, self._threadsafe_status),
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
        self._load_file(json_path)
        self.status_var.set(f"Live refresh finished and loaded: {json_path}")

    def _after_claim(self, claimed_question: Question) -> None:
        if self.current_set:
            self.current_set.questions = [item for item in self.current_set.questions if item.task_id != claimed_question.task_id]
            self.title_var.set(f"{self.current_set.title}  |  {len(self.current_set.questions)} questions")
        self.apply_filter(select_first=True)
        self.status_var.set("Claim succeeded. Refreshing live list to pull in new questions...")
        self._run_background(
            start_message="Refreshing live pool 1 questions...",
            worker=lambda: fetch_pool_questions(
                self.capture_config,
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
        self.status_var.set("Claim succeeded and the live list has been refreshed.")

    def _show_page_diagnostics(self, diagnostics: dict[str, object]) -> None:
        lines = [
            "Current browser page",
            f"Title: {diagnostics.get('selected_title') or '(untitled)'}",
            f"URL: {diagnostics.get('selected_url') or 'about:blank'}",
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
        self.title_var.set(f"{question_set.title}  |  {len(question_set.questions)} questions")
        self.search_var.set("")
        self.apply_filter(select_first=True)

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
            self.preview_subtitle.configure(text="No matching result")
            self._draw_empty_state("No question matches the current search keyword.")

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
            tags = ("new",) if self._question_key(question) in self.highlight_question_ids else ()
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
                bg=CARD_BG,
                fg="#0a7f39",
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
            self._stop_built_in_browser()
            reset_runtime_cache(self.capture_output_dir)
        finally:
            self.root.destroy()

    def _launch_built_in_browser(self) -> None:
        self._stop_built_in_browser()
        self.built_in_profile_dir.mkdir(parents=True, exist_ok=True)

        config = self._effective_capture_config()

        if getattr(sys, "frozen", False):
            command = [
                str(Path(sys.executable).resolve()),
                "--webview-host",
                "--url",
                config.start_url.strip(),
                "--debug-port",
                str(config.debug_port),
                "--profile-dir",
                str(self.built_in_profile_dir),
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
                str(self.built_in_profile_dir),
            ]

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        self.built_in_process = subprocess.Popen(
            command,
            cwd=str(self.app_home),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        for _ in range(60):
            if self.built_in_process.poll() is not None:
                raise CaptureError("The built-in browser exited unexpectedly during startup.")
            try:
                inspect_current_page(config, None)
                return
            except Exception:
                pass
            threading.Event().wait(0.5)

        raise CaptureError("The built-in browser started, but its debug connection did not become ready.")

    def _stop_built_in_browser(self) -> None:
        if not self.built_in_process:
            return
        if self.built_in_process.poll() is None:
            try:
                self.built_in_process.terminate()
                self.built_in_process.wait(timeout=5)
            except Exception:
                try:
                    self.built_in_process.kill()
                except Exception:
                    pass
        self.built_in_process = None

    def _effective_capture_config(self) -> CaptureConfig:
        if self.built_in_process and self.built_in_process.poll() is None:
            return replace(self.capture_config, profile_dir=str(self.built_in_profile_dir))
        return self.capture_config

    def _make_card(self, parent: tk.Widget, pady: int = 16) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=CARD_BG,
            padx=18,
            pady=pady,
            highlightthickness=1,
            highlightbackground="#dde6f2",
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
            button.configure(state=state)

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
