"""Compatibility entry point; the wizard itself lives in ``huawei_fit.ui.app``."""
from __future__ import annotations

from .ui.app import ConverterApp, app_directory, duration_text, main

__all__ = ["ConverterApp", "app_directory", "duration_text", "main"]
