"""Three-step wizard shell: pick data, review records, export FIT files."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from ..core import (COORD_MODES, VERSION, export_exercises, sample_exercises,
                    scan_archive, write_json)
from . import theme as t
from .components import (Card, Collapsible, EmptyState, PathField, Pill, StatTile,
                         StatusBar, StepRail, restyle_segmented)

APPEARANCES = {"system": "跟随系统", "light": "浅色", "dark": "深色"}
RANGE_PRESETS = ("全部时间", "近 30 天", "近 90 天", "今年")
STEPS = (
    ("选择数据", "定位导出目录并扫描"),
    ("预览筛选", "核对记录与时间范围"),
    ("导出", "生成 FIT 或打成 ZIP"),
)
COLUMNS = (
    ("date", "运动日期 (原时区)", 186, "w"),
    ("sport", "运动类型", 118, "w"),
    ("distance", "距离 / km", 96, "e"),
    ("duration", "运动时长", 96, "e"),
    ("gps", "GPS 点", 78, "e"),
    ("heart", "心率点", 78, "e"),
    ("state", "导出状态", 110, "w"),
)
STATUS_LABELS = {"success": "成功", "skipped": "已存在，跳过", "failed": "失败"}
STATUS_TAGS = {"success": "ok", "skipped": "skipped", "failed": "failed"}


def app_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def duration_text(seconds):
    seconds = round(seconds)
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def enable_dpi_awareness():
    """Without this Tk renders at 96 DPI and Windows stretches the window,
    which makes every glyph look soft on scaled displays."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class ConverterApp(ctk.CTk):
    def __init__(self, source=None):
        enable_dpi_awareness()
        self.base = app_directory()
        self.config_path = self.base / "converter_settings.json"
        settings = self._read_settings()
        appearance = settings.get("appearance")
        if appearance not in APPEARANCES:
            appearance = "system"
        ctk.set_appearance_mode(appearance)
        super().__init__(fg_color=t.BG)

        self.title("华为运动记录 → FIT")
        self.minsize(1080, 720)
        self._center(1240, 860)

        default_source = self.base / "HUAWEI_HEALTH"
        if not default_source.exists() and (self.base.parent / "HUAWEI_HEALTH").exists():
            default_source = self.base.parent / "HUAWEI_HEALTH"
        self.source = tk.StringVar(value=str(source or settings.get("source", default_source)))
        self.output = tk.StringVar(value=str(settings.get("output", self.base / "exported_fit")))
        mode = settings.get("coordinate", "auto")
        self.coordinate = tk.StringVar(value=COORD_MODES.get(mode, COORD_MODES["auto"]))
        self.appearance = tk.StringVar(value=APPEARANCES[appearance])
        self.sport_filter = tk.StringVar(value="全部运动")
        self.range_filter = tk.StringVar(value=RANGE_PRESETS[0])
        self.from_date = tk.StringVar()
        self.to_date = tk.StringVar()
        self.scope = tk.StringVar(value="")
        self.zip_enabled = tk.BooleanVar(value=False)

        self.exercises = []
        self.visible = []
        self.date_range = None
        self.scope_kinds = []
        self.row_tags = {}
        self.row_status = {}
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.step = 1
        self.unlocked = 1
        self.last_output = None
        self.lockable = []
        self._tree_mode = None

        self._build_shell()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)
        self.go_step(1)
        if Path(self.source.get()).exists():
            self.after(450, self.scan)

    # ---------------------------------------------------------------- settings
    def _read_settings(self):
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        try:
            write_json(self.config_path, {"source": self.source.get(), "output": self.output.get(),
                                          "coordinate": self.coordinate_mode(),
                                          "appearance": self.appearance_key()})
        except OSError as exc:
            self.append_log(f"设置未保存：{exc}")

    def coordinate_mode(self):
        return next(k for k, v in COORD_MODES.items() if v == self.coordinate.get())

    def appearance_key(self):
        return next(k for k, v in APPEARANCES.items() if v == self.appearance.get())

    def _center(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2 - 24)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()
        self._build_log_drawer()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(titles, text="华为运动记录 → FIT", font=t.font(22, "bold"),
                     text_color=t.TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(titles, text="本地转换 · 每次运动一个文件 · 导出后可在 Zepp 中试导入",
                     font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 0))
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        Pill(right, f"v{VERSION}", "accent").grid(row=0, column=0, padx=(0, 10))
        self.appearance_seg = ctk.CTkSegmentedButton(
            right, values=list(APPEARANCES.values()), variable=self.appearance,
            command=self._change_appearance, height=30, corner_radius=8,
            font=t.font(t.FONT_SMALL), selected_color=t.ACCENT,
            selected_hover_color=t.ACCENT_HOVER, unselected_color=t.SURFACE,
            unselected_hover_color=t.HOVER, text_color=t.TEXT_MUTED)
        self.appearance_seg.grid(row=0, column=1, sticky="e")
        restyle_segmented(self.appearance_seg)

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(6, 0))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1, minsize=0)
        body.grid_columnconfigure(0, weight=0, minsize=226)

        rail_card = Card(body, padding=10)
        rail_card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        rail_card.body.grid_rowconfigure(0, weight=1)
        self.rail = StepRail(rail_card.body, STEPS, self.go_step)
        self.rail.grid(row=0, column=0, sticky="new")
        note = ctk.CTkFrame(rail_card.body, fg_color="transparent")
        note.grid(row=1, column=0, sticky="sew", padx=8)
        ctk.CTkFrame(note, height=1, fg_color=t.BORDER, corner_radius=0).grid(
            row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(note, text="全部转换在本机完成", font=t.font(t.FONT_TINY, "bold"),
                     text_color=t.TEXT_MUTED, anchor="w").grid(row=1, column=0, sticky="w")
        ctk.CTkLabel(note, text="原始归档只读，不会上传。", font=t.font(t.FONT_TINY),
                     text_color=t.TEXT_FAINT, anchor="w", justify="left", wraplength=186
                     ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        self.content = ctk.CTkFrame(body, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {1: self._build_step1(), 2: self._build_step2(), 3: self._build_step3()}
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

    def _restyle_segments(self):
        for name in ("appearance_seg", "range_seg", "scope_seg"):
            segmented = getattr(self, name, None)
            if segmented is not None:
                try:
                    restyle_segmented(segmented)
                except Exception:
                    pass

    def _build_log_drawer(self):
        drawer = ctk.CTkFrame(self, fg_color="transparent")
        drawer.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 0))
        drawer.grid_columnconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(drawer, height=86, corner_radius=10, border_width=1,
                                      border_color=t.BORDER, fg_color=t.SURFACE_ALT,
                                      text_color=t.TEXT_MUTED, font=t.font(t.FONT_TINY, family=t.MONO),
                                      wrap="word", activate_scrollbars=True)
        self.log_drawer = Collapsible(drawer, "运行日志", open_=False,
                                     on_toggle=self._toggle_log)
        self.log_drawer.grid(row=0, column=0, sticky="ew")
        self.log_box.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self.log_box.grid_remove()
        self.log_box.configure(state="disabled")
        self.append_log(f"版本 {VERSION}。导出文件会完成 FIT 解码与 CRC 校验；"
                        "Zepp 实际导入效果需在手机端核对。")

    def _build_footer(self):
        line = ctk.CTkFrame(self, height=1, fg_color=t.BORDER, corner_radius=0)
        line.grid(row=3, column=0, sticky="ew")
        self.status_bar = StatusBar(self)
        self.status_bar.grid(row=4, column=0, sticky="ew")
        self.status_bar.cancel.configure(command=self.cancel_task)
        self.status_bar.show_activity(False)
        self.status_bar.set("就绪")

    def _toggle_log(self, opened):
        if opened:
            self.log_box.grid()
        else:
            self.log_box.grid_remove()

    # --------------------------------------------------------------- step one
    def _build_step1(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(head, text="选择数据目录", font=t.font(t.FONT_TITLE, "bold"),
                     text_color=t.TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="先让工具找到华为运动健康导出的运动明细；扫描成功后会自动进入下一步。",
                     font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.picker_card = Card(page, padding=20)
        self.picker_card.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        self.picker_card.body.grid_columnconfigure(0, weight=1)
        PathField(self.picker_card.body, "源数据目录", self.source,
                  actions=(("选择文件夹", self.pick_source, True),),
                  hint="支持 HUAWEI_HEALTH 根目录，也支持其中的"
                       "「Motion path detail data」这类运动明细文件夹。"
                  ).grid(row=0, column=0, sticky="ew")
        actions = ctk.CTkFrame(self.picker_card.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        self.scan_button = ctk.CTkButton(actions, text="扫描记录", command=self.scan, height=38,
                                         width=132, corner_radius=t.RADIUS_CONTROL,
                                         font=t.font(t.FONT_BODY, "bold"), fg_color=t.ACCENT,
                                         hover_color=t.ACCENT_HOVER, text_color=t.ACCENT_TEXT)
        self.scan_button.grid(row=0, column=0, sticky="w")
        self.scan_hint = ctk.CTkLabel(actions, text="扫描后可按运动类型与日期筛选，不会修改源文件。",
                                      font=t.font(t.FONT_SMALL), text_color=t.TEXT_FAINT, anchor="w")
        self.scan_hint.grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.scan_progress = ctk.CTkProgressBar(self.picker_card.body, height=6, corner_radius=3,
                                                fg_color=t.DISABLED, progress_color=t.ACCENT)
        self.scan_progress.set(0)
        self.scan_progress.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.scan_progress.grid_remove()
        self._lock(self.scan_button)

        self.summary_card = Card(page, padding=18)
        self.summary_card.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        self.summary_card.body.grid_columnconfigure(0, weight=0)
        self.summary_card.body.grid_columnconfigure(1, weight=1)
        self.summary_badge = ctk.CTkLabel(self.summary_card.body, text="✓", width=30, height=30,
                                          corner_radius=15, font=t.font(t.FONT_BODY, "bold"),
                                          fg_color=t.SUCCESS_SOFT, text_color=t.SUCCESS)
        self.summary_badge.grid(row=0, column=0, sticky="n", padx=(0, 12))
        info = ctk.CTkFrame(self.summary_card.body, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew")
        info.grid_columnconfigure(0, weight=1)
        self.summary_path = ctk.CTkLabel(info, text="", font=t.font(t.FONT_BODY, "bold"),
                                         text_color=t.TEXT, anchor="w", justify="left")
        self.summary_path.grid(row=0, column=0, sticky="w")
        self.summary_stats = ctk.CTkLabel(info, text="", font=t.font(t.FONT_SMALL),
                                          text_color=t.TEXT_MUTED, anchor="w")
        self.summary_stats.grid(row=1, column=0, sticky="w", pady=(3, 0))
        buttons = ctk.CTkFrame(self.summary_card.body, fg_color="transparent")
        buttons.grid(row=0, column=2, sticky="e")
        self.rescan_button = ctk.CTkButton(buttons, text="重新扫描", command=self.scan, height=32,
                                           width=92, corner_radius=t.RADIUS_CONTROL,
                                           font=t.font(t.FONT_SMALL), fg_color=t.ACCENT,
                                           hover_color=t.ACCENT_HOVER, text_color=t.ACCENT_TEXT)
        self.rescan_button.grid(row=0, column=0, padx=(0, 8))
        self.change_button = ctk.CTkButton(buttons, text="更改", command=self._reopen_picker, height=32,
                                           width=72, corner_radius=t.RADIUS_CONTROL,
                                           font=t.font(t.FONT_SMALL), fg_color=t.SURFACE_ALT,
                                           hover_color=t.HOVER, text_color=t.TEXT,
                                           border_width=1, border_color=t.BORDER)
        self.change_button.grid(row=0, column=1)
        self._lock(self.rescan_button)
        self.summary_card.grid_remove()

        guide = Card(page, padding=20)
        guide.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        ctk.CTkLabel(guide.body, text="接下来会发生什么", font=t.font(t.FONT_SMALL, "bold"),
                     text_color=t.TEXT_MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        self._bullet(guide.body, 1, "每个运动生成一条记录，按记录 ID 自动去重。")
        self._bullet(guide.body, 2, "有轨迹的导出 GPS；无轨迹仍保留心率、步频与运动汇总。")
        self._bullet(guide.body, 3, "导出的 FIT 会逐条解码并校验 CRC，失败的记录会单独列出原因。")
        self._bullet(guide.body, 4, "建议先导出 3 类测试样本，在 Zepp 里核对后再批量导出。")

        self.source_error = ctk.CTkLabel(page, text="", font=t.font(t.FONT_SMALL),
                                         text_color=t.DANGER, anchor="w")
        self.source_error.grid(row=3, column=0, sticky="nw", pady=(10, 0))
        return page

    def _bullet(self, parent, row, text):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        ctk.CTkLabel(line, text="·", font=t.font(t.FONT_BODY, "bold"), text_color=t.ACCENT,
                     width=12).grid(row=0, column=0, sticky="nw")
        ctk.CTkLabel(line, text=text, font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                     anchor="w", justify="left", wraplength=620).grid(row=0, column=1, sticky="w")

    def _reopen_picker(self):
        self.summary_card.grid_remove()
        self.picker_card.grid()
        self.source_error.configure(text="")

    # --------------------------------------------------------------- step two
    def _build_step2(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(head, text="预览与筛选", font=t.font(t.FONT_TITLE, "bold"),
                     text_color=t.TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="改动筛选会立即刷新列表；选中若干条后即可只导出这些记录。",
                     font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 0))

        stats = ctk.CTkFrame(page, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.tiles = {}
        for index, (key, label) in enumerate((("total", "当前记录"), ("gps", "有 GPS 轨迹"),
                                              ("heart", "有心率"), ("sports", "运动类型"))):
            stats.grid_columnconfigure(index, weight=1)
            tile = StatTile(stats, label, "0")
            tile.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            self.tiles[key] = tile

        filters = Card(page, padding=14)
        filters.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        filters.body.grid_columnconfigure(6, weight=1)
        ctk.CTkLabel(filters.body, text="运动类型", font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED
                     ).grid(row=0, column=0, padx=(0, 8))
        self.sport_box = ctk.CTkComboBox(filters.body, values=["全部运动"], variable=self.sport_filter,
                                         state="readonly", width=132, height=32,
                                         corner_radius=t.RADIUS_CONTROL,
                                         fg_color=t.SURFACE_ALT, border_color=t.BORDER,
                                         button_color=t.SURFACE_ALT, button_hover_color=t.HOVER,
                                         dropdown_fg_color=t.SURFACE, text_color=t.TEXT,
                                         font=t.font(t.FONT_SMALL), dropdown_font=t.font(t.FONT_SMALL),
                                         command=lambda _: self.refresh_visible())
        self.sport_box.grid(row=0, column=1, padx=(0, 18))
        ctk.CTkLabel(filters.body, text="时间范围", font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED
                     ).grid(row=0, column=2, padx=(0, 8))
        self.range_seg = ctk.CTkSegmentedButton(
            filters.body, values=list(RANGE_PRESETS), variable=self.range_filter,
            command=self._on_range, height=32, corner_radius=8, font=t.font(t.FONT_SMALL),
            selected_color=t.ACCENT, selected_hover_color=t.ACCENT_HOVER,
            unselected_color=t.SURFACE_ALT, unselected_hover_color=t.HOVER, text_color=t.TEXT_MUTED)
        self.range_seg.grid(row=0, column=3, padx=(0, 12))
        restyle_segmented(self.range_seg)
        self._lock(self.range_seg)
        self.custom_pill = Pill(filters.body, "", "accent")
        self.custom_pill.grid(row=0, column=4, padx=(0, 8))
        self.custom_pill.grid_remove()
        self.custom_clear = ctk.CTkButton(filters.body, text="清除", width=56, height=26,
                                          command=self._clear_custom_range, corner_radius=6,
                                          font=t.font(t.FONT_TINY), fg_color="transparent",
                                          hover_color=t.HOVER, text_color=t.TEXT_MUTED)
        self.custom_clear.grid(row=0, column=5)
        self.custom_clear.grid_remove()
        self.date_toggle = ctk.CTkButton(filters.body, text="自定义日期   ▶", height=26, width=112,
                                         command=self._toggle_dates, corner_radius=6,
                                         font=t.font(t.FONT_TINY), fg_color="transparent",
                                         hover_color=t.HOVER, text_color=t.TEXT_MUTED, anchor="e")
        self.date_toggle.grid(row=0, column=7, sticky="e")
        self._lock(self.date_toggle)
        dates = ctk.CTkFrame(filters.body, fg_color="transparent")
        dates.grid(row=1, column=0, columnspan=8, sticky="w", pady=(10, 0))
        dates.grid_remove()
        self.dates_frame = dates
        ctk.CTkLabel(dates, text="起", font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED
                     ).grid(row=0, column=0, padx=(0, 6))
        self.from_entry = ctk.CTkEntry(dates, textvariable=self.from_date, width=118, height=32,
                                       placeholder_text="2026-01-01",
                                       corner_radius=t.RADIUS_CONTROL, fg_color=t.SURFACE_ALT,
                                       border_color=t.BORDER, text_color=t.TEXT,
                                       placeholder_text_color=t.TEXT_FAINT, font=t.font(t.FONT_SMALL))
        self.from_entry.grid(row=0, column=1)
        ctk.CTkLabel(dates, text="止", font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED
                     ).grid(row=0, column=2, padx=(12, 6))
        self.to_entry = ctk.CTkEntry(dates, textvariable=self.to_date, width=118, height=32,
                                     placeholder_text="2026-12-31",
                                     corner_radius=t.RADIUS_CONTROL, fg_color=t.SURFACE_ALT,
                                     border_color=t.BORDER, text_color=t.TEXT,
                                     placeholder_text_color=t.TEXT_FAINT, font=t.font(t.FONT_SMALL))
        self.to_entry.grid(row=0, column=3)
        self.apply_dates = ctk.CTkButton(dates, text="应用", width=64, height=32, command=self._apply_dates,
                                         corner_radius=t.RADIUS_CONTROL, font=t.font(t.FONT_SMALL),
                                         fg_color=t.SURFACE_ALT, hover_color=t.HOVER, text_color=t.TEXT,
                                         border_width=1, border_color=t.BORDER)
        self.apply_dates.grid(row=0, column=4, padx=(12, 0))
        self.date_hint = ctk.CTkLabel(dates, text="格式 2026-10-25", font=t.font(t.FONT_TINY),
                                      text_color=t.TEXT_FAINT)
        self.date_hint.grid(row=0, column=5, padx=(10, 0))
        self.dates_open = False
        self._lock(self.sport_box)
        self._lock(self.from_entry)
        self._lock(self.to_entry)
        self._lock(self.apply_dates)

        self.list_card = Card(page, padding=14)
        self.list_card.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        self.list_card.body.grid_rowconfigure(3, weight=1)
        header = ctk.CTkFrame(self.list_card.body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(header, text="记录列表", font=t.font(t.FONT_SECTION, "bold"),
                     text_color=t.TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        self.list_count = Pill(header, "0 条", "muted")
        self.list_count.grid(row=0, column=1, padx=(10, 0))
        self.selection_pill = Pill(header, "未选择", "muted")
        self.selection_pill.grid(row=0, column=2, sticky="w", padx=(8, 0))
        for offset, (text, command) in enumerate((("全选", self.select_all),
                                                  ("仅选有轨迹", self.select_with_gps),
                                                  ("清除", self.select_none))):
            button = ctk.CTkButton(header, text=text, command=command, height=28, width=76,
                                   corner_radius=6, font=t.font(t.FONT_TINY),
                                   fg_color="transparent", hover_color=t.HOVER, text_color=t.TEXT_MUTED)
            button.grid(row=0, column=3 + offset, padx=(6, 0))
            self._lock(button)

        self.detail_card = ctk.CTkFrame(self.list_card.body, fg_color=t.SURFACE_ALT, corner_radius=10)
        self.detail_card.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.detail_card.grid_columnconfigure(0, weight=1)
        self.detail_text = ctk.CTkLabel(self.detail_card, text="", font=t.font(t.FONT_SMALL),
                                        text_color=t.TEXT_MUTED, anchor="w", justify="left",
                                        wraplength=760)
        self.detail_text.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        self.detail_card.grid_remove()

        self.tree_wrap = ctk.CTkFrame(self.list_card.body, fg_color="transparent")
        self.tree_wrap.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.tree_wrap.grid_columnconfigure(0, weight=1)
        self.tree_wrap.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.tree_wrap, columns=[c[0] for c in COLUMNS], show="headings",
                                 selectmode="extended")
        for key, label, width, anchor in COLUMNS:
            self.tree.heading(key, text=label, anchor="w" if anchor == "w" else "e")
            self.tree.column(key, width=width, minwidth=64, anchor=anchor, stretch=key in ("date", "sport"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_scroll = ctk.CTkScrollbar(self.tree_wrap, command=self.tree.yview, width=12,
                                            fg_color="transparent", button_color=t.BORDER,
                                            button_hover_color=t.TEXT_FAINT)
        self.tree_scroll.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Control-a>", self.select_all)
        self._lock(self.tree)
        self.empty_state = EmptyState(self.list_card.body, "◎", "当前筛选没有记录",
                                      "调整运动类型或时间范围后再看；也可以回到上一步重新扫描。")
        self.empty_state.grid(row=3, column=0, sticky="nsew")
        self.empty_state.grid_remove()

        footer = ctk.CTkFrame(page, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(1, weight=1)
        back = ctk.CTkButton(footer, text="上一步", command=lambda: self.go_step(1), height=38,
                             width=96, corner_radius=t.RADIUS_CONTROL, font=t.font(t.FONT_BODY),
                             fg_color="transparent", hover_color=t.HOVER, text_color=t.TEXT_MUTED,
                             border_width=1, border_color=t.BORDER)
        back.grid(row=0, column=0, sticky="w")
        self.next_button = ctk.CTkButton(footer, text="继续导出", command=lambda: self.go_step(3),
                                         height=38, width=178, corner_radius=t.RADIUS_CONTROL,
                                         font=t.font(t.FONT_BODY, "bold"), fg_color=t.ACCENT,
                                         hover_color=t.ACCENT_HOVER, text_color=t.ACCENT_TEXT)
        self.next_button.grid(row=0, column=2, sticky="e")
        self._lock(back)
        self._lock(self.next_button)
        return page

    # ------------------------------------------------------------- step three
    def _build_step3(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(head, text="导出", font=t.font(t.FONT_TITLE, "bold"), text_color=t.TEXT,
                     anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="选好范围与坐标系后开始导出；失败记录会保留原因，不影响其他记录。",
                     font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 0))

        scroll = ctk.CTkFrame(page, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        scroll.grid_columnconfigure(0, weight=1)
        scroll.grid_rowconfigure(3, weight=1)

        place = Card(scroll, padding=18)
        place.grid(row=0, column=0, sticky="ew")
        PathField(place.body, "FIT 输出目录", self.output,
                  actions=(("更改", self.pick_output, False), ("打开", self.open_output, False)),
                  hint="输出目录需要位于源数据目录之外；已校验过的相同记录会直接复用并跳过。"
                  ).grid(row=0, column=0, sticky="ew")

        settings = Card(scroll, padding=18)
        settings.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        settings.body.grid_columnconfigure(0, weight=1)
        settings.body.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(settings.body, text="导出范围", font=t.font(t.FONT_SMALL, "bold"),
                     text_color=t.TEXT_MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        self.scope_seg = ctk.CTkSegmentedButton(
            settings.body, values=[""], variable=self.scope, height=32, width=168, corner_radius=8,
            font=t.font(t.FONT_SMALL), selected_color=t.ACCENT, selected_hover_color=t.ACCENT_HOVER,
            unselected_color=t.SURFACE_ALT, unselected_hover_color=t.HOVER, text_color=t.TEXT_MUTED,
            command=lambda _value: self._restyle_segments())
        self.scope_seg.grid(row=1, column=0, sticky="w", pady=(6, 0))
        restyle_segmented(self.scope_seg)
        self._lock(self.scope_seg)
        ctk.CTkLabel(settings.body, text="轨迹坐标处理", font=t.font(t.FONT_SMALL, "bold"),
                     text_color=t.TEXT_MUTED, anchor="w").grid(row=0, column=1, sticky="w", padx=(18, 0))
        self.coord_box = ctk.CTkComboBox(settings.body, values=list(COORD_MODES.values()),
                                         variable=self.coordinate, state="readonly", height=32,
                                         width=292,
                                         corner_radius=t.RADIUS_CONTROL, fg_color=t.SURFACE_ALT,
                                         border_color=t.BORDER, button_color=t.SURFACE_ALT,
                                         button_hover_color=t.HOVER, dropdown_fg_color=t.SURFACE,
                                         text_color=t.TEXT, font=t.font(t.FONT_SMALL),
                                         dropdown_font=t.font(t.FONT_SMALL))
        self.coord_box.grid(row=1, column=1, sticky="w", padx=(18, 0), pady=(6, 0))
        self._lock(self.coord_box)

        self.coord_help = Collapsible(settings.body, "坐标与轨迹说明")
        self.coord_help.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(self.coord_help.body,
                     text="未标明坐标系时，自动模式依据高德来源做假设，请先验证样本。"
                          "选择「不导出 GPS 轨迹」时仍会保留心率、步频与运动汇总。",
                     font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED, anchor="w",
                     justify="left", wraplength=720).grid(row=0, column=0, sticky="w")

        self.advanced = Collapsible(settings.body, "高级选项")
        self.advanced.grid(row=3, column=0, columnspan=2, sticky="ew")
        ctk.CTkSwitch(self.advanced.body, text="生成 ZIP 包（仅含 FIT，超过 50 MB 自动分包）",
                      variable=self.zip_enabled, onvalue=True, offvalue=False,
                      font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                      progress_color=t.ACCENT).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(scroll, text="导出时会逐条解码并校验 CRC；每条结果、跳过原因与限制说明都写入"
                                  "输出目录的 conversion_report_*.json。",
                     font=t.font(t.FONT_SMALL), text_color=t.TEXT_FAINT, anchor="w",
                     justify="left", wraplength=800).grid(row=2, column=0, sticky="w", pady=(12, 0))

        self.result_card = Card(page, padding=16)
        self.result_card.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.result_card.body.grid_columnconfigure(1, weight=1)
        result_top = ctk.CTkFrame(self.result_card.body, fg_color="transparent")
        result_top.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.result_title = ctk.CTkLabel(result_top, text="导出完成", font=t.font(t.FONT_SECTION, "bold"),
                                         text_color=t.TEXT, anchor="w")
        self.result_title.grid(row=0, column=0, sticky="w")
        self.result_pills = ctk.CTkFrame(result_top, fg_color="transparent")
        self.result_pills.grid(row=0, column=1, sticky="e")
        self.result_pill_success = Pill(self.result_pills, "成功 0", "success")
        self.result_pill_success.grid(row=0, column=0, padx=(0, 6))
        self.result_pill_skipped = Pill(self.result_pills, "跳过 0", "muted")
        self.result_pill_skipped.grid(row=0, column=1, padx=(0, 6))
        self.result_pill_failed = Pill(self.result_pills, "失败 0", "muted")
        self.result_pill_failed.grid(row=0, column=2)
        self.result_detail = Collapsible(self.result_card.body, "查看失败原因与报告", on_toggle=None)
        self.result_detail.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.result_text = ctk.CTkTextbox(self.result_detail.body, height=96, corner_radius=8,
                                          border_width=1, border_color=t.BORDER,
                                          fg_color=t.SURFACE_ALT, text_color=t.TEXT_MUTED,
                                          font=t.font(t.FONT_TINY, family=t.MONO), wrap="word")
        self.result_text.grid(row=0, column=0, sticky="ew")
        self.result_text.configure(state="disabled")
        self.result_card.grid_remove()

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        actions.grid_columnconfigure(2, weight=1)
        self.back3 = ctk.CTkButton(actions, text="上一步", command=lambda: self.go_step(2), height=38,
                                   width=96, corner_radius=t.RADIUS_CONTROL, font=t.font(t.FONT_BODY),
                                   fg_color="transparent", hover_color=t.HOVER, text_color=t.TEXT_MUTED,
                                   border_width=1, border_color=t.BORDER)
        self.back3.grid(row=0, column=0, sticky="w")
        self.open_button = ctk.CTkButton(actions, text="打开输出目录", command=self.open_output, height=38,
                                         width=124, corner_radius=t.RADIUS_CONTROL,
                                         font=t.font(t.FONT_SMALL), fg_color="transparent",
                                         hover_color=t.HOVER, text_color=t.TEXT_MUTED,
                                         border_width=1, border_color=t.BORDER)
        self.open_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.export_button = ctk.CTkButton(actions, text="开始导出", command=self.start_export, height=38,
                                           width=150, corner_radius=t.RADIUS_CONTROL,
                                           font=t.font(t.FONT_BODY, "bold"), fg_color=t.ACCENT,
                                           hover_color=t.ACCENT_HOVER, text_color=t.ACCENT_TEXT)
        self.export_button.grid(row=0, column=3, sticky="e")
        for widget in (self.back3, self.open_button, self.export_button):
            self._lock(widget)
        return page

    # ------------------------------------------------------------- navigation
    def go_step(self, index):
        if self.busy or index not in self.pages:
            return
        if index >= 2 and not self.exercises:
            return
        if index >= 3 and not self.visible:
            return
        for number, page in self.pages.items():
            if number == index:
                page.grid()
            else:
                page.grid_remove()
        self.step = index
        self.unlocked = max(self.unlocked, index)
        self.rail.update_states(index, self.unlocked)
        if index == 2:
            self.refresh_visible()
        elif index == 3:
            self.refresh_scope()
        if not self.busy:
            if index == 1:
                self.status_bar.set("就绪")
            elif index == 3:
                self.status_bar.set(f"准备导出 · 已选 {len(self.selected_exercises())} 条")

    # --------------------------------------------------------------- scanning
    def _lock(self, widget, state="normal"):
        self.lockable.append((widget, state))
        return widget

    def _set_busy(self, value):
        self.busy = value
        for widget, state in self.lockable:
            try:
                widget.configure(state="disabled" if value else state)
            except Exception:
                pass
            if not value:
                # CTk 控件在重新启用后不会自动重绘文字颜色，手动触发一次。
                draw = getattr(widget, "_draw", None)
                if callable(draw):
                    try:
                        draw()
                    except Exception:
                        pass
        self.status_bar.show_activity(value)
        if value:
            self.cancel.clear()
            self.status_bar.set_progress(0)
            self.scan_progress.set(0)
        else:
            self._restyle_segments()

    def _run_worker(self, function):
        self._set_busy(True)

        def worker():
            try:
                function()
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("idle", None))

        threading.Thread(target=worker, daemon=True).start()

    def pick_source(self):
        value = filedialog.askdirectory(title="选择 HUAWEI_HEALTH 或运动明细目录")
        if value:
            self.source.set(value)
            self.scan()

    def scan(self):
        if self.busy:
            return
        text = self.source.get().strip()
        if not text:
            self.source_error.configure(text="请先选择源数据目录。")
            return
        source = Path(text)
        if not source.exists():
            self.source_error.configure(text="目录不存在，请重新选择。")
            self.status_bar.set("目录不存在，请重新选择", "danger")
            return
        self.source_error.configure(text="")
        self.save_settings()
        self.status_bar.set("正在扫描运动明细…", "accent")
        self.scan_progress.grid()
        self.scan_progress.set(0)

        def work():
            result = scan_archive(source, self.cancel,
                                  lambda n, total, text: self.events.put(("progress", (n, total, text))))
            self.events.put(("scanned", result))

        self._run_worker(work)

    # -------------------------------------------------------------- filtering
    def _on_range(self, value):
        self._restyle_segments()
        today = date.today()
        spans = {"全部时间": None, "近 30 天": 30, "近 90 天": 90, "今年": "year"}
        span = spans.get(value)
        if span is None:
            self.date_range = None
        elif span == "year":
            self.date_range = (date(today.year, 1, 1), today)
        else:
            self.date_range = (today - timedelta(days=span), today)
        self._clear_custom_badge()
        self.refresh_visible()

    def _toggle_dates(self):
        self.dates_open = not self.dates_open
        if self.dates_open:
            self.dates_frame.grid()
            self.from_entry.focus_set()
        else:
            self.dates_frame.grid_remove()
        self.date_toggle.configure(
            text=("自定义日期   ▼" if self.dates_open else "自定义日期   ▶"))

    def _apply_dates(self):
        try:
            start = (datetime.strptime(self.from_date.get().strip(), "%Y-%m-%d").date()
                     if self.from_date.get().strip() else None)
            end = (datetime.strptime(self.to_date.get().strip(), "%Y-%m-%d").date()
                   if self.to_date.get().strip() else None)
            if start and end and start > end:
                raise ValueError("开始日期晚于结束日期")
        except ValueError as exc:
            self.date_hint.configure(text=f"日期无效：{exc}", text_color=t.DANGER)
            self.status_bar.set("日期格式应为 2026-10-25", "danger")
            return
        self.date_range = (start, end) if (start or end) else None
        self.date_hint.configure(text="格式 2026-10-25", text_color=t.TEXT_FAINT)
        if self.date_range:
            self.custom_pill.set(f"{start or '最早'} → {end or '最新'}", "accent")
            self.custom_pill.grid()
            self.custom_clear.grid()
        else:
            self._clear_custom_badge()
        self.refresh_visible()

    def _clear_custom_badge(self):
        self.custom_pill.grid_remove()
        self.custom_clear.grid_remove()

    def _clear_custom_range(self):
        self.from_date.set("")
        self.to_date.set("")
        self.date_range = None
        self.range_filter.set(RANGE_PRESETS[0])
        self._clear_custom_badge()
        self._restyle_segments()
        self.refresh_visible()

    def refresh_visible(self):
        sport = self.sport_filter.get()
        start, end = self.date_range or (None, None)
        self.visible = [ex for ex in self.exercises
                        if (sport == "全部运动" or ex.sport[0] == sport)
                        and (start is None or ex.local_start.date() >= start)
                        and (end is None or ex.local_start.date() <= end)]
        self.row_tags = {}
        self.tree.delete(*self.tree.get_children())
        for number, ex in enumerate(self.visible):
            tags = ["odd"] if number % 2 else []
            if not ex.gps_points:
                tags.append("no_gps")
            label, state = self.row_status.get((ex.record_id, ex.local_start.isoformat()),
                                              ("待导出", None))
            if state:
                tags.append(STATUS_TAGS[state])
            iid = str(number)
            self.row_tags[iid] = list(tags)
            self.tree.insert("", "end", iid=iid, values=(
                ex.local_start.strftime("%Y-%m-%d %H:%M:%S"), ex.sport[0],
                f"{ex.distance / 1000:.2f}", duration_text(ex.duration),
                ex.gps_points, ex.heart_points, label), tags=tuple(tags))
        if self.visible:
            self.tree_wrap.grid()
            self.empty_state.grid_remove()
        else:
            self.tree_wrap.grid_remove()
            self.empty_state.grid()
        self._update_stats()
        self._on_select()

    def _update_stats(self):
        sports = {ex.sport[0] for ex in self.visible}
        self.tiles["total"].set(len(self.visible))
        self.tiles["gps"].set(sum(1 for ex in self.visible if ex.gps_points))
        self.tiles["heart"].set(sum(1 for ex in self.visible if ex.heart_points))
        self.tiles["sports"].set(len(sports))
        self.list_count.set(f"{len(self.visible)} 条")
        if self.step == 2:
            self.next_button.configure(text=f"继续导出 · {len(self.visible)} 条"
                                      if self.visible else "继续导出",
                                      state="normal" if self.visible and not self.busy else "disabled")
            if not self.busy:
                self.status_bar.set(f"当前筛选 {len(self.visible)} 条 · 共 {len(self.exercises)} 条",
                                    "accent")

    def selected_exercises(self):
        chosen = []
        for iid in self.tree.selection():
            index = int(iid)
            if 0 <= index < len(self.visible):
                chosen.append(self.visible[index])
        return chosen

    def _on_select(self, _event=None):
        chosen = self.selected_exercises()
        if not chosen:
            self.selection_pill.set("未选择", "muted")
            self.detail_card.grid_remove()
            return
        self.selection_pill.set(f"已选 {len(chosen)} 条", "accent")
        distance = sum(ex.distance for ex in chosen) / 1000
        duration = sum(ex.duration for ex in chosen)
        if len(chosen) == 1:
            ex = chosen[0]
            notes = "；".join(ex.notes) if ex.notes else "无异常提示"
            text = (f"{ex.local_start:%Y-%m-%d %H:%M} · {ex.sport[0]} · "
                    f"{ex.distance / 1000:.2f} km · {duration_text(ex.duration)} · "
                    f"GPS {ex.gps_points} 点 · 心率 {ex.heart_points} 点\n"
                    f"来源 {ex.source.name}　提示 {notes}")
        else:
            dates = sorted(ex.local_start.date() for ex in chosen)
            warned = sum(1 for ex in chosen if ex.notes)
            text = (f"选中 {len(chosen)} 条 · {dates[0]} 至 {dates[-1]} · "
                    f"合计 {distance:.2f} km / {duration_text(duration)} · "
                    f"{warned} 条带提示")
        self.detail_text.configure(text=text)
        self.detail_card.grid()

    def select_all(self, _event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def select_none(self):
        self.tree.selection_remove(self.tree.selection())

    def select_with_gps(self):
        picks = [str(index) for index, ex in enumerate(self.visible) if ex.gps_points]
        self.tree.selection_set(picks)

    # ---------------------------------------------------------------- export
    def refresh_scope(self):
        selected = len(self.selected_exercises())
        entries = []
        if selected:
            entries.append(("selected", f"所选 {selected} 条"))
        if self.visible:
            entries.append(("visible", f"全部筛选 {len(self.visible)} 条"))
        samples = sample_exercises(self.visible)
        if samples:
            entries.append(("samples", f"测试样本 {len(samples)} 类"))
        if not entries:
            entries.append(("visible", "全部筛选 0 条"))
        labels = [label for _, label in entries]
        labels = [f"  {label}  " for label in labels]
        self.scope_kinds = [kind for kind, _ in entries]
        self.scope_seg.configure(values=labels)
        self.scope.set(self.scope.get() if self.scope.get() in labels else labels[0])
        restyle_segmented(self.scope_seg)
        self.export_button.configure(state="normal" if self.visible and not self.busy else "disabled")

    def current_scope(self):
        labels = list(self.scope_seg.cget("values"))
        label = self.scope.get()
        try:
            index = labels.index(label)
        except ValueError:
            return "visible"
        return self.scope_kinds[index] if 0 <= index < len(self.scope_kinds) else "visible"

    def pick_output(self):
        value = filedialog.askdirectory(title="选择 FIT 输出目录")
        if value:
            self.output.set(value)
            self.save_settings()

    def start_export(self):
        if self.busy:
            return
        if not self.visible:
            self.status_bar.set("没有可导出的记录，请先调整筛选条件", "warning")
            return
        if not self.output.get().strip():
            self.status_bar.set("请先选择 FIT 输出目录", "warning")
            return
        kind = self.current_scope()
        output = Path(self.output.get()).resolve()
        if kind == "samples":
            chosen = sample_exercises(self.visible)
            output = output / "samples"
        elif kind == "selected":
            chosen = self.selected_exercises()
        else:
            chosen = list(self.visible)
        if not chosen:
            self.status_bar.set("请先在列表中选择要导出的记录", "warning")
            return
        source_path = Path(self.source.get()).resolve()
        if output == source_path or source_path in output.parents:
            self.status_bar.set("输出目录不能位于源数据目录内，请更换位置", "danger")
            return
        self.save_settings()
        mode = self.coordinate_mode()
        pack_zip = bool(self.zip_enabled.get())
        self.last_output = output
        chosen_keys = {(ex.record_id, ex.local_start.isoformat()) for ex in chosen}
        for index, ex in enumerate(self.visible):
            key = (ex.record_id, ex.local_start.isoformat())
            if key not in chosen_keys:
                continue
            self.row_status.pop(key, None)
            iid = str(index)
            if iid in self.tree.get_children():
                self.tree.set(iid, "state", "待导出")
                tags = [tag for tag in self.row_tags.get(iid, [])
                        if tag not in STATUS_TAGS.values()]
                self.row_tags[iid] = tags
                self.tree.item(iid, tags=tuple(tags))
        self.result_card.grid_remove()
        self.status_bar.set(f"准备导出 {len(chosen)} 次运动…", "accent")
        self.append_log(f"导出 {len(chosen)} 条 → {output}；坐标：{COORD_MODES[mode]}"
                        + ("；同时生成 ZIP" if pack_zip else ""))
        if pack_zip:
            self.append_log("ZIP 仅包含 FIT；超过 50 MB 自动分为多个可独立导入的包。")
        lookup = {(ex.record_id, ex.local_start.isoformat()): str(index)
                  for index, ex in enumerate(self.visible)}

        def work():
            report = export_exercises(
                chosen, output, mode, self.cancel,
                lambda n, total, result: self.events.put(("export_progress", (n, total, result, lookup))),
                pack_zip=pack_zip,
                zip_progress=lambda n, total, text: self.events.put(("progress", (n, total, text))))
            self.events.put(("exported", report))

        self._run_worker(work)

    def cancel_task(self):
        self.cancel.set()
        self.status_bar.set("正在取消，等待当前记录安全写入…", "warning")

    def open_output(self):
        path = self.last_output or Path(self.output.get())
        if not path.is_dir():
            self.status_bar.set("输出目录尚不存在，完成首次导出后即可打开", "warning")
            return
        os.startfile(str(path.resolve()))

    # -------------------------------------------------------------- appearance
    def _change_appearance(self, _value):
        key = self.appearance_key()
        ctk.set_appearance_mode(key)
        self._style_tree()
        self._restyle_segments()
        self.save_settings()

    def _ui_scale(self):
        """Reuse CTk's DPI factor so ttk widgets stay in step with the CTk layout."""
        try:
            return max(1.0, min(2.5, float(ctk.ScalingTracker.get_window_scaling(self))))
        except Exception:
            return 1.0

    def _style_tree(self):
        palette = t.treeview_palette()
        scale = self._ui_scale()
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Records.Treeview", background=palette["background"],
                        fieldbackground=palette["background"], foreground=palette["foreground"],
                        borderwidth=0, relief="flat", rowheight=int(34 * scale),
                        font=(t.FAMILY, int(10 * scale)))
        style.configure("Records.Treeview.Heading", background=palette["heading"],
                        foreground=palette["heading_text"], borderwidth=0, relief="flat",
                        font=(t.FAMILY, int(10 * scale), "bold"),
                        padding=(10, int(8 * scale)))
        style.map("Records.Treeview.Heading", background=[("active", palette["heading"])],
                  relief=[("active", "flat")])
        style.map("Records.Treeview", background=[("selected", palette["selected"])],
                  foreground=[("selected", palette["selected_text"])])
        try:
            style.layout("Records.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        except tk.TclError:
            pass
        self.tree.configure(style="Records.Treeview")
        self.tree.tag_configure("odd", background=palette["stripe"])
        self.tree.tag_configure("no_gps", foreground=palette["muted_row"])
        self.tree.tag_configure("ok", foreground=palette["ok_row"])
        self.tree.tag_configure("skipped", foreground=palette["muted_row"])
        self.tree.tag_configure("failed", foreground=palette["failed_row"])
        self._tree_mode = ctk.get_appearance_mode()
        if hasattr(self, "rail"):
            self.rail.refresh_theme()

    # ------------------------------------------------------------------- log
    def append_log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", str(text) + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ poll
    def poll(self):
        try:
            if ctk.get_appearance_mode() != self._tree_mode:
                self._style_tree()
        except Exception:
            pass
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "idle":
                self._set_busy(False)
                if self.closing:
                    self.destroy()
                    return
            elif kind == "progress":
                n, total, text = value
                self.status_bar.set_progress(n / max(total, 1))
                self.status_bar.set(text, "accent")
                self.scan_progress.set(n / max(total, 1))
            elif kind == "scanned":
                self._handle_scan(value)
            elif kind == "export_progress":
                n, total, result, lookup = value
                self.status_bar.set_progress(n / max(total, 1))
                label = STATUS_LABELS[result["status"]]
                self.status_bar.set(f"{n}/{total} · {result['date'][:19]} · {label}",
                                    "accent" if result["status"] == "success" else "warning")
                iid = lookup.get((result["record_id"], result["date"]))
                self.row_status[(result["record_id"], result["date"])] = (label, result["status"])
                if iid and iid in self.tree.get_children():
                    self.tree.set(iid, "state", label)
                    tags = list(self.row_tags.get(iid, [])) + [STATUS_TAGS[result["status"]]]
                    self.tree.item(iid, tags=tuple(tags))
                if result["status"] == "failed":
                    self.append_log(f"{result['date'][:19]}：{result.get('error', '未知原因')}")
            elif kind == "exported":
                self._handle_export(value)
            elif kind == "error":
                self.status_bar.set(value, "danger")
                self.append_log(value)
        self.after(100, self.poll)

    def _handle_scan(self, result):
        self.exercises = result.exercises
        self.row_status = {}
        self.scan_progress.grid_remove()
        self.sport_box.configure(values=["全部运动"] + sorted({ex.sport[0] for ex in self.exercises}))
        self.sport_filter.set("全部运动")
        self.range_filter.set(RANGE_PRESETS[0])
        self.date_range = None
        self._clear_custom_badge()
        self._restyle_segments()
        self.picker_card.grid_remove()
        self.summary_card.grid()
        self.summary_path.configure(text=self.source.get())
        self.summary_stats.configure(
            text=f"{len(result.exercises)} 次运动 · {result.files} 个文件 · 去重 {result.duplicates} 条"
                 + (f" · {len(result.warnings)} 条提示" if result.warnings else ""))
        self.append_log(f"扫描完成：{result.files} 个文件，{len(result.exercises)} 次运动，"
                        f"去除 {result.duplicates} 条重复。")
        for warning in result.warnings:
            self.append_log(warning)
        if not result.exercises:
            self.status_bar.set("没有找到可转换记录，请检查源目录", "warning")
            self.append_log("没有找到可转换记录，请检查源目录和扫描提示。")
            return
        self.status_bar.set(f"扫描完成：{len(result.exercises)} 次运动", "success")
        self.unlocked = max(self.unlocked, 2)
        self._style_tree()
        # 扫描结果先入队、任务结束标志后入队，等 busy 清空后再跳转。
        self.after(1, lambda: self.go_step(2))

    def _handle_export(self, value):
        self.append_log(f"报告：{value['report_path']}")
        if value.get("zip_files"):
            count = sum(item["count"] for item in value["zip_files"])
            self.status_bar.set(f"ZIP 已生成：{len(value['zip_files'])} 个包 · {count} 条运动", "success")
            for archive in value["zip_files"]:
                self.append_log(f"ZIP：{archive['file']}（{archive['count']} 个 FIT，"
                                f"{archive['bytes'] / 1_000_000:.2f} MB）")
        elif value.get("zip_error"):
            self.status_bar.set("FIT 已导出，但 ZIP 打包失败", "warning")
            self.append_log(f"ZIP 打包失败：{value['zip_error']}")
        elif value["cancelled"]:
            self.status_bar.set(f"已取消：成功 {value['success']} · 跳过 {value['skipped']} · "
                                f"失败 {value['failed']}", "warning")
        else:
            self.status_bar.set(f"导出完成：成功 {value['success']} · 跳过 {value['skipped']} · "
                                f"失败 {value['failed']}",
                                "success" if not value["failed"] else "warning")
        self.append_log("请在 Zepp 中核对运动日期、距离、时长、心率和地图；限制说明见报告 notes。")
        self._show_result(value)

    def _show_result(self, value):
        self.result_title.configure(text=("导出已取消" if value["cancelled"] else "导出完成")
                                    + f" · 共请求 {value['requested']} 条")
        self.result_pill_success.set(f"成功 {value['success']}", "success")
        self.result_pill_skipped.set(f"跳过 {value['skipped']}",
                                     "muted" if not value["skipped"] else "warning")
        self.result_pill_failed.set(f"失败 {value['failed']}",
                                    "muted" if not value["failed"] else "danger")
        lines = []
        for item in value["results"]:
            if item["status"] == "failed":
                lines.append(f"{item['date'][:19]} {item['sport']}：{item.get('error', '未知原因')}")
        for item in value["zip_files"] if value.get("zip_files") else []:
            lines.append(f"ZIP：{Path(item['file']).name}（{item['count']} 个 FIT）")
        if value.get("zip_error"):
            lines.append(f"ZIP 打包失败：{value['zip_error']}")
        lines.append(f"报告：{value['report_path']}")
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "\n".join(lines))
        self.result_text.configure(state="disabled")
        self.result_detail.header.configure(
            text=("▼   " if self.result_detail.is_open else "▶   ")
                 + ("查看失败原因与报告" if value["failed"] else "查看报告与打包结果"))
        if value["failed"]:
            self.result_detail.set_open(True)
        self.result_card.grid()

    def close(self):
        if self.busy:
            if not messagebox.askyesno("正在处理", "取消当前任务并关闭窗口？已完成的 FIT 会保留。"):
                return
            self.closing = True
            self.cancel_task()
        else:
            self.save_settings()
            self.destroy()


def main(source=None):
    ConverterApp(source).mainloop()
