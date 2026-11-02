"""Reusable CustomTkinter widgets shared by the three wizard steps."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont

import customtkinter as ctk

from . import theme as t

TONE_SOFT = {
    "accent": (t.ACCENT_SOFT, t.ACCENT),
    "success": (t.SUCCESS_SOFT, t.SUCCESS),
    "warning": (t.WARNING_SOFT, t.WARNING),
    "danger": (t.DANGER_SOFT, t.DANGER),
    "muted": (t.SURFACE_ALT, t.TEXT_MUTED),
}


def bind_tree(widget, sequence, callback):
    """Bind on a widget and every descendant so a whole card reacts like a row."""
    widget.bind(sequence, callback)
    for child in widget.winfo_children():
        bind_tree(child, sequence, callback)


class Card(ctk.CTkFrame):
    def __init__(self, master, padding=18, fg_color=None, **kwargs):
        kwargs.setdefault("corner_radius", t.RADIUS_CARD)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", t.BORDER)
        super().__init__(master, fg_color=fg_color or t.SURFACE, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.body = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.body.grid(row=0, column=0, sticky="nsew", padx=padding, pady=padding)
        self.body.grid_columnconfigure(0, weight=1)


class SectionTitle(ctk.CTkFrame):
    def __init__(self, master, title, subtitle=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=t.font(t.FONT_SECTION, "bold"), text_color=t.TEXT,
                     anchor="w").grid(row=0, column=0, sticky="w")
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                         anchor="w", justify="left").grid(row=1, column=0, sticky="w", pady=(3, 0))


class StatTile(ctk.CTkFrame):
    def __init__(self, master, label, value="0", **kwargs):
        super().__init__(master, fg_color=t.SURFACE, corner_radius=12, border_width=1,
                         border_color=t.BORDER, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._value = ctk.CTkLabel(self, text=str(value), font=t.font(22, "bold"), text_color=t.TEXT,
                                   anchor="w")
        self._value.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(self, text=label, font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

    def set(self, value):
        self._value.configure(text=str(value))


class Pill(ctk.CTkLabel):
    def __init__(self, master, text="", level="muted", **kwargs):
        kwargs.setdefault("height", 22)
        kwargs.setdefault("corner_radius", 11)
        kwargs.setdefault("font", t.font(t.FONT_TINY, "bold"))
        super().__init__(master, text=text, **kwargs)
        self.set(text, level)

    def set(self, text, level="muted"):
        background, foreground = TONE_SOFT.get(level, TONE_SOFT["muted"])
        self.configure(text=f" {text} ", fg_color=background, text_color=foreground)


class Collapsible(ctk.CTkFrame):
    """Header row plus a body that is only built into the layout once opened."""

    def __init__(self, master, title, *, open_=False, on_toggle=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.title = title
        self.is_open = open_
        self._on_toggle = on_toggle
        self.header = ctk.CTkButton(self, text="", anchor="w", height=28, corner_radius=6,
                                    fg_color="transparent", hover_color=t.HOVER,
                                    text_color=t.TEXT_MUTED, font=t.font(t.FONT_SMALL),
                                    command=self.toggle)
        self.header.grid(row=0, column=0, sticky="ew")
        self.body = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.body.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self.body.grid_columnconfigure(0, weight=1)
        self._sync()

    def _sync(self):
        self.header.configure(text=("▼   " if self.is_open else "▶   ") + self.title)
        if self.is_open:
            self.body.grid()
        else:
            self.body.grid_remove()

    def toggle(self):
        self.set_open(not self.is_open)

    def set_open(self, value):
        self.is_open = bool(value)
        self._sync()
        if self._on_toggle:
            self._on_toggle(self.is_open)


class PathField(ctk.CTkFrame):
    def __init__(self, master, label, variable, *, on_change=None, actions=(), hint=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.variable = variable
        ctk.CTkLabel(self, text=label, font=t.font(t.FONT_SMALL, "bold"), text_color=t.TEXT_MUTED,
                     anchor="w").grid(row=0, column=0, sticky="w", columnspan=4, pady=(0, 6))
        self.entry = ctk.CTkEntry(self, textvariable=variable, state="readonly", height=38,
                                  corner_radius=t.RADIUS_CONTROL, border_color=t.BORDER,
                                  fg_color=t.SURFACE_ALT, text_color=t.TEXT,
                                  font=t.font(t.FONT_BODY))
        self.entry.grid(row=1, column=0, sticky="ew")
        self.buttons = []
        for index, (text, command, primary) in enumerate(actions, start=1):
            button = ctk.CTkButton(self, text=text, command=command, height=38, width=104,
                                   corner_radius=t.RADIUS_CONTROL,
                                   font=t.font(t.FONT_SMALL, "bold"),
                                   fg_color=t.ACCENT if primary else t.SURFACE_ALT,
                                   hover_color=t.ACCENT_HOVER if primary else t.HOVER,
                                   text_color=t.ACCENT_TEXT if primary else t.TEXT,
                                   border_width=0 if primary else 1, border_color=t.BORDER)
            button.grid(row=1, column=index, sticky="e", padx=(8, 0))
            self.buttons.append(button)
        self.hint = None
        if hint:
            self.hint = ctk.CTkLabel(self, text=hint, font=t.font(t.FONT_SMALL), text_color=t.TEXT_FAINT,
                                     anchor="w", justify="left", wraplength=640)
            self.hint.grid(row=2, column=0, sticky="w", columnspan=4, pady=(8, 0))


class EmptyState(ctk.CTkFrame):
    def __init__(self, master, glyph, title, hint="", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=glyph, font=t.font(34), text_color=t.TEXT_FAINT).grid(
            row=0, column=0, pady=(18, 6))
        ctk.CTkLabel(self, text=title, font=t.font(t.FONT_SECTION, "bold"), text_color=t.TEXT).grid(
            row=1, column=0)
        if hint:
            ctk.CTkLabel(self, text=hint, font=t.font(t.FONT_SMALL), text_color=t.TEXT_MUTED,
                         justify="center", wraplength=420).grid(row=2, column=0, pady=(6, 18))


class StepBadge(ctk.CTkFrame):
    """Step marker built from a real SVG (Tk 9 rasterises it) plus a centred label."""

    def __init__(self, master, index, size=28, scale=None, **kwargs):
        super().__init__(master, width=size, height=size, corner_radius=0,
                         fg_color="transparent", **kwargs)
        self.index = index
        self.size = size
        # Follow CTk's own scaling so the marker matches every other widget.
        self.scale = float(scale or self._get_widget_scaling())
        self.px = max(16, round(size * self.scale))
        self.state = "todo"
        self._font = tkfont.Font(family=t.FAMILY, size=-max(9, round(11 * self.scale)),
                                 weight="bold")
        self._icon = tk.Label(self, bd=0, highlightthickness=0, padx=0, pady=0)
        self._icon.place(x=0, y=0)
        self._digit = tk.Label(self, bd=0, highlightthickness=0, padx=0, pady=0,
                               font=self._font)
        self._digit.place(relx=0.5, rely=0.5, anchor="center")
        self._render()

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self._render()

    def refresh_theme(self):
        self._render()

    def _render(self):
        dark = t.is_dark()
        surface = t.pick(t.SURFACE)
        fill, ink = _badge_colors(self.state, dark)
        photo = _badge_photo(self.state, self.px, dark)
        text = "" if self.state == "done" else str(self.index)
        if photo is None:
            # Tk < 9 has no SVG decoder: fall back to a plain rounded marker.
            self._icon.place_forget()
            self.configure(fg_color=fill, corner_radius=self.size // 2)
        else:
            self.configure(fg_color="transparent")
            self._icon.configure(image=photo, bg=surface)
            self._icon.place(x=0, y=0)
        self._digit.configure(text=text, bg=fill, fg=ink)


_BADGE_CACHE: dict = {}


def _badge_colors(state, dark):
    index = 1 if dark else 0
    if state == "current":
        return t.ACCENT[index], t.ON_ACCENT[index]
    if state == "done":
        return t.ACCENT_SOFT[index], t.ACCENT[index]
    if state == "ready":
        return t.SURFACE[index], t.ACCENT[index]
    return t.DISABLED[index], t.DISABLED_TEXT[index]


_CHECK_POINTS = ((8.6, 14.4), (12.2, 17.9), (19.4, 10.1))
_CHECK_HALF_WIDTH = 1.15


def _check_shapes(color):
    """Two filled bars plus joint circles: any stroked or polygon joined shape
    leaves a wedge at the elbow at badge size, overlapping fills cannot."""
    a, b, c = _CHECK_POINTS
    half = _CHECK_HALF_WIDTH
    d1 = (b[0] - a[0], b[1] - a[1])
    d2 = (c[0] - b[0], c[1] - b[1])
    l1, l2 = math.hypot(*d1), math.hypot(*d2)
    n1 = (-d1[1] / l1 * half, d1[0] / l1 * half)
    n2 = (-d2[1] / l2 * half, d2[0] / l2 * half)

    def bar(p, q, normal):
        corners = [(p[0] + normal[0], p[1] + normal[1]), (q[0] + normal[0], q[1] + normal[1]),
                   (q[0] - normal[0], q[1] - normal[1]), (p[0] - normal[0], p[1] - normal[1])]
        return ('<polygon points="'
                + " ".join(f"{x:.2f},{y:.2f}" for x, y in corners) + f'" fill="{color}"/>')

    shapes = [bar(a, b, n1), bar(b, c, n2)]
    shapes += [f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{half:.2f}" fill="{color}"/>'
               for x, y in (a, b, c)]
    return "".join(shapes)


def _badge_photo(state, px, dark):
    """Rasterise the badge SVG at device resolution; Tk does the anti-aliasing."""
    key = (state, px, dark)
    if key not in _BADGE_CACHE:
        index = 1 if dark else 0
        surface = t.SURFACE[index]
        fill, ink = _badge_colors(state, dark)
        ring = t.ACCENT_LINE[index] if state == "ready" else fill
        stroke = "1" if state != "ready" else "1.2"
        shapes = [f'<rect width="28" height="28" fill="{surface}"/>',
                  f'<circle cx="14" cy="14" r="13" fill="{fill}" stroke="{ring}" '
                  f'stroke-width="{stroke}"/>']
        if state == "done":
            shapes.append(_check_shapes(ink))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" '
               f'viewBox="0 0 28 28">' + "".join(shapes) + "</svg>")
        try:
            _BADGE_CACHE[key] = tk.PhotoImage(data=svg, format="svg")
        except tk.TclError:  # Tk < 9 cannot decode SVG
            _BADGE_CACHE[key] = None
    return _BADGE_CACHE[key]


class RailItem(ctk.CTkFrame):
    def __init__(self, master, index, title, subtitle, on_click, last=False, scale=None, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=12, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.index = index
        self.title = title
        self.subtitle = subtitle
        self.state = "todo"
        self._on_click = on_click
        self.badge = StepBadge(self, index, size=28, scale=scale)
        self.badge.grid(row=0, column=0, sticky="n", padx=(0, 10), pady=(8, 0))
        self.text = ctk.CTkFrame(self, fg_color="transparent")
        self.text.grid(row=0, column=1, rowspan=2, sticky="new", pady=(6, 6), padx=(0, 8))
        self.text.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self.text, text=title, anchor="w", height=18,
                                        font=t.font(t.FONT_BODY, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = ctk.CTkLabel(self.text, text=subtitle, anchor="w", height=16,
                                           font=t.font(t.FONT_TINY), text_color=t.TEXT_MUTED,
                                           justify="left", wraplength=148)
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(3, 0))
        if not last:
            self.connector = ctk.CTkFrame(self, width=2, height=12, fg_color=t.BORDER,
                                          corner_radius=1)
            self.connector.grid(row=1, column=0, sticky="n", padx=(0, 10), pady=(3, 3))
        bind_tree(self, "<Button-1>", self._click)
        self.apply("todo")

    def apply(self, state):
        self.state = state
        self.badge.set_state(state)
        clickable = state != "todo"
        if state == "current":
            self.title_label.configure(text_color=t.TEXT)
            self.subtitle_label.configure(text_color=t.TEXT_MUTED)
        elif state == "done":
            self.title_label.configure(text_color=t.TEXT)
            self.subtitle_label.configure(text_color=t.TEXT_MUTED)
        elif state == "ready":
            self.title_label.configure(text_color=t.TEXT_MUTED)
            self.subtitle_label.configure(text_color=t.TEXT_FAINT)
        else:
            self.title_label.configure(text_color=t.DISABLED_TEXT)
            self.subtitle_label.configure(text_color=t.TEXT_FAINT)
        cursor = "hand2" if clickable else "arrow"
        for widget in (self, self.badge, self.text, self.title_label, self.subtitle_label):
            try:
                widget.configure(cursor=cursor)
            except Exception:
                pass

    def refresh_theme(self):
        self.badge.refresh_theme()

    def _click(self, _event=None):
        if self.state != "todo":
            self._on_click(self.index)


class StepRail(ctk.CTkFrame):
    def __init__(self, master, steps, on_select, scale=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.items = []
        for offset, (title, subtitle) in enumerate(steps):
            item = RailItem(self, offset + 1, title, subtitle, on_select,
                            last=offset == len(steps) - 1, scale=scale)
            item.grid(row=offset, column=0, sticky="ew")
            self.items.append(item)

    def update_states(self, current, unlocked=None):
        unlocked = unlocked or current
        for item in self.items:
            if item.index == current:
                item.apply("current")
            elif item.index < current:
                item.apply("done")
            elif item.index <= unlocked:
                item.apply("ready")
            else:
                item.apply("todo")

    def refresh_theme(self):
        for item in self.items:
            item.refresh_theme()


def restyle_segmented(segmented, selected_text=None, normal_text=None):
    """CTk gives every segment one text colour; selected segments need their own."""
    selected = selected_text or t.ON_ACCENT
    normal = normal_text or t.TEXT_MUTED
    current = segmented.get()
    for value, button in segmented._buttons_dict.items():  # noqa: SLF001 - no public API
        if value == current:
            button.configure(text_color=selected, text_color_disabled=selected)
        else:
            button.configure(text_color=normal, text_color_disabled=t.TEXT_FAINT)


class StatusBar(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=t.SURFACE, corner_radius=0, **kwargs)
        self.grid_columnconfigure(2, weight=1)
        self.dot = ctk.CTkLabel(self, text="●", font=t.font(13), text_color=t.TEXT_FAINT, width=16)
        self.dot.grid(row=0, column=0, padx=(18, 0))
        self.label = ctk.CTkLabel(self, text="就绪", anchor="w", font=t.font(t.FONT_SMALL),
                                  text_color=t.TEXT_MUTED)
        self.label.grid(row=0, column=1, sticky="w", padx=(6, 12), pady=10)
        self.progress = ctk.CTkProgressBar(self, width=170, height=6, corner_radius=3,
                                           fg_color=t.DISABLED, progress_color=t.ACCENT)
        self.progress.set(0)
        self.cancel = ctk.CTkButton(self, text="取消任务", width=88, height=28, corner_radius=6,
                                    font=t.font(t.FONT_SMALL), fg_color="transparent",
                                    hover_color=t.HOVER, text_color=t.TEXT_MUTED, border_width=1,
                                    border_color=t.BORDER)

    def set(self, text, level="muted"):
        self.label.configure(text=text, text_color=t.TEXT_MUTED if level == "muted" else t.tone(level))
        self.dot.configure(text_color=t.TEXT_FAINT if level == "muted" else t.tone(level))

    def show_activity(self, visible):
        if visible:
            self.progress.grid(row=0, column=2, sticky="e", padx=(0, 10))
            self.cancel.grid(row=0, column=3, padx=(0, 18))
        else:
            self.progress.grid_remove()
            self.cancel.grid_remove()

    def set_progress(self, value):
        self.progress.set(max(0.0, min(1.0, value)))
