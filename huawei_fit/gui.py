from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import COORD_MODES, VERSION, export_exercises, sample_exercises, scan_archive, write_json


def app_directory():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def duration_text(seconds):
    seconds = round(seconds)
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


class ConverterApp(tk.Tk):
    def __init__(self, source=None):
        super().__init__()
        self.title("华为运动记录 → FIT")
        self.geometry("1180x830")
        self.minsize(1020, 740)
        self.configure(bg="#f3f5f9")
        self.base = app_directory()
        self.config_path = self.base / "converter_settings.json"
        try:
            settings = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                settings = {}
        except (OSError, ValueError):
            settings = {}
        default_source = self.base / "HUAWEI_HEALTH"
        if not default_source.exists() and (self.base.parent / "HUAWEI_HEALTH").exists():
            default_source = self.base.parent / "HUAWEI_HEALTH"
        self.source = tk.StringVar(value=str(source or settings.get("source", default_source)))
        self.output = tk.StringVar(value=str(settings.get("output", self.base / "exported_fit")))
        mode = settings.get("coordinate", "auto")
        self.coordinate = tk.StringVar(value=COORD_MODES.get(mode, COORD_MODES["auto"]))
        self.sport_filter = tk.StringVar(value="全部运动")
        self.from_date = tk.StringVar()
        self.to_date = tk.StringVar()
        self.summary = tk.StringVar(value="选择华为健康导出目录，扫描后预览运动记录")
        self.status = tk.StringVar(value="就绪")
        self.exercises = []
        self.visible = []
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.last_output = None
        self.controls = []
        self._style()
        self._layout()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)
        if Path(self.source.get()).exists():
            self.after(400, self.scan)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#f3f5f9")
        style.configure("TLabel", background="#f3f5f9", foreground="#26364b")
        style.configure("TButton", padding=(12, 8), font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TButton", background="#2463d5", foreground="white", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#194eaf"), ("disabled", "#b8c7de")],
                  foreground=[("disabled", "#f8faff")])
        style.configure("Treeview", background="white", fieldbackground="white", foreground="#25344b",
                        rowheight=32, font=("Microsoft YaHei UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background="#e8edf5", foreground="#44546b",
                        font=("Microsoft YaHei UI", 10, "bold"), padding=8)
        style.map("Treeview", background=[("selected", "#dbe8ff")], foreground=[("selected", "#16458e")])
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=6)
        style.configure("Horizontal.TProgressbar", background="#2463d5", troughcolor="#e2e8f2", borderwidth=0)

    def _layout(self):
        header = tk.Frame(self, bg="#16365e", padx=26, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="华为运动记录 → FIT", bg="#16365e", fg="white",
                 font=("Microsoft YaHei UI", 21, "bold")).pack(anchor="w")
        tk.Label(header, text="本地转换 · 每次运动一个文件 · 导出后可在 Zepp 中试导入", bg="#16365e",
                 fg="#d3e1f4", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(6, 0))
        body = ttk.Frame(self, padding=(24, 16))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        paths = ttk.Frame(body)
        paths.grid(row=0, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        for row, (label, variable, action) in enumerate((("源数据目录", self.source, self.pick_source),
                                                        ("FIT 输出目录", self.output, self.pick_output))):
            ttk.Label(paths, text=label).grid(row=row, column=0, padx=(0, 14), pady=5, sticky="w")
            entry = ttk.Entry(paths, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            button = ttk.Button(paths, text="选择文件夹", command=action)
            button.grid(row=row, column=2, padx=(10, 0), pady=5)
            self.controls.extend([entry, button])
        scan_button = ttk.Button(paths, text="扫描记录", command=self.scan, style="Accent.TButton")
        scan_button.grid(row=0, column=3, rowspan=2, padx=(12, 0), sticky="ns", pady=5)
        self.controls.append(scan_button)
        ttk.Label(body, textvariable=self.summary, font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=1, column=0, sticky="ew", pady=(15, 10))
        filters = ttk.Frame(body)
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(filters, text="运动").pack(side="left")
        self.sports = ttk.Combobox(filters, textvariable=self.sport_filter, state="readonly", width=15,
                                   values=["全部运动"])
        self.sports.pack(side="left", padx=(8, 18))
        self.sports.bind("<<ComboboxSelected>>", lambda _: self.apply_filters())
        self.controls.append(self.sports)
        for label, variable in (("起始日期", self.from_date), ("结束日期", self.to_date)):
            ttk.Label(filters, text=label).pack(side="left")
            entry = ttk.Entry(filters, textvariable=variable, width=13)
            entry.pack(side="left", padx=(8, 12))
            entry.bind("<Return>", lambda _: self.apply_filters())
            self.controls.append(entry)
        apply_button = ttk.Button(filters, text="应用筛选", command=self.apply_filters)
        apply_button.pack(side="left")
        self.controls.append(apply_button)
        ttk.Label(filters, text="日期格式：2026-10-25", foreground="#6a788d").pack(side="right")
        table = ttk.Frame(body)
        table.grid(row=3, column=0, sticky="nsew")
        columns = ("date", "sport", "distance", "duration", "gps", "heart", "state")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended", height=10)
        for key, label, width in zip(columns, ("运动日期 (原时区)", "运动类型", "距离 / km", "运动时长", "GPS 点", "心率点", "导出状态"),
                                     (200, 135, 110, 110, 90, 90, 140)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=75, anchor="w" if key in ("date", "sport", "state") else "center")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("no_gps", foreground="#896422")
        self.tree.tag_configure("failed", foreground="#b33137")
        self.tree.bind("<<TreeviewSelect>>", self.show_selection)
        self.tree.bind("<Control-a>", self.select_all)
        ttk.Label(body, text="按住 Ctrl / Shift 可多选；无 GPS 的记录仍可导出心率与运动汇总。", foreground="#68768a").grid(
            row=4, column=0, sticky="w", pady=(6, 10))
        coordinates = ttk.Frame(body)
        coordinates.grid(row=5, column=0, sticky="ew")
        ttk.Label(coordinates, text="轨迹坐标").pack(side="left", padx=(0, 12))
        self.coord_box = ttk.Combobox(coordinates, textvariable=self.coordinate, state="readonly", width=36,
                                      values=list(COORD_MODES.values()))
        self.coord_box.pack(side="left")
        self.controls.append(self.coord_box)
        ttk.Label(coordinates, text="未标明坐标系时，自动模式依据高德来源做假设，请先验证样本。",
                  foreground="#68768a").pack(side="left", padx=14)
        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, sticky="ew", pady=(12, 10))
        for label, command, style in (("导出测试样本", lambda: self.export("samples"), "TButton"),
                                       ("导出所选", lambda: self.export("selected"), "TButton"),
                                       ("导出全部筛选结果", lambda: self.export("visible"), "Accent.TButton"),
                                       ("导出 ZIP 包", lambda: self.export("zip"), "TButton")):
            button = ttk.Button(buttons, text=label, command=command, style=style)
            button.pack(side="left", padx=(0, 10))
            self.controls.append(button)
        self.cancel_button = ttk.Button(buttons, text="取消任务", command=self.cancel_task, state="disabled")
        self.cancel_button.pack(side="left")
        ttk.Button(buttons, text="打开输出目录", command=self.open_output).pack(side="right")
        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.grid(row=7, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(body, textvariable=self.status, foreground="#42638e").grid(row=8, column=0, sticky="w")
        log_frame = ttk.Frame(body)
        log_frame.grid(row=9, column=0, sticky="ew", pady=(8, 0))
        self.log = tk.Text(log_frame, height=4, wrap="word", bg="white", fg="#526178", relief="flat",
                           padx=10, pady=8, font=("Microsoft YaHei UI", 9), state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="x", expand=True)
        log_scroll.pack(side="right", fill="y")
        self.append_log(f"版本 {VERSION}。导出文件会完成 FIT 解码与 CRC 校验；Zepp 实际导入效果需在手机端核对。")

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", str(text) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def pick_source(self):
        value = filedialog.askdirectory(title="选择 HUAWEI_HEALTH 或运动明细目录")
        if value:
            self.source.set(value)
            self.scan()

    def pick_output(self):
        value = filedialog.askdirectory(title="选择 FIT 输出目录")
        if value:
            self.output.set(value)

    def save_settings(self):
        try:
            write_json(self.config_path, {"source": self.source.get(), "output": self.output.get(),
                                          "coordinate": self.coordinate_mode()})
        except OSError as exc:
            self.append_log(f"设置未保存：{exc}")

    def coordinate_mode(self):
        return next(k for k, v in COORD_MODES.items() if v == self.coordinate.get())

    def set_busy(self, value):
        self.busy = value
        for widget in self.controls:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="disabled" if value else "readonly")
            else:
                widget.configure(state="disabled" if value else "normal")
        self.cancel_button.configure(state="normal" if value else "disabled")
        if value:
            self.cancel.clear()
            self.progress["value"] = 0

    def run_worker(self, function):
        self.set_busy(True)
        def worker():
            try:
                function()
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("idle", None))
        threading.Thread(target=worker, daemon=True).start()

    def scan(self):
        if self.busy:
            return
        source = Path(self.source.get().strip())
        if not str(self.source.get()).strip():
            messagebox.showinfo("选择数据目录", "请先选择源数据目录")
            return
        self.status.set("正在扫描运动明细…")
        self.save_settings()
        def work():
            result = scan_archive(source, self.cancel,
                                  lambda n, total, text: self.events.put(("progress", (n, total, text))))
            self.events.put(("scanned", result))
        self.run_worker(work)

    def apply_filters(self):
        if self.busy:
            return
        try:
            start = datetime.strptime(self.from_date.get().strip(), "%Y-%m-%d").date() if self.from_date.get().strip() else None
            end = datetime.strptime(self.to_date.get().strip(), "%Y-%m-%d").date() if self.to_date.get().strip() else None
            if start and end and start > end:
                raise ValueError("开始日期晚于结束日期")
        except ValueError as exc:
            messagebox.showerror("日期无效", f"请输入 YYYY-MM-DD 格式的日期。\n{exc}")
            return
        self.visible = [ex for ex in self.exercises
                        if (self.sport_filter.get() == "全部运动" or ex.sport[0] == self.sport_filter.get())
                        and (start is None or ex.local_start.date() >= start)
                        and (end is None or ex.local_start.date() <= end)]
        self.tree.delete(*self.tree.get_children())
        for n, ex in enumerate(self.visible):
            self.tree.insert("", "end", iid=str(n), values=(ex.local_start.strftime("%Y-%m-%d %H:%M:%S"), ex.sport[0],
                             f"{ex.distance / 1000:.2f}", duration_text(ex.duration), ex.gps_points,
                             ex.heart_points, "待导出"), tags=() if ex.gps_points else ("no_gps",))
        self.summary.set(f"共 {len(self.exercises)} 次运动   /   当前显示 {len(self.visible)} 次   /   "
                         f"有 GPS {sum(ex.gps_points > 0 for ex in self.visible)} 次   /   "
                         f"有心率 {sum(ex.heart_points > 0 for ex in self.visible)} 次")

    def show_selection(self, _=None):
        if not self.busy:
            self.status.set(f"显示 {len(self.visible)} 条，已选中 {len(self.tree.selection())} 条")

    def select_all(self, _=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def export(self, kind):
        if self.busy:
            return
        if not self.visible:
            messagebox.showinfo("没有运动记录", "请先扫描目录并检查筛选条件")
            return
        if not self.output.get().strip():
            messagebox.showinfo("选择输出目录", "请先选择 FIT 输出目录")
            return
        output = Path(self.output.get()).resolve()
        if kind == "samples":
            chosen = sample_exercises(self.visible)
            output = output / "samples"
        elif kind == "selected":
            chosen = [self.visible[int(i)] for i in self.tree.selection()]
        else:
            chosen = list(self.visible)
        if not chosen:
            messagebox.showinfo("选择记录", "请先在列表中选中要导出的记录")
            return
        source_path = Path(self.source.get()).resolve()
        if output == source_path or source_path in output.parents:
            messagebox.showerror("输出目录无效", "请将 FIT 输出到源数据目录以外的位置")
            return
        self.save_settings()
        mode = self.coordinate_mode()
        self.last_output = output
        self.status.set(f"准备导出 {len(chosen)} 次运动…")
        self.append_log(f"导出 {len(chosen)} 条 → {output}；坐标：{COORD_MODES[mode]}")
        if kind == "zip":
            self.append_log("将当前筛选结果打包为 ZIP，仅包含 FIT；超过 50 MB 自动分为多个可独立导入的包。")
        def work():
            report = export_exercises(chosen, output, mode, self.cancel,
                                      lambda n, total, result: self.events.put(("export_progress", (n, total, result))),
                                      pack_zip=kind == "zip",
                                      zip_progress=lambda n, total, text: self.events.put(("progress", (n, total, text))))
            self.events.put(("exported", report))
        self.run_worker(work)

    def cancel_task(self):
        self.cancel.set()
        self.status.set("正在取消，等待当前记录安全写入…")

    def open_output(self):
        path = self.last_output or Path(self.output.get())
        if not path.is_dir():
            messagebox.showinfo("目录尚不存在", "完成首次导出后即可打开输出目录")
            return
        os.startfile(str(path.resolve()))

    def poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "idle":
                self.set_busy(False)
                if self.closing:
                    self.destroy()
                    return
            elif kind == "progress":
                n, total, text = value
                self.progress["value"] = n / max(total, 1) * 100
                self.status.set(text)
            elif kind == "scanned":
                self.exercises = value.exercises
                self.sports["values"] = ["全部运动"] + sorted({ex.sport[0] for ex in self.exercises})
                self.sport_filter.set("全部运动")
                # Filtering changes only Tk state; run after the worker idle event.
                self.after(1, self.apply_filters)
                self.append_log(f"扫描完成：{value.files} 个文件，{len(value.exercises)} 次运动，去除 {value.duplicates} 条重复。")
                for warning in value.warnings:
                    self.append_log(warning)
                if not value.exercises:
                    self.append_log("没有找到可转换记录，请检查源目录和扫描提示。")
            elif kind == "export_progress":
                n, total, result = value
                self.progress["value"] = n / max(total, 1) * 100
                label = {"success": "成功", "skipped": "已存在，跳过", "failed": "失败"}[result["status"]]
                self.status.set(f"{n}/{total}   {result['date'][:19]}   {label}")
                for i, ex in enumerate(self.visible):
                    if ex.record_id == result["record_id"] and ex.local_start.isoformat() == result["date"]:
                        self.tree.set(str(i), "state", label)
                        if result["status"] == "failed":
                            self.tree.item(str(i), tags=("failed",))
                if result["status"] == "failed":
                    self.append_log(f"{result['date']}：{result['error']}")
            elif kind == "exported":
                self.status.set(f"{'已取消' if value['cancelled'] else '导出完成'}：成功 {value['success']}，"
                                f"跳过 {value['skipped']}，失败 {value['failed']}")
                if value.get("zip_files"):
                    count = sum(item["count"] for item in value["zip_files"])
                    self.status.set(f"ZIP 已生成：{len(value['zip_files'])} 个包，包含 {count} 条运动；转换失败 {value['failed']} 条")
                    for archive in value["zip_files"]:
                        self.append_log(f"ZIP：{archive['file']}（{archive['count']} 个 FIT，{archive['bytes']/1_000_000:.2f} MB）")
                if value.get("zip_error"):
                    self.status.set("FIT 导出已结束，ZIP 打包失败；请查看下方原因")
                    self.append_log(f"ZIP 打包失败：{value['zip_error']}")
                self.append_log(f"报告：{value['report_path']}")
                self.append_log("请在 Zepp 中核对运动日期、距离、时长、心率和地图；每条记录的限制说明见报告 notes。")
            elif kind == "error":
                self.status.set(value)
                self.append_log(value)
        self.after(100, self.poll)

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
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    ConverterApp(source).mainloop()
