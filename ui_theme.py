"""
Design tokens for Voilà.

Colors are (light, dark) tuples: CustomTkinter swaps them by itself when the
appearance mode changes, so widgets never need to be recolored by hand.
Only raw Tk parts (text tags) need `pick()` plus a theme callback.
"""

import json
import os

import customtkinter as ctk

C = {
    "bg": ("#F5F4F7", "#111015"),
    "surface": ("#FFFFFF", "#1A1920"),
    "field": ("#F0EEF3", "#24232B"),
    "field_hover": ("#E5E2EA", "#2F2D37"),
    "border": ("#E3E0E8", "#2C2A33"),
    "pill": ("#FFFFFF", "#3A3843"),
    "text": ("#1B1A21", "#EDEBF2"),
    "muted": ("#6E6A7C", "#9692A3"),
    "accent": ("#EA580C", "#F97316"),
    "accent_hover": ("#C2410C", "#EA580C"),
    "danger": ("#DC2626", "#EF4444"),
    "danger_hover": ("#B91C1C", "#DC2626"),
    "success": ("#16A34A", "#22C55E"),
    "warning": ("#D97706", "#F59E0B"),
    "info": ("#2563EB", "#60A5FA"),
    "switch_off": ("#D4D0DB", "#3A3843"),
    "knob": ("#FFFFFF", "#F5F4F7"),
}

FONT = "Segoe UI"
F = {
    "title": ("Segoe UI Semibold", 18),
    "h": ("Segoe UI Semibold", 14),
    "label": ("Segoe UI Semibold", 12),
    "body": ("Segoe UI", 13),
    "small": ("Segoe UI", 11),
    "button": ("Segoe UI Semibold", 13),
    "big": ("Segoe UI Semibold", 15),
    "icon": ("Segoe MDL2 Assets", 15),  # ships with Windows 10/11
}

# Segoe MDL2 Assets glyphs
ICON = {
    "mic": "",
    "speaker": "",
    "settings": "",
    "sun": "",
    "moon": "",
    "eye": "",
    "zoom_in": "",
    "zoom_out": "",
}

UI_CONFIG_FILE = "ui_config.json"


class ThemeManager:
    def __init__(self):
        self.current_theme = "dark"
        self._theme_callbacks = []

    def apply_theme(self, theme_name="dark"):
        self.current_theme = theme_name if theme_name in ("dark", "light") else "dark"
        ctk.set_appearance_mode(self.current_theme)
        self._save_theme_preference()
        for callback in list(self._theme_callbacks):
            try:
                callback(self.current_theme)
            except Exception as e:
                print(f"Error in theme callback: {e}")

    def add_theme_callback(self, callback):
        self._theme_callbacks.append(callback)

    def remove_theme_callback(self, callback):
        if callback in self._theme_callbacks:
            self._theme_callbacks.remove(callback)

    def _save_theme_preference(self):
        try:
            config = {}
            if os.path.exists(UI_CONFIG_FILE):
                with open(UI_CONFIG_FILE, "r") as f:
                    config = json.load(f)
            config["theme"] = self.current_theme
            with open(UI_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving theme preference: {e}")

    def load_theme_preference(self):
        try:
            if os.path.exists(UI_CONFIG_FILE):
                with open(UI_CONFIG_FILE, "r") as f:
                    return json.load(f).get("theme", "dark")
        except Exception as e:
            print(f"Error loading theme preference: {e}")
        return "dark"


theme_manager = ThemeManager()


def apply_theme(theme_name="dark"):
    theme_manager.apply_theme(theme_name)


def add_theme_callback(callback):
    theme_manager.add_theme_callback(callback)


def pick(color):
    """Resolve a (light, dark) token to one hex string for raw Tk options."""
    return color[1] if theme_manager.current_theme == "dark" else color[0]


# --- Widget factories: one place for the look of each control. Keyword args override the defaults. ---

def card(master):
    return ctk.CTkFrame(master, fg_color=C["surface"], border_width=1, border_color=C["border"], corner_radius=14)


def entry(master, **kw):
    return ctk.CTkEntry(master, **{
        "fg_color": C["field"], "border_width": 1, "border_color": C["border"], "text_color": C["text"],
        "placeholder_text_color": C["muted"], "font": F["body"], "height": 36, "corner_radius": 8, **kw})


def combo(master, **kw):
    return ctk.CTkComboBox(master, **{
        "state": "readonly", "fg_color": C["field"], "border_width": 1, "border_color": C["border"],
        "button_color": C["field"], "button_hover_color": C["field_hover"], "text_color": C["text"],
        "dropdown_fg_color": C["surface"], "dropdown_hover_color": C["field"], "dropdown_text_color": C["text"],
        "font": F["body"], "dropdown_font": F["body"], "height": 36, "corner_radius": 8, **kw})


def segmented(master, values, command):
    return ctk.CTkSegmentedButton(
        master, values=values, command=command, font=F["body"], height=34, corner_radius=8,
        fg_color=C["field"], selected_color=C["pill"], selected_hover_color=C["pill"],
        unselected_color=C["field"], unselected_hover_color=C["field_hover"], text_color=C["text"]
    )


def switch(master, command):
    return ctk.CTkSwitch(
        master, text="", width=44, switch_width=40, switch_height=20, border_width=0, command=command,
        fg_color=C["switch_off"], progress_color=C["accent"], button_color=C["knob"], button_hover_color=C["knob"]
    )


def primary_button(master, text, command, **kw):
    return ctk.CTkButton(master, text=text, command=command, **{
        "font": F["button"], "height": 38, "corner_radius": 10, "fg_color": C["accent"],
        "hover_color": C["accent_hover"], "text_color": "#FFFFFF", "text_color_disabled": C["muted"], **kw})


def secondary_button(master, text, command, **kw):
    return ctk.CTkButton(master, text=text, command=command, **{
        "font": F["button"], "height": 38, "corner_radius": 10, "fg_color": C["surface"],
        "hover_color": C["field"], "border_width": 1, "border_color": C["border"], "text_color": C["text"], **kw})


def icon_button(master, glyph, command, size=36):
    return ctk.CTkButton(
        master, text=glyph, command=command, font=F["icon"], width=size, height=size, corner_radius=10,
        fg_color="transparent", hover_color=C["field"], text_color=C["muted"]
    )
