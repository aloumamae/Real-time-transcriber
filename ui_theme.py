"""
UI Theme System for Real-time Transcriber
Design tokens and theme management
"""

import customtkinter as ctk

# Color tokens
THEMES = {
    "dark": {
        "bg": "#0B0F17",
        "surface": "#111827",
        "surface2": "#0F172A",
        "border": "#223046",
        "text_primary": "#E5E7EB",
        "text_secondary": "#9CA3AF",
        "accent": "#3B82F6",
        "success": "#16A34A",
        "danger": "#EF4444",
        "warning": "#F59E0B"
    },
    "light": {
        "bg": "#F8FAFC",
        "surface": "#FFFFFF",
        "surface2": "#F1F5F9",
        "border": "#CBD5E1",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "accent": "#2563EB",
        "success": "#16A34A",
        "danger": "#DC2626",
        "warning": "#D97706"
    }
}

# Radius tokens (in pixels)
RADIUS = {
    "card": 12,
    "input": 10,
    "button": 14
}

# Spacing tokens (in pixels)
SPACING = {
    "padding_external": 16,
    "padding_card": 14,
    "gap": 12,
    "input_height": 36,
    "button_primary_height": 48,
    "button_secondary_height": 40,
    "progress_height": 10
}

class ThemeManager:
    """Manages theme application and state"""

    def __init__(self):
        self.current_theme = "dark"
        self._theme_callbacks = []

    def get_colors(self):
        """Get current theme colors"""
        return THEMES[self.current_theme]

    def get_radius(self):
        """Get radius values"""
        return RADIUS

    def get_spacing(self):
        """Get spacing values"""
        return SPACING

    def apply_theme(self, theme_name="dark"):
        """Apply theme to CustomTkinter and store preference"""
        if theme_name not in THEMES:
            theme_name = "dark"

        self.current_theme = theme_name

        # Set CustomTkinter appearance mode
        if theme_name == "dark":
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

        # Save theme preference
        self._save_theme_preference(theme_name)

        # Notify listeners
        for callback in self._theme_callbacks:
            try:
                callback(theme_name)
            except Exception as e:
                print(f"Error in theme callback: {e}")

    def add_theme_callback(self, callback):
        """Add callback to be called when theme changes"""
        self._theme_callbacks.append(callback)

    def remove_theme_callback(self, callback):
        """Remove theme callback"""
        if callback in self._theme_callbacks:
            self._theme_callbacks.remove(callback)

    def _save_theme_preference(self, theme_name):
        """Save theme preference to config"""
        try:
            import json
            import os

            config_file = "ui_config.json"
            config = {}

            # Load existing config if it exists
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    config = json.load(f)

            # Update theme
            config["theme"] = theme_name

            # Save config
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)

        except Exception as e:
            print(f"Error saving theme preference: {e}")

    def load_theme_preference(self):
        """Load saved theme preference"""
        try:
            import json
            import os

            config_file = "ui_config.json"
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    config = json.load(f)
                    return config.get("theme", "dark")
        except Exception as e:
            print(f"Error loading theme preference: {e}")

        return "dark"

# Global theme manager instance
theme_manager = ThemeManager()

def get_colors():
    """Convenience function to get current colors"""
    return theme_manager.get_colors()

def get_radius():
    """Convenience function to get radius values"""
    return theme_manager.get_radius()

def get_spacing():
    """Convenience function to get spacing values"""
    return theme_manager.get_spacing()

def apply_theme(theme_name="dark"):
    """Convenience function to apply theme"""
    theme_manager.apply_theme(theme_name)

def add_theme_callback(callback):
    """Convenience function to add theme callback"""
    theme_manager.add_theme_callback(callback)

def lighten_color(hex_color, percent=10):
    """Lighten a hex color by the given percentage"""
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    # Calculate new RGB values
    new_rgb = []
    for c in rgb:
        new_c = int(c + (255 - c) * (percent / 100))
        new_rgb.append(min(255, max(0, new_c)))

    return f"#{new_rgb[0]:02x}{new_rgb[1]:02x}{new_rgb[2]:02x}"

def get_hover_color(base_color, lighten_percent=10):
    """Get hover color (lighter version of base color)"""
    return lighten_color(base_color, lighten_percent)

def get_button_colors(button_type):
    """Get button colors based on type (success, danger, secondary)"""
    colors = get_colors()

    if button_type == "success":
        base = colors["success"]
        hover = get_hover_color(base, 12)
    elif button_type == "danger":
        base = colors["danger"]
        hover = get_hover_color(base, 12)
    elif button_type == "secondary":
        # For secondary buttons, use a slightly lighter surface
        base = colors["surface"]
        hover = get_hover_color(base, 8)
    else:
        # Default/fallback
        base = colors["accent"]
        hover = get_hover_color(base, 10)

    return {"fg_color": base, "hover_color": hover}