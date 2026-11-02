"""GUI entry point; --cli also supports repeatable headless conversion."""
from pathlib import Path
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="华为运动健康 JSON → FIT")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--cli", action="store_true", help="以命令行模式运行")
    parser.add_argument("--output", type=Path, default=Path("exported_fit"))
    parser.add_argument("--samples", action="store_true", help="仅导出三类测试样本")
    parser.add_argument("--coord", choices=("auto", "gcj02", "wgs84", "omit"), default="auto")
    args = parser.parse_args()
    try:
        from garmin_fit_sdk import Encoder
    except ImportError:
        if args.cli:
            print("缺少 FIT 编码依赖，请安装 requirements.txt 中锁定的 SDK。", file=sys.stderr)
        else:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("缺少依赖", "请运行：python -m pip install -r requirements.txt\n或直接使用打包后的 EXE。")
            root.destroy()
        return 1
    if args.cli:
        from huawei_fit.core import export_exercises, sample_exercises, scan_archive
        try:
            source = args.source or Path("HUAWEI_HEALTH")
            output = args.output.resolve()
            resolved_source = source.resolve()
            if output == resolved_source or resolved_source in output.parents:
                raise ValueError("输出目录应位于源数据目录之外")
            result = scan_archive(source)
            print(json.dumps({"scanned": len(result.exercises), "files": result.files,
                              "duplicates": result.duplicates, "warnings": result.warnings}, ensure_ascii=True))
            if not result.exercises:
                return 1
            chosen = sample_exercises(result.exercises) if args.samples else result.exercises
            report = export_exercises(chosen, output, args.coord)
            print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=True))
            return 1 if report["failed"] else 0
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    from huawei_fit.gui import main as gui_main
    gui_main(args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
