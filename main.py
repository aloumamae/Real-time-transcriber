import threading
import queue
import bisect
import os
import datetime
import time
import json
import subprocess
import unicodedata
from tkinter import messagebox, filedialog
import pyaudiowpatch as pyaudio
import assemblyai as aai
from assemblyai.streaming.v3 import (
    StreamingClient,
    StreamingClientOptions,
    StreamingParameters,
    StreamingEvents,
    BeginEvent,
    TurnEvent,
    TerminationEvent,
    StreamingError,
)
import customtkinter as ctk
import numpy as np

# Config, theme and default Recordings/ live next to main.py, whatever folder the app is launched from.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from ui_theme import theme_manager, get_colors, get_radius, get_spacing, apply_theme, add_theme_callback, get_button_colors

# --- Configurações ---
CONFIG_FILE = "config.json"
ICON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "icons", "voila_logo.ico"))
CHUNK_SIZE = 4096

# Initialize theme system
apply_theme(theme_manager.load_theme_preference())

def apply_window_icon(window):
    """Apply the app icon to a Tk window."""
    try:
        window.iconbitmap(ICON_PATH)
    except Exception:
        try:
            window.tk.call("wm", "iconbitmap", window._w, ICON_PATH)
        except Exception:
            pass
        pass
    try:
        window.tk.call("wm", "iconbitmap", window._w, ICON_PATH)
    except Exception:
        pass
    try:
        window.update_idletasks()
    except Exception:
        pass

class AudioRecorder:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.is_recording = False
        self.mic_stream = None
        self.sys_stream = None
        self.start_time = None
        self.mic_rate = 16000
        self.sys_rate = 16000

    def reinitialize(self):
        try:
            self.p.terminate()
        except Exception:
            pass
        self.p = pyaudio.PyAudio()

    def validate_device_index(self, device_index):
        try:
            self.p.get_device_info_by_index(device_index)
            return True
        except Exception:
            return False

    def get_input_devices(self):
        devices = []
        try:
            info = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
            count = info.get('deviceCount')
            for i in range(count):
                dev = self.p.get_device_info_by_host_api_device_index(info['index'], i)
                if dev['maxInputChannels'] > 0 and not dev['isLoopbackDevice']:
                    devices.append((dev['index'], dev['name'], int(dev['defaultSampleRate']), 1))
        except Exception as e:
            print(f"Erro WASAPI: {e}")
        return devices

    def get_output_loopback_devices(self):
        devices = []
        try:
            for loopback in self.p.get_loopback_device_info_generator():
                max_channels = int(loopback.get('maxInputChannels', 1)) or 1
                devices.append((loopback['index'], loopback['name'], int(loopback['defaultSampleRate']), max_channels))
        except Exception as e:
            print(f"Erro Loopback: {e}")
        return devices

    def _open_streams(self, mic_idx, sys_idx, mic_rate, sys_rate, mic_channels, sys_channels, on_mic_data, on_sys_data, on_mic_level, on_sys_level, use_sys_stream=True):
        self.mic_rate = mic_rate
        self.sys_rate = sys_rate
        mic_channels = max(1, int(mic_channels))
        sys_channels = max(1, int(sys_channels))

        def mic_callback(in_data, frame_count, time_info, status):
            if not self.is_recording: return (None, pyaudio.paComplete)
            audio_data = np.frombuffer(in_data, dtype=np.int16)
            if mic_channels > 1:
                try:
                    audio_data = audio_data.reshape(-1, mic_channels).mean(axis=1).astype(np.int16)
                except Exception:
                    pass
            if on_mic_data:
                on_mic_data(audio_data.tobytes())
            try:
                vol = np.linalg.norm(audio_data) / 500
                on_mic_level(min(vol, 100))
            except: pass
            return (in_data, pyaudio.paContinue)

        def sys_callback(in_data, frame_count, time_info, status):
            if not self.is_recording: return (None, pyaudio.paComplete)
            audio_data = np.frombuffer(in_data, dtype=np.int16)
            if sys_channels > 1:
                try:
                    audio_data = audio_data.reshape(-1, sys_channels).mean(axis=1).astype(np.int16)
                except Exception:
                    pass
            if on_sys_data:
                on_sys_data(audio_data.tobytes())
            try:
                vol = np.linalg.norm(audio_data) / 500
                on_sys_level(min(vol, 100))
            except: pass
            return (in_data, pyaudio.paContinue)

        self.mic_stream = self.p.open(
            format=pyaudio.paInt16, channels=mic_channels, rate=mic_rate, input=True,
            input_device_index=mic_idx, frames_per_buffer=CHUNK_SIZE, stream_callback=mic_callback
        )

        self.sys_stream = None
        if use_sys_stream:
            self.sys_stream = self.p.open(
                format=pyaudio.paInt16, channels=sys_channels, rate=sys_rate, input=True,
                input_device_index=sys_idx, frames_per_buffer=CHUNK_SIZE, stream_callback=sys_callback
            )

        self.mic_stream.start_stream()
        if self.sys_stream:
            self.sys_stream.start_stream()

    def start_recording(self, mic_idx, sys_idx, mic_rate, sys_rate, mic_channels, sys_channels, on_mic_data, on_sys_data, on_mic_level, on_sys_level, use_sys_stream=True):
        self.is_recording = True
        self.start_time = datetime.datetime.now()
        self._open_streams(mic_idx, sys_idx, mic_rate, sys_rate, mic_channels, sys_channels, on_mic_data, on_sys_data, on_mic_level, on_sys_level, use_sys_stream=use_sys_stream)

    def restart_streams(self, mic_idx, sys_idx, mic_rate, sys_rate, mic_channels, sys_channels, on_mic_data, on_sys_data, on_mic_level, on_sys_level, use_sys_stream=True):
        if self.mic_stream:
            self.mic_stream.stop_stream()
            self.mic_stream.close()
        if self.sys_stream:
            self.sys_stream.stop_stream()
            self.sys_stream.close()
        self.is_recording = True
        self._open_streams(mic_idx, sys_idx, mic_rate, sys_rate, mic_channels, sys_channels, on_mic_data, on_sys_data, on_mic_level, on_sys_level, use_sys_stream=use_sys_stream)

    def stop_recording(self, base_folder):
        self.is_recording = False
        if self.mic_stream:
            self.mic_stream.stop_stream()
            self.mic_stream.close()
        if self.sys_stream:
            self.sys_stream.stop_stream()
            self.sys_stream.close()

        # Create folder structure: weekday-date subfolder (for transcript only)
        # Map weekdays to Portuguese
        weekdays_pt = {
            0: "Segunda-feira",  # Monday
            1: "Terça-feira",    # Tuesday
            2: "Quarta-feira",   # Wednesday
            3: "Quinta-feira",   # Thursday
            4: "Sexta-feira",    # Friday
            5: "Sábado",         # Saturday
            6: "Domingo"         # Sunday
        }

        weekday_name = weekdays_pt[self.start_time.weekday()]
        date_str = self.start_time.strftime("%d-%m-%Y")
        date_folder = f"{date_str}-{weekday_name}"

        # Create main date folder only if it doesn't exist
        main_folder_path = os.path.join(base_folder, date_folder)
        os.makedirs(main_folder_path, exist_ok=True)

        # Create subfolder with timestamp (this will be renamed later with the actual title)
        time_folder = self.start_time.strftime("%H-%M-%S")
        full_path_folder = os.path.join(main_folder_path, time_folder)
        os.makedirs(full_path_folder, exist_ok=True)

        return full_path_folder

class TranscriptWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Voilà | Transcrição em Tempo Real")
        self.geometry("900x620")
        self.minsize(720, 480)
        self.resizable(True, True)
        # Center window
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.parent_app = parent
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Font zoom state
        self.current_font_size = 12
        self.default_font_size = 12
        self.min_font_size = 10
        self.max_font_size = 22
        self.font_family = "Segoe UI"

        colors = get_colors()
        spacing = get_spacing()
        radius = get_radius()

        # Track partial lines per speaker
        self.partial_lines = {}
        self.partial_mark_counter = 0

        # Apply theme to window
        self.configure(fg_color=colors["bg"])

        # Textbox with proper styling
        self.textbox = ctk.CTkTextbox(
            self,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            font=(self.font_family, self.current_font_size),
            corner_radius=radius["card"],
            wrap="word"
        )
        self.textbox.pack(fill="both", expand=True, padx=spacing["padding_external"], pady=spacing["padding_external"])
        self.textbox.configure(state="disabled")

        # Configure text tags for speaker highlighting
        self.textbox.tag_config("user", foreground=colors["accent"])
        self.textbox.tag_config("system", foreground=colors["text_secondary"])
        self.textbox.tag_config("error", foreground=colors["danger"])

        # Bind zoom controls
        self.bind_zoom_controls()

        # Add theme callback
        add_theme_callback(self.on_theme_changed)

    def bind_zoom_controls(self):
        """Bind zoom controls to the textbox and window"""
        # Mouse wheel zoom (Ctrl+Scroll)
        self.textbox.bind("<Control-MouseWheel>", self.on_mouse_wheel_zoom)

        # Keyboard zoom shortcuts
        self.bind("<Control-plus>", lambda e: self.zoom_in())
        self.bind("<Control-equal>", lambda e: self.zoom_in())  # Ctrl+= (same as Ctrl++)
        self.bind("<Control-minus>", lambda e: self.zoom_out())
        self.bind("<Control-0>", lambda e: self.zoom_reset())

        # Also bind to textbox for when it has focus
        self.textbox.bind("<Control-plus>", lambda e: self.zoom_in())
        self.textbox.bind("<Control-equal>", lambda e: self.zoom_in())
        self.textbox.bind("<Control-minus>", lambda e: self.zoom_out())
        self.textbox.bind("<Control-0>", lambda e: self.zoom_reset())

    def on_mouse_wheel_zoom(self, event):
        """Handle Ctrl+MouseWheel zoom"""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def zoom_in(self):
        """Increase font size"""
        if self.current_font_size < self.max_font_size:
            self.current_font_size += 1
            self.update_font()

    def zoom_out(self):
        """Decrease font size"""
        if self.current_font_size > self.min_font_size:
            self.current_font_size -= 1
            self.update_font()

    def zoom_reset(self):
        """Reset font size to default"""
        self.current_font_size = self.default_font_size
        self.update_font()

    def update_font(self):
        """Update the textbox font with current size"""
        self.textbox.configure(font=(self.font_family, self.current_font_size))

    def append_text(self, text, is_error=False):
        self.insert_entry(None, text, is_error)

    def insert_entry(self, line_no, text, is_error=False):
        """Insert one final entry as text line `line_no` (1-based); None appends.

        Finals always sit above the partial lines, so line N == history[N-1].
        """
        self.textbox.configure(state="normal")
        self._insert_line("end-1c" if line_no is None else f"{line_no}.0", text, is_error)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def _insert_line(self, index, text, is_error=False):
        # Exactly one text line per entry keeps line numbers == history positions.
        text = text.replace("\n", " ")
        if is_error:
            self.textbox.insert(index, f"⚠️ {text}\n", "error")
        else:
            self._insert_formatted_text(text, index)

    def _format_line(self, source, text, timestamp=None):
        if timestamp:
            time_str = timestamp.strftime("%H:%M:%S")
        else:
            time_str = datetime.datetime.now().strftime("%H:%M:%S")
        return f"[{time_str}] {source}: {text}"

    def set_partial_line(self, source, text, timestamp=None):
        line = self._format_line(source, text, timestamp)
        line_text = line + "\n"
        self.textbox.configure(state="normal")
        if source in self.partial_lines:
            start_mark, end_mark = self.partial_lines[source]
            try:
                start_index = self.textbox.index(start_mark)
                self.textbox.delete(start_mark, end_mark)
                self.textbox.insert(start_index, line_text)
                self.textbox.mark_set(start_mark, start_index)
                self.textbox.mark_gravity(start_mark, "right")
                self.textbox.mark_set(end_mark, f"{start_index} + {len(line_text)}c")
                self.textbox.mark_gravity(end_mark, "left")
            except Exception:
                self._unset_partial_marks(start_mark, end_mark)
                self.partial_lines.pop(source, None)
                self._insert_new_partial_line(source, line_text)
        else:
            self._insert_new_partial_line(source, line_text)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def _insert_new_partial_line(self, source, line_text):
        start_index = self.textbox.index("end-1c")
        self.textbox.insert("end", line_text)
        self.partial_mark_counter += 1
        start_mark = f"partial_start_{self.partial_mark_counter}"
        end_mark = f"partial_end_{self.partial_mark_counter}"
        self.textbox.mark_set(start_mark, start_index)
        self.textbox.mark_gravity(start_mark, "right")
        self.textbox.mark_set(end_mark, f"{start_index} + {len(line_text)}c")
        # Left gravity prevents text inserted at this exact boundary from being
        # absorbed into the preceding partial line.
        self.textbox.mark_gravity(end_mark, "left")
        self.partial_lines[source] = (start_mark, end_mark)

    def _unset_partial_marks(self, start_mark, end_mark):
        for mark in (start_mark, end_mark):
            try:
                self.textbox.mark_unset(mark)
            except Exception:
                pass

    def clear_partial_line(self, source):
        if source not in self.partial_lines:
            return
        start_mark, end_mark = self.partial_lines.pop(source)
        self.textbox.configure(state="normal")
        try:
            self.textbox.delete(start_mark, end_mark)
        except Exception:
            pass
        self._unset_partial_marks(start_mark, end_mark)
        self.textbox.configure(state="disabled")

    def reset_partial_lines(self):
        """Forget all Tk marks before the textbox is fully rebuilt."""
        for start_mark, end_mark in list(self.partial_lines.values()):
            self._unset_partial_marks(start_mark, end_mark)
        self.partial_lines.clear()

    def _insert_formatted_text(self, text, index="end-1c"):
        """Insert text with speaker highlighting at `index`."""
        # Resolve to a fixed position so the two inserts below land together.
        index = self.textbox.index(index)
        tag = None
        if ": " in text:
            speaker, content = text.split(": ", 1)
            if speaker.strip() in [self.parent_app.user_name, "Você"]:
                tag = "user"
            elif speaker.strip() in ["Sistema", "Outros"]:
                tag = "system"
        if tag:
            self.textbox.insert(index, f"{content}\n")
            self.textbox.insert(index, f"{speaker}: ", tag)
        else:
            self.textbox.insert(index, text + "\n")

    def on_theme_changed(self, theme_name):
        """Called when theme changes"""
        colors = theme_manager.get_colors()
        radius = theme_manager.get_radius()

        # Update window background
        self.configure(fg_color=colors["bg"])

        # Update textbox
        self.textbox.configure(
            fg_color=colors["surface2"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        # Update text tags
        self.textbox.tag_config("user", foreground=colors["accent"])
        self.textbox.tag_config("system", foreground=colors["text_secondary"])
        self.textbox.tag_config("error", foreground=colors["danger"])

    def on_close(self):
        theme_manager.remove_theme_callback(self.on_theme_changed)
        self.parent_app.transcript_window = None
        self.destroy()

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Voilà | Configurações")
        default_width = 760
        default_height = 860
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(default_width, max(560, screen_width - 120))
        height = min(default_height, max(520, screen_height - 120))
        self.geometry(f"{width}x{height}")
        self.resizable(True, True)
        self.minsize(560, 520)
        # Center window
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
        self.parent_app = parent
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<FocusIn>", self._on_settings_focus_in)

        # Dirty state tracking
        self.original_values = {}
        self.save_feedback_label = None
        self.output_app_label_to_exe = {}
        self.output_app_exe_to_label = {}
        self.output_apps_poll_job = None
        self.output_apps_refresh_in_progress = False
        self.output_apps_last_refresh_ts = 0.0
        self.output_apps_poll_interval_ms = 3000

        colors = get_colors()
        spacing = get_spacing()
        radius = get_radius()

        # Apply theme to window
        self.configure(fg_color=colors["bg"])

        # Keep settings content scrollable while actions remain fixed.
        self.settings_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=colors["surface2"],
            scrollbar_button_hover_color=colors["border"]
        )
        self.settings_scroll.pack(fill="both", expand=True)

        # User Name Card
        frame_name = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_name.pack(pady=(spacing["padding_external"], spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_name = ctk.CTkFrame(frame_name, fg_color="transparent")
        content_name.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_name,
            text="Nome do Usuário:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.entry_name = ctk.CTkEntry(
            content_name,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            height=spacing["input_height"],
            corner_radius=radius["input"]
        )
        self.entry_name.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self.entry_name.insert(0, self.parent_app.user_name)
        self.entry_name.bind("<KeyRelease>", self.on_value_changed)

        # Participants Card
        frame_participants = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_participants.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_participants = ctk.CTkFrame(frame_participants, fg_color="transparent")
        content_participants.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_participants,
            text="Participantes da Próxima Reunião:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.entry_participants = ctk.CTkEntry(
            content_participants,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            height=spacing["input_height"],
            corner_radius=radius["input"]
        )
        self.entry_participants.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self.entry_participants.insert(0, self.parent_app.participants)
        self.entry_participants.bind("<KeyRelease>", self.on_participants_changed)

        ctk.CTkLabel(
            content_participants,
            text="(separados por espaço - reseta após gravação)",
            text_color=colors["text_secondary"],
            font=("Arial", 10)
        ).pack(anchor="w")

        # Meeting title card (temporary for next meeting)
        frame_meeting_title = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_meeting_title.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_meeting_title = ctk.CTkFrame(frame_meeting_title, fg_color="transparent")
        content_meeting_title.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_meeting_title,
            text="Título da Próxima Reunião:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.entry_meeting_title = ctk.CTkEntry(
            content_meeting_title,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            height=spacing["input_height"],
            corner_radius=radius["input"]
        )
        self.entry_meeting_title.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self.entry_meeting_title.insert(0, self.parent_app.meeting_title)
        self.entry_meeting_title.bind("<KeyRelease>", self.on_value_changed)

        ctk.CTkLabel(
            content_meeting_title,
            text='(opcional - se vazio, usa "meeting"; reseta após gravação)',
            text_color=colors["text_secondary"],
            font=("Arial", 10)
        ).pack(anchor="w")

        # Realtime transcript toggle
        frame_realtime = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_realtime.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_realtime = ctk.CTkFrame(frame_realtime, fg_color="transparent")
        content_realtime.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_realtime,
            text="Transcrição em Tempo Real:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.switch_realtime = ctk.CTkSwitch(
            content_realtime,
            text="Ativar",
            command=self.on_realtime_changed
        )
        self.switch_realtime.pack(anchor="w", pady=(spacing["gap"]/2, 0))
        if self.parent_app.realtime_transcript:
            self.switch_realtime.select()
        else:
            self.switch_realtime.deselect()

        # Language selection (temporary for next meeting)
        frame_language = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_language.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_language = ctk.CTkFrame(frame_language, fg_color="transparent")
        content_language.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_language,
            text="Idioma da Próxima Reunião:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.combo_language = ctk.CTkComboBox(
            content_language,
            values=["Multilingual", "Inglês"],
            state="readonly",
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            button_color=colors["surface2"],
            button_hover_color=colors["border"],
            dropdown_fg_color=colors["surface"],
            dropdown_text_color=colors["text_primary"],
            dropdown_font=("Arial", 12),
            height=spacing["input_height"],
            corner_radius=radius["input"],
            command=self.on_language_changed
        )
        self.combo_language.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self.combo_language.set(self.parent_app.language_choice)
        self._bind_combo_toggle(self.combo_language)
        self.after(0, lambda: self._update_combo_menu_width(self.combo_language))
        self.combo_language.bind("<Configure>", lambda e: self._update_combo_menu_width(self.combo_language))

        ctk.CTkLabel(
            content_language,
            text="(reseta após gravação)",
            text_color=colors["text_secondary"],
            font=("Arial", 10)
        ).pack(anchor="w")

        # Output capture mode (advanced)
        frame_output_capture = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_output_capture.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_output_capture = ctk.CTkFrame(frame_output_capture, fg_color="transparent")
        content_output_capture.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_output_capture,
            text="Captura do Sistema:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.combo_output_capture_mode = ctk.CTkComboBox(
            content_output_capture,
            values=["Sistema inteiro", "App específico"],
            state="readonly",
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            button_color=colors["surface2"],
            button_hover_color=colors["border"],
            dropdown_fg_color=colors["surface"],
            dropdown_text_color=colors["text_primary"],
            dropdown_font=("Arial", 12),
            height=spacing["input_height"],
            corner_radius=radius["input"],
            command=self.on_output_capture_mode_changed
        )
        self.combo_output_capture_mode.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self._bind_combo_toggle(self.combo_output_capture_mode)
        self.after(0, lambda: self._update_combo_menu_width(self.combo_output_capture_mode))
        self.combo_output_capture_mode.bind("<Configure>", lambda e: self._update_combo_menu_width(self.combo_output_capture_mode))
        self.combo_output_capture_mode.set("Sistema inteiro")

        app_row = ctk.CTkFrame(content_output_capture, fg_color="transparent")
        app_row.pack(pady=(spacing["gap"]/2, 0), fill="x")

        self.combo_output_app = ctk.CTkComboBox(
            app_row,
            values=["Selecione um app"],
            state="readonly",
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            button_color=colors["surface2"],
            button_hover_color=colors["border"],
            dropdown_fg_color=colors["surface"],
            dropdown_text_color=colors["text_primary"],
            dropdown_font=("Arial", 12),
            height=spacing["input_height"],
            corner_radius=radius["input"],
            command=self.on_output_app_changed
        )
        self.combo_output_app.pack(side="left", fill="x", expand=True)
        self._bind_combo_toggle(self.combo_output_app)
        self.after(0, lambda: self._update_combo_menu_width(self.combo_output_app))
        self.combo_output_app.bind("<Configure>", lambda e: self._update_combo_menu_width(self.combo_output_app))

        self.lbl_output_capture_status = ctk.CTkLabel(
            content_output_capture,
            text="",
            text_color=colors["text_secondary"],
            font=("Arial", 10)
        )
        self.lbl_output_capture_status.pack(anchor="w")

        # Save directory card
        frame_save_dir = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_save_dir.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_save_dir = ctk.CTkFrame(frame_save_dir, fg_color="transparent")
        content_save_dir.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_save_dir,
            text="Pasta de Salvamento:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        row_dir = ctk.CTkFrame(content_save_dir, fg_color="transparent")
        row_dir.pack(pady=(spacing["gap"]/2, 0), fill="x")

        self.entry_save_dir = ctk.CTkEntry(
            row_dir,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            height=spacing["input_height"],
            corner_radius=radius["input"]
        )
        self.entry_save_dir.pack(side="left", fill="x", expand=True, padx=(0, spacing["gap"]/2))
        self.entry_save_dir.insert(0, self.parent_app.save_directory)
        self.entry_save_dir.bind("<KeyRelease>", self.on_save_dir_changed)

        self.btn_browse_dir = ctk.CTkButton(
            row_dir,
            text="Selecionar",
            width=120,
            height=spacing["input_height"],
            corner_radius=radius["input"],
            command=self.browse_save_directory
        )
        self.btn_browse_dir.pack(side="right")

        ctk.CTkLabel(
            content_save_dir,
            text="(será mantida para as próximas reuniões)",
            text_color=colors["text_secondary"],
            font=("Arial", 10)
        ).pack(anchor="w")

        # AssemblyAI API Key Card
        frame_api = ctk.CTkFrame(
            self.settings_scroll,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        frame_api.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        content_api = ctk.CTkFrame(frame_api, fg_color="transparent")
        content_api.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        ctk.CTkLabel(
            content_api,
            text="AssemblyAI API Key:",
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(anchor="w")

        self.entry_api = ctk.CTkEntry(
            content_api,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text_primary"],
            height=spacing["input_height"],
            corner_radius=radius["input"],
            show="*"
        )
        self.entry_api.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self.entry_api.insert(0, self.parent_app.api_key)
        self.entry_api.bind("<KeyRelease>", self.on_value_changed)

        # Save Button
        frame_btn = ctk.CTkFrame(self, fg_color="transparent")
        frame_btn.pack(pady=(spacing["gap"], spacing["padding_external"]), padx=spacing["padding_external"], fill="x")

        self.btn_save = ctk.CTkButton(
            frame_btn,
            text="Salvar Configurações",
            fg_color=colors["bg"],  # Background color when disabled (ghost style)
            border_width=2,  # Visible border when disabled
            border_color="white",  # White border to indicate inactive state
            text_color=colors["text_primary"],  # Readable text color
            height=spacing["button_primary_height"],
            corner_radius=radius["button"],
            font=("Arial", 14, "bold"),
            command=self.save_settings,
            state="disabled"  # Start disabled
        )
        self.btn_save.pack(fill="x")

        # Initialize output capture controls from app state.
        self.combo_output_capture_mode.set(self.parent_app.sys_capture_mode or "Sistema inteiro")
        self._set_output_capture_controls_state()
        if self.combo_output_capture_mode.get().strip() == "App específico":
            self.refresh_output_apps_async()
            self._start_output_apps_auto_refresh()

        # Store original values and initialize dirty state
        self.store_original_values()

        # Add theme callback
        add_theme_callback(self.on_theme_changed)
        self.after(0, self.bring_to_front)

    def bring_to_front(self):
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(120, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def store_original_values(self):
        """Store the original values when window opens"""
        self.original_values = {
            "user_name": self.entry_name.get().strip(),
            "api_key": self.entry_api.get().strip(),
            "participants": self.entry_participants.get().strip() or "Outros",
            "meeting_title": self.entry_meeting_title.get().strip(),
            "realtime_transcript": bool(self.switch_realtime.get()),
            "language_choice": self.combo_language.get().strip(),
            "save_directory": self.entry_save_dir.get().strip(),
            "sys_capture_mode": self.combo_output_capture_mode.get().strip(),
            "sys_app_target": self._get_selected_output_app_exe()
        }
        self.check_dirty_state()

    def _format_app_display_name(self, exe_name):
        common = {
            "chrome.exe": "Google Chrome",
            "msedge.exe": "Microsoft Edge",
            "firefox.exe": "Mozilla Firefox",
            "zoom.exe": "Zoom",
            "teams.exe": "Microsoft Teams",
            "code.exe": "Visual Studio Code",
            "discord.exe": "Discord",
            "slack.exe": "Slack",
            "spotify.exe": "Spotify",
            "whatsapp.exe": "WhatsApp",
            "whatsapp.root.exe": "WhatsApp",
        }
        exe = (exe_name or "").strip().lower()
        if exe in common:
            return common[exe]
        stem = exe[:-4] if exe.endswith(".exe") else exe
        return " ".join(part.capitalize() for part in stem.replace("_", " ").replace("-", " ").split())

    def _get_selected_output_app_exe(self):
        label = self.combo_output_app.get().strip()
        return self.output_app_label_to_exe.get(label, label)

    def on_value_changed(self, event=None):
        """Called when any input field changes"""
        self.check_dirty_state()

    def _bind_combo_toggle(self, combo):
        if not hasattr(self, "_combo_open"):
            self._combo_open = {}

        def handler(event=None):
            try:
                self._update_combo_menu_width(combo)
                menu = combo._dropdown_menu
                is_open = self._combo_open.get(id(combo), False)
                if is_open:
                    menu.unpost()
                    self._combo_open[id(combo)] = False
                else:
                    if combo is self.combo_output_app and self.combo_output_capture_mode.get().strip() == "App específico":
                        self.refresh_output_apps_async(silent=True)
                    combo._open_dropdown_menu()
                    self._combo_open[id(combo)] = True
            except Exception:
                pass
            return "break"

        try:
            combo._canvas.tag_bind("right_parts", "<Button-1>", handler)
            combo._canvas.tag_bind("dropdown_arrow", "<Button-1>", handler)
        except Exception:
            pass

        try:
            combo._entry.bind("<Button-1>", handler)
        except Exception:
            pass

        try:
            combo._dropdown_menu.bind("<Unmap>", lambda e, c=combo: self._combo_open.__setitem__(id(c), False))
        except Exception:
            pass

    def _update_combo_menu_width(self, combo):
        try:
            width_px = combo.winfo_width() or getattr(combo, "_current_width", 0)
            if width_px <= 0:
                return
            try:
                import tkinter.font as tkfont
                menu_font = combo._dropdown_menu.cget("font")
                font = tkfont.Font(font=menu_font)
                char_width = max(1, font.measure("W"))
                target_chars = int((width_px / char_width)) + 2
            except Exception:
                # Fallback if font measure fails
                avg_char_px = 7
                target_chars = max(18, int(width_px / avg_char_px) + 2)

            combo._dropdown_menu._min_character_width = target_chars
            combo._dropdown_menu._add_menu_commands()
        except Exception:
            pass

    def on_participants_changed(self, event=None):
        """Called when participants field changes - update immediately and check dirty state"""
        participants_text = self.entry_participants.get().strip()
        if participants_text:
            self.parent_app.participants = participants_text
        else:
            self.parent_app.participants = "Outros"
        self.check_dirty_state()

    def on_realtime_changed(self):
        self.parent_app.set_realtime_transcript(bool(self.switch_realtime.get()))
        self.check_dirty_state()

    def on_language_changed(self, value):
        self.parent_app.language_choice = value
        if self.parent_app.is_recording:
            self.parent_app.switch_language()
        self.check_dirty_state()

    def on_save_dir_changed(self, event=None):
        self.check_dirty_state()

    def _set_output_capture_controls_state(self):
        app_mode = self.combo_output_capture_mode.get().strip() == "App específico"
        self.combo_output_app.configure(state="readonly" if app_mode else "disabled")
        if app_mode:
            if self.combo_output_app.get().strip() in ("", "Selecione um app"):
                self.lbl_output_capture_status.configure(text="Selecione o aplicativo alvo.")
            else:
                self.lbl_output_capture_status.configure(text="")
        else:
            self.lbl_output_capture_status.configure(text="")

    def refresh_output_apps_async(self, silent=False):
        if self.output_apps_refresh_in_progress:
            return

        self.output_apps_refresh_in_progress = True
        self.output_apps_last_refresh_ts = time.time()
        if not silent:
            self.lbl_output_capture_status.configure(text="Carregando apps...")

        def worker():
            exe_values = self.parent_app.refresh_output_apps()
            def done():
                self.output_apps_refresh_in_progress = False
                if not self.winfo_exists():
                    return
                self.output_app_label_to_exe = {}
                self.output_app_exe_to_label = {}

                labels = []
                for exe in exe_values:
                    label = self._format_app_display_name(exe)
                    if label in self.output_app_label_to_exe and self.output_app_label_to_exe[label] != exe:
                        label = f"{label} ({exe})"
                    self.output_app_label_to_exe[label] = exe
                    self.output_app_exe_to_label[exe] = label
                    labels.append(label)

                self.combo_output_app.configure(values=labels)
                if self.parent_app.sys_app_target and self.parent_app.sys_app_target in self.output_app_exe_to_label:
                    self.combo_output_app.set(self.output_app_exe_to_label[self.parent_app.sys_app_target])
                elif labels:
                    self.combo_output_app.set(labels[0])
                self._set_output_capture_controls_state()
                self.check_dirty_state()
                if not silent:
                    if exe_values and exe_values[0] != "Nenhum app encontrado":
                        self.lbl_output_capture_status.configure(text=f"{len(exe_values)} apps disponíveis.")
                    else:
                        self.lbl_output_capture_status.configure(text="Nenhum app disponível.")
            try:
                self.after(0, done)
            except Exception:
                self.output_apps_refresh_in_progress = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_settings_focus_in(self, event=None):
        if self.combo_output_capture_mode.get().strip() == "App específico":
            if (time.time() - self.output_apps_last_refresh_ts) >= 1.0:
                self.refresh_output_apps_async(silent=True)

    def _start_output_apps_auto_refresh(self):
        self._stop_output_apps_auto_refresh()
        self.output_apps_poll_job = self.after(
            self.output_apps_poll_interval_ms,
            self._output_apps_auto_refresh_tick
        )

    def _stop_output_apps_auto_refresh(self):
        if self.output_apps_poll_job is not None:
            try:
                self.after_cancel(self.output_apps_poll_job)
            except Exception:
                pass
            self.output_apps_poll_job = None

    def _output_apps_auto_refresh_tick(self):
        self.output_apps_poll_job = None
        if not self.winfo_exists():
            return
        if self.combo_output_capture_mode.get().strip() == "App específico":
            self.refresh_output_apps_async(silent=True)
            self._start_output_apps_auto_refresh()

    def _apply_output_capture_live(self):
        if not self.parent_app.is_recording:
            return
        self.lbl_output_capture_status.configure(text="Aplicando mudanças...")
        threading.Thread(
            target=lambda: self.parent_app.switch_recording_devices(show_errors=False),
            daemon=True
        ).start()
        self.after(800, lambda: self.lbl_output_capture_status.configure(text=""))

    def on_output_capture_mode_changed(self, value):
        self.parent_app.sys_capture_mode = value
        self._set_output_capture_controls_state()
        if value == "App específico":
            self.refresh_output_apps_async()
            self._start_output_apps_auto_refresh()
        else:
            self._stop_output_apps_auto_refresh()
        self.check_dirty_state()
        self._apply_output_capture_live()

    def on_output_app_changed(self, value):
        selected = value.strip()
        self.parent_app.sys_app_target = self.output_app_label_to_exe.get(selected, selected)
        self.check_dirty_state()
        self._apply_output_capture_live()

    def browse_save_directory(self):
        selected = filedialog.askdirectory(
            parent=self,
            initialdir=self.entry_save_dir.get().strip() or self.parent_app.save_directory
        )
        if selected:
            self.entry_save_dir.delete(0, "end")
            self.entry_save_dir.insert(0, selected)
            self.check_dirty_state()

    def check_dirty_state(self):
        """Check if current values differ from original"""
        current_values = {
            "user_name": self.entry_name.get().strip(),
            "api_key": self.entry_api.get().strip(),
            "participants": self.entry_participants.get().strip() or "Outros",
            "meeting_title": self.entry_meeting_title.get().strip(),
            "realtime_transcript": bool(self.switch_realtime.get()),
            "language_choice": self.combo_language.get().strip(),
            "save_directory": self.entry_save_dir.get().strip(),
            "sys_capture_mode": self.combo_output_capture_mode.get().strip(),
            "sys_app_target": self._get_selected_output_app_exe()
        }

        # Check if any value changed
        has_changes = current_values != self.original_values

        # Update button state and appearance
        colors = get_colors()
        if has_changes:
            # Enable button with normal appearance (blue)
            self.btn_save.configure(
                state="normal",
                fg_color=colors["accent"],
                border_width=0,  # No border when active
                text_color="white"
            )
        else:
            # Disable button with ghost appearance (background color + white border)
            self.btn_save.configure(
                state="disabled",
                fg_color=colors["bg"],  # Same as app background
                border_width=2,  # Visible border
                border_color="white",  # White border indicates inactive
                text_color=colors["text_primary"]  # Readable text
            )

    def save_settings(self):
        # Only save if there are changes
        current_values = {
            "user_name": self.entry_name.get().strip(),
            "api_key": self.entry_api.get().strip(),
            "participants": self.entry_participants.get().strip() or "Outros",
            "meeting_title": self.entry_meeting_title.get().strip(),
            "realtime_transcript": bool(self.switch_realtime.get()),
            "language_choice": self.combo_language.get().strip(),
            "save_directory": self.entry_save_dir.get().strip(),
            "sys_capture_mode": self.combo_output_capture_mode.get().strip(),
            "sys_app_target": self._get_selected_output_app_exe()
        }

        if current_values == self.original_values:
            return  # No changes to save

        # Save persistent settings (exclude participants)
        persistent_values = {
            "user_name": current_values["user_name"],
            "api_key": current_values["api_key"],
            "realtime_transcript": current_values["realtime_transcript"],
            "save_directory": current_values["save_directory"],
            "sys_capture_mode": current_values["sys_capture_mode"],
            "sys_app_target": current_values["sys_app_target"]
        }

        # Check if persistent values changed
        persistent_original = {k: v for k, v in self.original_values.items() if k not in ("participants", "meeting_title", "language_choice")}
        if persistent_values != persistent_original:
            self.parent_app.user_name = current_values["user_name"]
            self.parent_app.api_key = current_values["api_key"]
            self.parent_app.set_realtime_transcript(current_values["realtime_transcript"])
            self.parent_app.save_directory = current_values["save_directory"]
            self.parent_app.sys_capture_mode = current_values["sys_capture_mode"]
            self.parent_app.sys_app_target = current_values["sys_app_target"]
            self.parent_app.save_config(show_message=False)

        # Always update temporary settings for the next meeting.
        participants_text = current_values["participants"]
        if participants_text and participants_text != "Outros":
            self.parent_app.participants = participants_text
        else:
            self.parent_app.participants = "Outros"
        self.parent_app.meeting_title = current_values["meeting_title"]
        self.parent_app.language_choice = current_values["language_choice"]
        if current_values["save_directory"]:
            self.parent_app.save_directory = current_values["save_directory"]
        self.parent_app.sys_capture_mode = current_values["sys_capture_mode"]
        self.parent_app.sys_app_target = current_values["sys_app_target"]

        # Update original values
        self.original_values = current_values.copy()

        # Update button appearance to inactive state
        colors = get_colors()
        self.btn_save.configure(
            state="disabled",
            fg_color=colors["bg"],  # Same as app background
            border_width=2,  # Visible border
            border_color="white",  # White border indicates inactive
            text_color=colors["text_primary"]  # Readable text
        )

        # Show inline feedback
        self.show_save_feedback()
        # Close settings after save
        self.on_close()

    def show_save_feedback(self):
        """Show temporary feedback that settings were saved"""
        colors = get_colors()

        # Remove existing feedback if present
        if self.save_feedback_label:
            self.save_feedback_label.destroy()

        # Place feedback inside the button frame to avoid shifting layout
        self.save_feedback_label = ctk.CTkLabel(
            self.btn_save.master,
            text="✓ Configurações salvas",
            text_color=colors["success"],
            font=("Arial", 12, "bold")
        )

        self.save_feedback_label.pack(pady=(0, 5))

        # Auto-hide after 2.5 seconds
        self.after(2500, self.hide_save_feedback)

    def hide_save_feedback(self):
        """Hide the save feedback label"""
        if self.save_feedback_label:
            self.save_feedback_label.destroy()
            self.save_feedback_label = None

    def on_theme_changed(self, theme_name):
        """Called when theme changes"""
        colors = theme_manager.get_colors()
        spacing = theme_manager.get_spacing()
        radius = theme_manager.get_radius()

        # Update window background
        self.configure(fg_color=colors["bg"])

        if hasattr(self, "settings_scroll"):
            self.settings_scroll.configure(
                fg_color="transparent",
                scrollbar_button_color=colors["surface2"],
                scrollbar_button_hover_color=colors["border"]
            )

        # Update all card containers recursively.
        def update_cards(widget):
            if isinstance(widget, ctk.CTkFrame) and hasattr(widget, "cget"):
                try:
                    if widget.cget("border_width") > 0:
                        widget.configure(
                            fg_color=colors["surface"],
                            border_color=colors["border"]
                        )
                except Exception:
                    pass
            for child in widget.winfo_children():
                update_cards(child)

        update_cards(self)

        # Update entries
        self.entry_name.configure(
            fg_color=colors["surface2"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        self.entry_api.configure(
            fg_color=colors["surface2"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        self.entry_meeting_title.configure(
            fg_color=colors["surface2"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        self.entry_participants.configure(
            fg_color=colors["surface2"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        if hasattr(self, "entry_save_dir"):
            self.entry_save_dir.configure(
                fg_color=colors["surface2"],
                border_color=colors["border"],
                text_color=colors["text_primary"]
            )
        if hasattr(self, "btn_browse_dir"):
            self.btn_browse_dir.configure(
                fg_color=colors["surface2"],
                hover_color=colors["border"],
                text_color=colors["text_primary"]
            )

        if hasattr(self, "switch_realtime"):
            self.switch_realtime.configure(
                fg_color=colors["accent"],
                progress_color=colors["surface"],
                text_color=colors["text_primary"]
            )

        if hasattr(self, "combo_language"):
            self.combo_language.configure(
                fg_color=colors["surface2"],
                border_color=colors["border"],
                button_color=colors["surface2"],
                button_hover_color=colors["border"],
                dropdown_fg_color=colors["surface"],
                dropdown_text_color=colors["text_primary"],
                text_color=colors["text_primary"]
            )
            self.after(0, lambda: self._update_combo_menu_width(self.combo_language))

        if hasattr(self, "combo_output_capture_mode"):
            self.combo_output_capture_mode.configure(
                fg_color=colors["surface2"],
                border_color=colors["border"],
                button_color=colors["surface2"],
                button_hover_color=colors["border"],
                dropdown_fg_color=colors["surface"],
                dropdown_text_color=colors["text_primary"],
                text_color=colors["text_primary"]
            )
            self.after(0, lambda: self._update_combo_menu_width(self.combo_output_capture_mode))

        if hasattr(self, "combo_output_app"):
            self.combo_output_app.configure(
                fg_color=colors["surface2"],
                border_color=colors["border"],
                button_color=colors["surface2"],
                button_hover_color=colors["border"],
                dropdown_fg_color=colors["surface"],
                dropdown_text_color=colors["text_primary"],
                text_color=colors["text_primary"]
            )
            self.after(0, lambda: self._update_combo_menu_width(self.combo_output_app))

        # Update button - respect current state
        if self.btn_save.cget("state") == "normal":
            # Button is enabled (blue)
            self.btn_save.configure(
                fg_color=colors["accent"],
                border_width=0,
                text_color="white"
            )
        else:
            # Button is disabled (ghost style)
            self.btn_save.configure(
                fg_color=colors["bg"],  # Same as app background
                border_width=2,  # Visible border
                border_color="white",  # White border indicates inactive
                text_color=colors["text_primary"]  # Readable text
            )

        # Update all labels
        def update_labels(widget):
            if isinstance(widget, ctk.CTkLabel):
                widget.configure(text_color=colors["text_primary"])
            for child in widget.winfo_children():
                update_labels(child)

        update_labels(self)

    def on_close(self):
        if self.check_dirty_state_and_confirm_close():
            self._stop_output_apps_auto_refresh()
            theme_manager.remove_theme_callback(self.on_theme_changed)
            self.parent_app.settings_window = None
            self.destroy()

    def check_dirty_state_and_confirm_close(self):
        current_values = {
            "user_name": self.entry_name.get().strip(),
            "api_key": self.entry_api.get().strip(),
            "participants": self.entry_participants.get().strip() or "Outros",
            "meeting_title": self.entry_meeting_title.get().strip(),
            "realtime_transcript": bool(self.switch_realtime.get()),
            "language_choice": self.combo_language.get().strip(),
            "save_directory": self.entry_save_dir.get().strip(),
            "sys_capture_mode": self.combo_output_capture_mode.get().strip(),
            "sys_app_target": self._get_selected_output_app_exe()
        }
        if current_values != self.original_values:
            return messagebox.askyesno(
                "Alterações não salvas",
                "Há alterações não salvas. Fechar sem salvar?",
                parent=self
            )
        return True

class TranscriptionApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Voilà | Never lose the thread")
        self.after(0, lambda: apply_window_icon(self))
        # Temporary geometry - will be adjusted after UI setup
        self.geometry("420x100")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.recorder = AudioRecorder()
        self.api_key = ""
        self.is_recording = False
        self.streaming_client_mic = None
        self.streaming_client_sys = None
        self.transcript_queue = queue.Queue()
        self.transcript_history = []
        self.partial_transcripts = {}
        self.partial_block_until = {}
        self.last_final_text = {}
        self.last_final_turn_order = {}
        self.ui_dirty = False
        self.last_ui_render = 0.0
        self.render_interval_ms = 200
        self.last_partial_update = {}
        self.realtime_transcript = True
        self.interrupt_split = True
        self.language_choice = "Multilingual"
        self.mic_enabled = True
        self.sys_enabled = True
        self.sys_capture_mode = "Sistema inteiro"
        self.sys_app_target = ""
        self.sys_app_capture_proc = None
        self.sys_app_capture_thread = None
        self.sys_app_stderr_thread = None
        self.sys_capture_rate = 48000
        self.audio_timeline_lock = threading.Lock()
        self.audio_stream_position_ms = {}
        self.audio_wall_segments = {}
        self.turn_start_times = {}
        self.audio_timeline_ready = False
        self.audio_timeline_generation = 0
        self.last_interrupt_time = {}
        self.last_forced_time = {}
        self.interrupt_cooldown_ms = 800
        self.save_directory = os.path.join(os.getcwd(), "Recordings")
        self.transcript_window = None
        self.settings_window = None
        self.mic_devices = []
        self.sys_devices = []
        self.selected_mic = ""
        self.selected_sys = ""
        self.user_name = "Você"
        self.participants = "Outros"  # Default participants name for system audio
        self.meeting_title = ""
        self.transcript_buffer = []  # Buffer for transcripts until folder is created
        self.temp_txt_path = None

        self.load_config()
        self.setup_ui()
        self.populate_devices()
        self.apply_theme_to_widgets()

        # Force initial layout update
        self.update_idletasks()

        self.after(50, self.process_queue)

        # Adjust window size after a longer delay to ensure all widgets are fully rendered
        self.after(150, self.adjust_window_size)

        # Add theme callback to update UI when theme changes
        add_theme_callback(self.on_theme_changed)

    def _run_hidden_command(self, cmd, timeout_sec=4):
        creationflags = 0
        startupinfo = None
        try:
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        except Exception:
            pass
        try:
            return subprocess.check_output(
                cmd,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                creationflags=creationflags,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return ""

    def setup_ui(self):
        # Theme toggle in top right
        colors = get_colors()
        spacing = get_spacing()

        frame_top = ctk.CTkFrame(self, fg_color="transparent")
        frame_top.pack(fill="x", padx=spacing["padding_external"], pady=(spacing["padding_external"], spacing["gap"]))

        # Theme toggle switch (discreet)
        self.theme_switch = ctk.CTkSwitch(
            frame_top,
            text="",
            width=40,
            height=20,
            command=self.toggle_theme
        )
        self.theme_switch.pack(side="right")
        # Set initial state based on current theme
        self.theme_switch.select() if theme_manager.current_theme == "dark" else self.theme_switch.deselect()

        # Device sections as cards
        self.create_device_section("Microfone:", "mic")
        self.create_device_section("Sistema:", "sys")
        if hasattr(self, "switch_mic_enabled"):
            self.switch_mic_enabled.select() if self.mic_enabled else self.switch_mic_enabled.deselect()
        if hasattr(self, "switch_sys_enabled"):
            self.switch_sys_enabled.select() if self.sys_enabled else self.switch_sys_enabled.deselect()

        # Record button and discreet settings button in the same frame
        frame_record = ctk.CTkFrame(self, fg_color="transparent")
        frame_record.pack(pady=(spacing["gap"], spacing["gap"]), padx=spacing["padding_external"], fill="x")

        spacing = get_spacing()
        button_colors = get_button_colors("success")
        self.btn_record = ctk.CTkButton(
            frame_record,
            text="INICIAR GRAVAÇÃO",
            fg_color=button_colors["fg_color"],
            hover_color=button_colors["hover_color"],
            height=spacing["button_primary_height"],
            corner_radius=get_radius()["button"],
            font=("Arial", 14, "bold"),
            command=self.toggle_recording
        )
        self.btn_record.pack(side="left", fill="x", expand=True, padx=(0, spacing["gap"]))

        # Discreet settings button - ghost style
        self.btn_settings = ctk.CTkButton(
            frame_record,
            text="⚙️",
            width=spacing["button_primary_height"],
            height=spacing["button_primary_height"],
            fg_color="transparent",
            border_width=1,
            corner_radius=get_radius()["button"],
            command=self.open_settings_window
        )
        self.btn_settings.pack(side="right")

        # Secondary buttons
        frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        frame_btns.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        colors = get_colors()
        spacing = get_spacing()
        self.btn_transcript = ctk.CTkButton(
            frame_btns,
            text="Ver Transcrição",
            fg_color="transparent",
            border_width=1,
            height=spacing["button_secondary_height"],
            corner_radius=get_radius()["button"],
            command=self.open_transcript_window
        )
        self.btn_transcript.pack(fill="x", pady=(0, spacing["gap"]/2))

        self.btn_folder = ctk.CTkButton(
            frame_btns,
            text="Abrir Pasta",
            fg_color="transparent",
            border_width=1,
            height=spacing["button_secondary_height"],
            corner_radius=get_radius()["button"],
            command=self.open_folder
        )
        self.btn_folder.pack(fill="x")

        # Status badge at bottom - minimal spacing
        self.lbl_status = ctk.CTkLabel(self, text="● Pronto", font=("Arial", 11))
        self.lbl_status.pack(pady=(0, spacing["gap"]))

    def adjust_window_size(self):
        """Adjust window size to fit content automatically"""
        fixed_width = 480  # Increased width to accommodate longer device names
        # Fixed height based on layout analysis - ensures all content fits
        fixed_height = 760  # Height based on content analysis (747px content + 13px padding)

        # Calculate centered position
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (fixed_width // 2)
        y = (screen_height // 2) - (fixed_height // 2)

        # Ensure window stays on screen
        x = max(0, min(x, screen_width - fixed_width))
        y = max(0, min(y, screen_height - fixed_height))

        # Apply geometry
        self.geometry(f'{fixed_width}x{fixed_height}+{x}+{y}')

        # Force layout update to ensure proper rendering
        self.update_idletasks()

        # Set minimum size to prevent shrinking below content size
        self.minsize(fixed_width, fixed_height)

        # Debug logging (can be removed in production)
        # print(f"Window adjusted to {fixed_width}x{fixed_height} at position {x},{y}")

    def create_device_section(self, label, type_key):
        colors = get_colors()
        spacing = get_spacing()
        radius = get_radius()

        # Card frame
        card = ctk.CTkFrame(
            self,
            fg_color=colors["surface"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=radius["card"]
        )
        card.pack(pady=(0, spacing["gap"]), padx=spacing["padding_external"], fill="x")

        # Card content with padding
        content_frame = ctk.CTkFrame(card, fg_color="transparent")
        content_frame.pack(padx=spacing["padding_card"], pady=spacing["padding_card"], fill="x")

        # Header (label + enable switch)
        header_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        header_frame.pack(fill="x")

        ctk.CTkLabel(
            header_frame,
            text=label,
            text_color=colors["text_primary"],
            font=("Arial", 12, "bold")
        ).pack(side="left")

        source_switch = ctk.CTkSwitch(
            header_frame,
            text="Ativo",
            width=70,
            command=lambda t=type_key: self.on_source_enabled_changed(t)
        )
        source_switch.pack(side="right")
        source_switch.select()

        # ComboBox
        combo = ctk.CTkComboBox(
            content_frame,
            fg_color=colors["surface2"],
            border_width=1,
            border_color=colors["border"],
            button_color=colors["surface2"],
            button_hover_color=colors["border"],
            dropdown_fg_color=colors["surface"],
            dropdown_text_color=colors["text_primary"],
            text_color=colors["text_primary"],
            height=spacing["input_height"],
            corner_radius=radius["input"],
            command=lambda value, t=type_key: self.on_device_selected(t, value)
        )
        combo.pack(pady=(spacing["gap"]/2, 0), fill="x")
        self._bind_combo_refresh(combo)
        try:
            combo.configure(state="readonly")
        except Exception:
            try:
                combo._entry.configure(state="readonly")
            except Exception:
                pass

        # Progress bar (thin style)
        progress = ctk.CTkProgressBar(
            content_frame,
            height=spacing["progress_height"],
            fg_color=colors["surface2"],
            progress_color=colors["accent"],
            corner_radius=spacing["progress_height"]/2  # Pill shape
        )
        progress.set(0)
        progress.pack(pady=(spacing["gap"]/2, 0), fill="x")

        if type_key == "mic":
            self.combo_mic = combo
            self.progress_mic = progress
            self.switch_mic_enabled = source_switch
        else:
            self.combo_sys = combo
            self.progress_sys = progress
            self.switch_sys_enabled = source_switch

    def toggle_theme(self):
        """Toggle between dark and light theme"""
        new_theme = "light" if theme_manager.current_theme == "dark" else "dark"
        apply_theme(new_theme)
        # Update switch state
        self.theme_switch.select() if new_theme == "dark" else self.theme_switch.deselect()

    def on_theme_changed(self, theme_name):
        """Called when theme changes externally"""
        self.apply_theme_to_widgets()
        # Update switch state
        self.theme_switch.select() if theme_name == "dark" else self.theme_switch.deselect()

    def apply_theme_to_widgets(self):
        """Apply current theme to all widgets"""
        colors = get_colors()
        spacing = get_spacing()
        radius = get_radius()

        # Update window background
        self.configure(fg_color=colors["bg"])

        # Update theme switch colors
        self.theme_switch.configure(
            fg_color=colors["accent"],
            progress_color=colors["surface"]
        )

        # Update device section cards
        for widget in self.winfo_children():
            if isinstance(widget, ctk.CTkFrame) and hasattr(widget, 'cget'):
                # Check if it's a card (has border)
                try:
                    if widget.cget("border_width") > 0:
                        widget.configure(
                            fg_color=colors["surface"],
                            border_color=colors["border"]
                        )
                except:
                    pass

        # Update combo boxes
        if hasattr(self, 'combo_mic'):
            self.combo_mic.configure(
                fg_color=colors["surface2"],
                border_color=colors["border"],
                button_color=colors["surface2"],
                button_hover_color=colors["border"],
                dropdown_fg_color=colors["surface"],
                dropdown_text_color=colors["text_primary"],
                text_color=colors["text_primary"]
            )

        if hasattr(self, 'combo_sys'):
            self.combo_sys.configure(
                fg_color=colors["surface2"],
                border_color=colors["border"],
                button_color=colors["surface2"],
                button_hover_color=colors["border"],
                dropdown_fg_color=colors["surface"],
                dropdown_text_color=colors["text_primary"],
                text_color=colors["text_primary"]
            )

        if hasattr(self, 'switch_mic_enabled'):
            self.switch_mic_enabled.configure(
                text_color=colors["text_primary"],
                progress_color=colors["accent"]
            )

        if hasattr(self, 'switch_sys_enabled'):
            self.switch_sys_enabled.configure(
                text_color=colors["text_primary"],
                progress_color=colors["accent"]
            )

        # Update progress bars
        if hasattr(self, 'progress_mic'):
            self.progress_mic.configure(
                fg_color=colors["surface2"],
                progress_color=colors["accent"]
            )

        if hasattr(self, 'progress_sys'):
            self.progress_sys.configure(
                fg_color=colors["surface2"],
                progress_color=colors["accent"]
            )

        # Update buttons - maintain correct colors based on recording state
        if self.is_recording:
            button_colors = get_button_colors("danger")
        else:
            button_colors = get_button_colors("success")
        self.btn_record.configure(
            fg_color=button_colors["fg_color"],
            hover_color=button_colors["hover_color"]
        )

        # Update settings button (ghost style)
        secondary_colors = get_button_colors("secondary")
        self.btn_settings.configure(
            fg_color="transparent",
            hover_color=secondary_colors["hover_color"],
            border_color=colors["border"]
        )

        self.btn_transcript.configure(
            fg_color="transparent",
            hover_color=secondary_colors["hover_color"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        self.btn_folder.configure(
            fg_color="transparent",
            hover_color=secondary_colors["hover_color"],
            border_color=colors["border"],
            text_color=colors["text_primary"]
        )

        # Update status label
        self.lbl_status.configure(text_color=colors["text_secondary"])

        # Update all labels
        def update_labels(widget):
            if isinstance(widget, ctk.CTkLabel):
                widget.configure(text_color=colors["text_primary"])
            for child in widget.winfo_children():
                update_labels(child)

        update_labels(self)

    def populate_devices(self):
        try:
            self.mic_devices = self.recorder.get_input_devices()
            self.sys_devices = self.recorder.get_output_loopback_devices()
            mic_values = [f"{d[1]} ({d[2]}Hz)" for d in self.mic_devices]
            sys_values = [f"{d[1]} ({d[2]}Hz)" for d in self.sys_devices]
            self.combo_mic.configure(values=mic_values if mic_values else ["Nenhum Mic Encontrado"])
            self.combo_sys.configure(values=sys_values if sys_values else ["Nenhum Audio Sistema"])

            # Set default selections: try saved selections first, then fall back to first device
            if mic_values:
                if self.selected_mic and self.selected_mic in mic_values:
                    self.combo_mic.set(self.selected_mic)
                else:
                    self.combo_mic.set(mic_values[0])

            if sys_values:
                if self.selected_sys and self.selected_sys in sys_values:
                    self.combo_sys.set(self.selected_sys)
                else:
                    self.combo_sys.set(sys_values[0])
        except Exception as e:
            messagebox.showerror("Erro Audio", f"{e}")

    def refresh_devices(self, preserve_selection=True):
        try:
            current_mic = self.combo_mic.get() if preserve_selection else ""
            current_sys = self.combo_sys.get() if preserve_selection else ""

            # Reinitialize PyAudio to pick up newly added/removed devices
            self.recorder.reinitialize()
            self.mic_devices = self.recorder.get_input_devices()
            self.sys_devices = self.recorder.get_output_loopback_devices()

            mic_values = [f"{d[1]} ({d[2]}Hz)" for d in self.mic_devices]
            sys_values = [f"{d[1]} ({d[2]}Hz)" for d in self.sys_devices]

            self.combo_mic.configure(values=mic_values if mic_values else ["Nenhum Mic Encontrado"])
            self.combo_sys.configure(values=sys_values if sys_values else ["Nenhum Audio Sistema"])

            if mic_values:
                if preserve_selection and current_mic in mic_values:
                    self.combo_mic.set(current_mic)
                else:
                    self.combo_mic.set(mic_values[0])

            if sys_values:
                if preserve_selection and current_sys in sys_values:
                    self.combo_sys.set(current_sys)
                else:
                    self.combo_sys.set(sys_values[0])
        except Exception as e:
            messagebox.showerror("Erro Audio", f"{e}")


    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def set_realtime_transcript(self, enabled):
        self.realtime_transcript = bool(enabled)
        # Clear partials when toggling off
        if not self.realtime_transcript:
            self.partial_transcripts.clear()
            self.render_transcript_window()

    def _bind_combo_refresh(self, combo):
        if not hasattr(self, "_combo_open"):
            self._combo_open = {}

        def handler(event=None):
            self.refresh_devices(preserve_selection=True)
            try:
                menu = combo._dropdown_menu
                is_open = self._combo_open.get(id(combo), False)
                if is_open:
                    menu.unpost()
                    self._combo_open[id(combo)] = False
                else:
                    combo._open_dropdown_menu()
                    self._combo_open[id(combo)] = True
            except Exception:
                pass
            return "break"

        try:
            combo._canvas.tag_bind("right_parts", "<Button-1>", handler)
            combo._canvas.tag_bind("dropdown_arrow", "<Button-1>", handler)
        except Exception:
            pass

        try:
            combo._entry.bind("<Button-1>", handler)
        except Exception:
            pass

        try:
            combo._dropdown_menu.bind("<Unmap>", lambda e, c=combo: self._combo_open.__setitem__(id(c), False))
        except Exception:
            pass

    def on_device_selected(self, type_key, value):
        self.selected_mic = self.combo_mic.get()
        self.selected_sys = self.combo_sys.get()
        self.save_config(show_message=False)
        if self.is_recording:
            self.switch_recording_devices()

    def on_source_enabled_changed(self, type_key):
        if type_key == "mic":
            self.mic_enabled = bool(self.switch_mic_enabled.get())
            if not self.mic_enabled:
                self.progress_mic.set(0)
                self.partial_transcripts.pop(self.user_name, None)
                if self.transcript_window and self.transcript_window.winfo_exists():
                    self.transcript_window.clear_partial_line(self.user_name)
        else:
            self.sys_enabled = bool(self.switch_sys_enabled.get())
            if not self.sys_enabled:
                self.progress_sys.set(0)
                self.partial_transcripts.pop(self.participants, None)
                if self.transcript_window and self.transcript_window.winfo_exists():
                    self.transcript_window.clear_partial_line(self.participants)
        self.save_config(show_message=False)

    def _list_running_apps(self):
        import csv
        import io

        blocklist = {
            "applicationframehost.exe", "searchhost.exe", "shellexperiencehost.exe",
            "startmenuexperiencehost.exe", "runtimebroker.exe", "taskhostw.exe",
            "dwm.exe", "ctfmon.exe", "fontdrvhost.exe", "audiodg.exe",
            "conhost.exe", "svchost.exe", "systemsettings.exe", "explorer.exe"
        }
        preferred = {"zoom.exe", "teams.exe", "chrome.exe", "msedge.exe", "firefox.exe", "discord.exe", "slack.exe", "spotify.exe", "whatsapp.exe"}
        apps = set()

        # Fast list of user-visible apps via PowerShell (includes apps with main window handle).
        raw = self._run_hidden_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -or ($_.MainWindowTitle -and $_.MainWindowTitle.Trim().Length -gt 0) } | Select-Object -ExpandProperty ProcessName"
            ],
            timeout_sec=6
        )
        if raw:
            for line in raw.splitlines():
                name = line.strip().lower()
                if not name:
                    continue
                exe = f"{name}.exe" if not name.endswith(".exe") else name
                if exe in blocklist:
                    continue
                apps.add(exe)

        # Keep important apps even when minimized/tray.
        raw = self._run_hidden_command(["tasklist", "/fo", "csv", "/nh"], timeout_sec=2)
        if raw:
            reader = csv.reader(io.StringIO(raw))
            for row in reader:
                if not row:
                    continue
                exe = row[0].strip().lower()
                if exe in preferred:
                    apps.add(exe)

        return sorted(apps, key=lambda x: (x not in preferred, x))

    def refresh_output_apps(self):
        apps = self._list_running_apps()
        return apps if apps else ["Nenhum app encontrado"]

    def on_sys_capture_mode_changed(self, value):
        self.sys_capture_mode = value
        self.save_config(show_message=False)
        if self.is_recording:
            threading.Thread(target=lambda: self.switch_recording_devices(show_errors=False), daemon=True).start()

    def on_sys_app_selected(self, value):
        self.sys_app_target = value.strip()
        self.save_config(show_message=False)
        if self.is_recording and self.sys_capture_mode == "App específico":
            threading.Thread(target=lambda: self.switch_recording_devices(show_errors=False), daemon=True).start()

    def _process_loopback_helper_paths(self):
        project = os.path.join(os.path.dirname(__file__), "native", "ProcessLoopbackCapture", "ProcessLoopbackCapture.csproj")
        exe_path = os.path.join(
            os.path.dirname(__file__),
            "native",
            "ProcessLoopbackCapture",
            "bin",
            "Release",
            "net9.0-windows",
            "ProcessLoopbackCapture.exe"
        )
        dll_path = os.path.join(
            os.path.dirname(__file__),
            "native",
            "ProcessLoopbackCapture",
            "bin",
            "Release",
            "net9.0-windows",
            "ProcessLoopbackCapture.dll"
        )
        return project, exe_path, dll_path

    def _ensure_process_loopback_helper(self):
        project, exe_path, dll_path = self._process_loopback_helper_paths()
        if os.path.exists(exe_path):
            return ("exe", exe_path)
        if os.path.exists(dll_path):
            return ("dll", dll_path)
        raise RuntimeError(
            "Capturador por app não encontrado. Compile native/ProcessLoopbackCapture/ProcessLoopbackCapture.csproj em Release."
        )

    def _stop_sys_app_capture(self):
        proc = getattr(self, "sys_app_capture_proc", None)
        self.sys_app_capture_proc = None
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.sys_app_capture_thread = None
        self.sys_app_stderr_thread = None

    def _start_sys_app_capture(self):
        self._stop_sys_app_capture()
        if not self.sys_enabled or self.sys_capture_mode != "App específico":
            return
        if not self.sys_app_target:
            raise RuntimeError("Nenhum app selecionado para captura específica.")

        helper_kind, helper_path = self._ensure_process_loopback_helper()
        if helper_kind == "exe":
            cmd = [
                helper_path,
                "--exe",
                self.sys_app_target,
                "--rate",
                str(self.sys_capture_rate),
            ]
        else:
            dotnet_exe = os.path.join("C:\\", "Program Files", "dotnet", "dotnet.exe")
            if not os.path.exists(dotnet_exe):
                dotnet_exe = "dotnet"
            cmd = [
                dotnet_exe,
                helper_path,
                "--exe",
                self.sys_app_target,
                "--rate",
                str(self.sys_capture_rate),
            ]

        creationflags = 0
        startupinfo = None
        try:
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        except Exception:
            creationflags = 0
            startupinfo = None

        self.sys_app_capture_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        def read_stdout():
            read_bytes = CHUNK_SIZE
            bytes_per_ms = int((self.sys_capture_rate * 2) / 1000)  # PCM16 mono
            target_chunk = max(bytes_per_ms * 100, read_bytes)       # send ~100ms per API write
            min_flush = bytes_per_ms * 50                            # API minimum is 50ms
            pending = bytearray()
            proc_ref = self.sys_app_capture_proc
            stream = proc_ref.stdout if proc_ref else None
            while self.is_recording and proc_ref and stream:
                data = stream.read(read_bytes)
                if not data:
                    break
                pending.extend(data)
                callback = getattr(self, "_sys_audio_callback", None)
                while len(pending) >= target_chunk:
                    chunk = bytes(pending[:target_chunk])
                    del pending[:target_chunk]
                    if callback:
                        callback(chunk)
                    try:
                        audio_data = np.frombuffer(chunk, dtype=np.int16)
                        vol = np.linalg.norm(audio_data) / 500 if audio_data.size else 0
                        self.transcript_queue.put(("VU", "sys", min(vol, 100)))
                    except Exception:
                        pass

            if pending and len(pending) >= min_flush:
                callback = getattr(self, "_sys_audio_callback", None)
                chunk = bytes(pending)
                if callback:
                    callback(chunk)
                try:
                    audio_data = np.frombuffer(chunk, dtype=np.int16)
                    vol = np.linalg.norm(audio_data) / 500 if audio_data.size else 0
                    self.transcript_queue.put(("VU", "sys", min(vol, 100)))
                except Exception:
                    pass

        def read_stderr():
            proc_ref = self.sys_app_capture_proc
            stream = proc_ref.stderr if proc_ref else None
            if not stream:
                return
            try:
                for line in iter(stream.readline, b""):
                    if not self.is_recording:
                        break
                    msg = line.decode("utf-8", errors="ignore").strip()
                    if msg:
                        self.log_transcript("Sistema", f"Captura por app: {msg}", True)
            except Exception:
                pass

        self.sys_app_capture_thread = threading.Thread(target=read_stdout, daemon=True)
        self.sys_app_capture_thread.start()
        self.sys_app_stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        self.sys_app_stderr_thread.start()

    def start_recording(self):
        key = self.api_key.strip()
        if not key or len(key) < 10:
            messagebox.showerror("Erro", "Chave API inválida. Configure nas configurações.")
            return
        aai.settings.api_key = key
        
        if not self.mic_enabled and not self.sys_enabled:
            messagebox.showerror("Erro", "Ative Microfone ou Sistema para iniciar a gravação.")
            return
        if self.sys_enabled and self.sys_capture_mode == "App específico":
            if not self.sys_app_target or self.sys_app_target == "Nenhum app encontrado":
                messagebox.showerror("Erro", "Selecione um aplicativo para o modo de captura por app.")
                return

        mic_sel = self.combo_mic.get()
        sys_sel = self.combo_sys.get()
        mic_info = next((d for d in self.mic_devices if f"{d[1]} ({d[2]}Hz)" == mic_sel), None)
        sys_info = next((d for d in self.sys_devices if f"{d[1]} ({d[2]}Hz)" == sys_sel), None)

        if not mic_info or not sys_info:
            messagebox.showerror("Erro", "Dispositivos inválidos.")
            return

        if not self.recorder.validate_device_index(mic_info[0]) or not self.recorder.validate_device_index(sys_info[0]):
            self.recorder.reinitialize()
            self.refresh_devices(preserve_selection=True)
            mic_sel = self.combo_mic.get()
            sys_sel = self.combo_sys.get()
            mic_info = next((d for d in self.mic_devices if f"{d[1]} ({d[2]}Hz)" == mic_sel), None)
            sys_info = next((d for d in self.sys_devices if f"{d[1]} ({d[2]}Hz)" == sys_sel), None)
            if not mic_info or not sys_info:
                messagebox.showerror("Erro", "Dispositivos inválidos.")
                return

        # Save the selected devices to config (silent)
        self.selected_mic = mic_sel
        self.selected_sys = sys_sel
        self.save_config(show_message=False)

        self.is_recording = True
        # Reset current transcript path for a new session
        self.current_txt_path = None
        self.transcript_history = []  # Clear previous transcript history
        self.partial_transcripts.clear()
        self.partial_block_until.clear()
        self.last_final_text.clear()
        self.last_final_turn_order.clear()
        self._reset_audio_timeline(ready=False)
        self.last_interrupt_time.clear()
        self.last_forced_time.clear()

        # Create temp transcript file to avoid data loss during crashes
        try:
            os.makedirs(os.path.join(self.save_directory, "_temp"), exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.temp_txt_path = os.path.join(self.save_directory, "_temp", f"transcript_{ts}.txt")
            self.current_txt_path = self.temp_txt_path
            with open(self.current_txt_path, "a", encoding="utf-8") as f:
                f.write("")  # ensure file exists
        except Exception:
            self.temp_txt_path = None

        # Update button to danger state
        button_colors = get_button_colors("danger")
        self.btn_record.configure(
            text="PARAR GRAVAÇÃO",
            fg_color=button_colors["fg_color"],
            hover_color=button_colors["hover_color"]
        )
        self.open_transcript_window()
        self.log_transcript("App", "Iniciando conexão...", False)

        try:
            stream_sys_rate = self.sys_capture_rate if self.sys_capture_mode == "App específico" else sys_info[2]
            self._connect_streaming_clients(key, mic_info[2], stream_sys_rate)

        except Exception as e:
            self.stop_recording_cleanup()
            self.log_transcript("CRITICO", str(e), True)
            return

        colors = get_colors()
        self.lbl_status.configure(text="● Gravando", text_color=colors["success"])
        
        # Store audio queues for streaming
        self.mic_audio_queue = queue.Queue()
        self.sys_audio_queue = queue.Queue()

        try:
            self._start_audio_streams(mic_info, sys_info, restart=False)
        except Exception as e:
            self.stop_recording_cleanup()
            messagebox.showerror("Erro Áudio", f"Falha ao iniciar gravação: {e}")
            return

        # Don't create folders here - let stop_recording handle folder creation
        # Transcripts will be buffered until stop_recording creates the proper folder structure
        self.transcript_buffer = []  # Buffer for transcripts until folder is created

    def stop_recording(self):
        colors = get_colors()
        self.lbl_status.configure(text="● Salvando...", text_color=colors["warning"])
        try:
            final_meeting_title = self.meeting_title
            final_user_name = self.user_name
            final_participants = self.participants
            self._stop_sys_app_capture()
            folder = self.recorder.stop_recording(self.save_directory)
            if not folder:
                self.stop_recording_cleanup()
                return

            # Move temp transcript to final location
            txt_file_path = os.path.join(folder, "transcript.txt")
            if self.temp_txt_path and os.path.exists(self.temp_txt_path):
                try:
                    os.replace(self.temp_txt_path, txt_file_path)
                except Exception:
                    # fallback: copy contents
                    try:
                        with open(self.temp_txt_path, "r", encoding="utf-8") as src:
                            content = src.read()
                        with open(txt_file_path, "w", encoding="utf-8") as dst:
                            dst.write(content)
                        os.remove(self.temp_txt_path)
                    except Exception:
                        pass
            self.current_txt_path = txt_file_path
            self.flush_transcript_buffer()

            if self.streaming_client_mic:
                self.streaming_client_mic.disconnect(terminate=True)
            if self.streaming_client_sys:
                self.streaming_client_sys.disconnect(terminate=True)
            self.stop_recording_cleanup()

            # Ensure all buffered transcripts are written before proceeding
            self.flush_transcript_buffer()

            # Small delay to ensure file operations are complete
            self.after(
                100,
                lambda: self._finalize_recording_with_title(
                    folder,
                    final_meeting_title,
                    final_user_name,
                    final_participants
                )
            )

        except:
            self.stop_recording_cleanup()
            # Fallback error handling
            try:
                colors = get_colors()
                self.lbl_status.configure(text="● Erro ao salvar", text_color=colors["danger"])
            except:
                pass

    def stop_recording_cleanup(self):
        self.is_recording = False
        self._stop_sys_app_capture()

        # Reset participants to default after recording completes
        self.participants = "Outros"
        self.meeting_title = ""
        self.language_choice = "Multilingual"
        if self.settings_window and self.settings_window.winfo_exists():
            try:
                self.settings_window.combo_language.set(self.language_choice)
                self.settings_window.entry_meeting_title.delete(0, "end")
            except Exception:
                pass

        # Clear transcript buffer
        self.transcript_buffer.clear()
        self.partial_transcripts.clear()
        self.partial_block_until.clear()
        self.last_final_text.clear()
        self.last_final_turn_order.clear()
        self.temp_txt_path = None

        # Reset button to success state
        button_colors = get_button_colors("success")
        self.btn_record.configure(
            text="INICIAR GRAVAÇÃO",
            fg_color=button_colors["fg_color"],
            hover_color=button_colors["hover_color"]
        )
        self.progress_mic.set(0)
        self.progress_sys.set(0)

    def log_transcript(self, source, text, is_error=False, timestamp=None):
        if timestamp:
            time_str = timestamp.strftime("%H:%M:%S")
        else:
            time_str = datetime.datetime.now().strftime("%H:%M:%S")
        msg = f"[{time_str}] {source}: {text}"
        self.transcript_queue.put(("TXT", msg, is_error, timestamp or datetime.datetime.now(), source))

        if self.is_recording and not is_error:
            if getattr(self, 'current_txt_path', None):
                try:
                    with open(self.current_txt_path, "a", encoding="utf-8") as f:
                        f.write(msg + "\n")
                except: pass
            elif hasattr(self, 'transcript_buffer'):
                # Buffer transcripts until folder is created
                self.transcript_buffer.append(msg)

    def flush_transcript_buffer(self):
        """Flush buffered transcripts to the current txt file"""
        if hasattr(self, 'current_txt_path') and hasattr(self, 'transcript_buffer'):
            try:
                with open(self.current_txt_path, "a", encoding="utf-8") as f:
                    for msg in self.transcript_buffer:
                        f.write(msg + "\n")
                self.transcript_buffer.clear()
            except: pass

    def process_queue(self):
        # Time budget: VU meters feed this queue constantly, so draining "until
        # empty" could hold the Tk event loop forever and freeze the window.
        deadline = time.perf_counter() + 0.04
        try:
            while time.perf_counter() < deadline:
                try:
                    item = self.transcript_queue.get_nowait()
                except queue.Empty:
                    break
                if item[0] == "VU":
                    if item[1] == "mic": self.progress_mic.set(item[2])
                    else: self.progress_sys.set(item[2])
                elif item[0] == "TXT":
                    msg = item[1]
                    is_err = item[2]
                    ts = item[3] if len(item) > 3 else datetime.datetime.now()
                    source = item[4] if len(item) > 4 else None
                    # Insert in timestamp order and draw only that line; a full
                    # redraw per line is O(n) and froze long meetings.
                    pos = bisect.bisect_right(self.transcript_history, ts, key=lambda x: x[2])
                    self.transcript_history.insert(pos, (msg, is_err, ts))
                    if self.transcript_window and self.transcript_window.winfo_exists():
                        if source and not is_err:
                            self.transcript_window.clear_partial_line(source)
                        self.transcript_window.insert_entry(pos + 1, msg, is_err)
                elif item[0] == "PARTIAL":
                    source = item[1]
                    text = item[2]
                    ts = item[3] if len(item) > 3 else datetime.datetime.now()
                    block_until = self.partial_block_until.get(source)
                    if block_until and datetime.datetime.now() < block_until:
                        continue
                    if self.last_final_text.get(source) == text:
                        continue
                    self.partial_transcripts[source] = (text, ts)
                    if self.transcript_window and self.transcript_window.winfo_exists():
                        last_ts = self.last_partial_update.get(source, 0.0)
                        if time.time() - last_ts >= (self.render_interval_ms / 1000.0):
                            self.last_partial_update[source] = time.time()
                            self.transcript_window.set_partial_line(source, text, ts)
        except: pass
        self.after(50, self.process_queue)

    def _on_begin(self, client: StreamingClient, event: BeginEvent, source_name):
        # Suppress connection noise in transcript
        return

    def _on_turn(self, client: StreamingClient, event: TurnEvent, source_name):
        turn_key = (source_name, event.turn_order)
        source_enabled = self.mic_enabled if source_name == self.user_name else self.sys_enabled
        if not source_enabled:
            if event.end_of_turn:
                with self.audio_timeline_lock:
                    self.turn_start_times.pop(turn_key, None)
            return

        if not event.transcript:
            if event.end_of_turn:
                with self.audio_timeline_lock:
                    self.turn_start_times.pop(turn_key, None)
            return

        mapped_timestamp = None
        has_word_timing = False
        if event.words:
            try:
                start_ms = event.words[0].start
                if isinstance(start_ms, (int, float)):
                    has_word_timing = True
                    mapped_timestamp = self._wall_time_for_audio_offset(source_name, start_ms)
            except Exception:
                pass

        with self.audio_timeline_lock:
            if has_word_timing:
                # A missing segment can occur during a startup race. Keep one
                # wall-clock fallback for every revision of this same turn.
                self.turn_start_times.setdefault(
                    turn_key, mapped_timestamp or datetime.datetime.now()
                )
            timestamp = self.turn_start_times.get(turn_key)
        if timestamp is None:
            timestamp = datetime.datetime.now()

        if event.transcript and not event.end_of_turn:
            other = self.participants if source_name == self.user_name else self.user_name
            self.last_interrupt_time[source_name] = datetime.datetime.now()
            self._maybe_force_endpoint(other)

        if self.realtime_transcript:
            if event.end_of_turn:
                last_turn = self.last_final_turn_order.get(source_name, -1)
                if event.turn_order <= last_turn:
                    with self.audio_timeline_lock:
                        self.turn_start_times.pop(turn_key, None)
                    return
                self.last_final_turn_order[source_name] = event.turn_order
                self.partial_transcripts.pop(source_name, None)
                self.partial_block_until[source_name] = datetime.datetime.now() + datetime.timedelta(milliseconds=600)
                self.last_final_text[source_name] = event.transcript
                self.log_transcript(source_name, event.transcript, False, timestamp)
                with self.audio_timeline_lock:
                    self.turn_start_times.pop(turn_key, None)
            else:
                self.transcript_queue.put(("PARTIAL", source_name, event.transcript, timestamp))
        else:
            if event.end_of_turn:
                last_turn = self.last_final_turn_order.get(source_name, -1)
                if event.turn_order <= last_turn:
                    with self.audio_timeline_lock:
                        self.turn_start_times.pop(turn_key, None)
                    return
                self.last_final_turn_order[source_name] = event.turn_order
                self.log_transcript(source_name, event.transcript, False, timestamp)
                with self.audio_timeline_lock:
                    self.turn_start_times.pop(turn_key, None)

    def _reset_audio_timeline(self, ready=True):
        """Reset stream offsets when a new pair of API connections is used."""
        with self.audio_timeline_lock:
            self.audio_stream_position_ms = {
                self.user_name: 0.0,
                self.participants: 0.0,
            }
            self.audio_wall_segments = {
                self.user_name: [],
                self.participants: [],
            }
            self.turn_start_times.clear()
            self.audio_timeline_ready = ready
            self.audio_timeline_generation += 1

    def _record_audio_buffer(
        self, source_name, byte_count, sample_rate, captured_at=None, expected_generation=None
    ):
        """Map successfully streamed PCM16 mono bytes to the Windows wall clock."""
        if not byte_count or not sample_rate:
            return
        captured_at = captured_at or datetime.datetime.now()
        duration_ms = byte_count / (sample_rate * 2.0) * 1000.0
        wall_start = captured_at - datetime.timedelta(milliseconds=duration_ms)

        with self.audio_timeline_lock:
            if not self.audio_timeline_ready or (
                expected_generation is not None
                and expected_generation != self.audio_timeline_generation
            ):
                return
            stream_start = self.audio_stream_position_ms.setdefault(source_name, 0.0)
            stream_end = stream_start + duration_ms
            segments = self.audio_wall_segments.setdefault(source_name, [])

            should_merge = False
            if segments:
                gap_ms = (wall_start - segments[-1]["wall_end"]).total_seconds() * 1000.0
                should_merge = abs(gap_ms) <= 250.0

            if should_merge:
                segments[-1]["stream_end"] = stream_end
                segments[-1]["wall_end"] = captured_at
            else:
                segments.append({
                    "stream_start": stream_start,
                    "stream_end": stream_end,
                    "wall_start": wall_start,
                    "wall_end": captured_at,
                })
            self.audio_stream_position_ms[source_name] = stream_end

    def _wall_time_for_audio_offset(self, source_name, offset_ms):
        """Convert an AssemblyAI per-connection audio offset to wall time."""
        if not isinstance(offset_ms, (int, float)):
            return None
        with self.audio_timeline_lock:
            segments = list(self.audio_wall_segments.get(source_name, ()))
        for segment in reversed(segments):
            if segment["stream_start"] <= offset_ms <= segment["stream_end"]:
                relative_ms = offset_ms - segment["stream_start"]
                return segment["wall_start"] + datetime.timedelta(milliseconds=relative_ms)
        return None


    def _maybe_force_endpoint(self, source_name):
        now = datetime.datetime.now()
        last_forced = self.last_forced_time.get(source_name)
        if last_forced and (now - last_forced).total_seconds() * 1000 < self.interrupt_cooldown_ms:
            return
        try:
            if source_name == self.user_name and self.streaming_client_mic:
                self.streaming_client_mic.force_endpoint()
            elif source_name == self.participants and self.streaming_client_sys:
                self.streaming_client_sys.force_endpoint()
            self.last_forced_time[source_name] = now
        except Exception:
            pass


    def _on_error(self, client: StreamingClient, error: StreamingError, source_name):
        self.transcript_queue.put(("TXT", f"ERRO API {source_name}: {error}", True, datetime.datetime.now()))

    def _on_terminated(self, client: StreamingClient, event: TerminationEvent, source_name):
        # Suppress connection noise in transcript
        return

    def _connect_streaming_clients(self, key, mic_rate, sys_rate):
        self._reset_audio_timeline(ready=False)
        # Create microphone streaming client
        self.streaming_client_mic = StreamingClient(
            StreamingClientOptions(
                api_key=key,
                api_host="streaming.assemblyai.com",
            )
        )

        # Create system audio streaming client
        self.streaming_client_sys = StreamingClient(
            StreamingClientOptions(
                api_key=key,
                api_host="streaming.assemblyai.com",
            )
        )

        # Set up event handlers for microphone client
        self.streaming_client_mic.on(StreamingEvents.Begin, lambda client, event: self._on_begin(client, event, "Microfone"))
        self.streaming_client_mic.on(StreamingEvents.Turn, lambda client, event: self._on_turn(client, event, self.user_name))
        self.streaming_client_mic.on(StreamingEvents.Error, lambda client, error: self._on_error(client, error, "Microfone"))
        self.streaming_client_mic.on(StreamingEvents.Termination, lambda client, event: self._on_terminated(client, event, "Microfone"))

        # Set up event handlers for system audio client
        self.streaming_client_sys.on(StreamingEvents.Begin, lambda client, event: self._on_begin(client, event, "Sistema"))
        self.streaming_client_sys.on(StreamingEvents.Turn, lambda client, event: self._on_turn(client, event, self.participants))
        self.streaming_client_sys.on(StreamingEvents.Error, lambda client, error: self._on_error(client, error, "Sistema"))
        self.streaming_client_sys.on(StreamingEvents.Termination, lambda client, event: self._on_terminated(client, event, "Sistema"))

        # Connect both clients with selected language settings
        self.streaming_client_mic.connect(self._get_streaming_params(mic_rate))
        self.streaming_client_sys.connect(self._get_streaming_params(sys_rate))
        # Audio callbacks may now start feeding this fresh pair of connections.
        self._reset_audio_timeline(ready=True)

    def _get_streaming_params(self, sample_rate):
        language = self.language_choice
        if language == "Inglês":
            return StreamingParameters(
                sample_rate=sample_rate,
                format_turns=True,
                speech_model="universal-streaming-english",
                language_detection=False,
            )
        return StreamingParameters(
            sample_rate=sample_rate,
            format_turns=True,
            speech_model="universal-streaming-multilingual",
            language_detection=True,
        )

    def _start_audio_streams(self, mic_info, sys_info, restart=False):
        self._stop_sys_app_capture()
        use_sys_stream = self.sys_capture_mode != "App específico"
        target_sys_rate = self.sys_capture_rate if not use_sys_stream else sys_info[2]
        target_sys_channels = 1 if not use_sys_stream else sys_info[3]

        def mic_audio_callback(audio_data):
            if not self.mic_enabled:
                self.transcript_queue.put(("VU", "mic", 0))
                return
            with self.audio_timeline_lock:
                mic_client = self.streaming_client_mic if self.audio_timeline_ready else None
                timeline_generation = self.audio_timeline_generation
            if mic_client:
                captured_at = datetime.datetime.now()
                try:
                    mic_client.stream(audio_data)
                    self._record_audio_buffer(
                        self.user_name,
                        len(audio_data),
                        mic_info[2],
                        captured_at,
                        expected_generation=timeline_generation,
                    )
                except Exception as e:
                    print(f"Error sending mic audio: {e}")

        def sys_audio_callback(audio_data):
            if not self.sys_enabled:
                self.transcript_queue.put(("VU", "sys", 0))
                return
            with self.audio_timeline_lock:
                sys_client = self.streaming_client_sys if self.audio_timeline_ready else None
                timeline_generation = self.audio_timeline_generation
            if sys_client:
                captured_at = datetime.datetime.now()
                try:
                    sys_client.stream(audio_data)
                    self._record_audio_buffer(
                        self.participants,
                        len(audio_data),
                        target_sys_rate,
                        captured_at,
                        expected_generation=timeline_generation,
                    )
                except Exception as e:
                    print(f"Error sending sys audio: {e}")

        self._sys_audio_callback = sys_audio_callback

        if restart:
            self.recorder.restart_streams(
                mic_idx=mic_info[0],
                sys_idx=sys_info[0],
                mic_rate=mic_info[2],
                sys_rate=target_sys_rate,
                mic_channels=mic_info[3],
                sys_channels=target_sys_channels,
                on_mic_data=mic_audio_callback,
                on_sys_data=sys_audio_callback if use_sys_stream else None,
                on_mic_level=lambda v: self.transcript_queue.put(("VU", "mic", v)),
                on_sys_level=lambda v: self.transcript_queue.put(("VU", "sys", v)),
                use_sys_stream=use_sys_stream
            )
        else:
            self.recorder.start_recording(
                mic_idx=mic_info[0],
                sys_idx=sys_info[0],
                mic_rate=mic_info[2],
                sys_rate=target_sys_rate,
                mic_channels=mic_info[3],
                sys_channels=target_sys_channels,
                on_mic_data=mic_audio_callback,
                on_sys_data=sys_audio_callback if use_sys_stream else None,
                on_mic_level=lambda v: self.transcript_queue.put(("VU", "mic", v)),
                on_sys_level=lambda v: self.transcript_queue.put(("VU", "sys", v)),
                use_sys_stream=use_sys_stream
            )

        if self.sys_capture_mode == "App específico":
            try:
                self._start_sys_app_capture()
            except Exception as e:
                self.log_transcript("Sistema", f"Falha na captura por app ({e}). Voltando para sistema inteiro.", True)
                self.sys_capture_mode = "Sistema inteiro"
                try:
                    if self.settings_window and self.settings_window.winfo_exists():
                        self.settings_window.combo_output_capture_mode.set(self.sys_capture_mode)
                        self.settings_window._set_output_capture_controls_state()
                except Exception:
                    pass
                self.save_config(show_message=False)
                self.recorder.restart_streams(
                    mic_idx=mic_info[0],
                    sys_idx=sys_info[0],
                    mic_rate=mic_info[2],
                    sys_rate=sys_info[2],
                    mic_channels=mic_info[3],
                    sys_channels=sys_info[3],
                    on_mic_data=mic_audio_callback,
                    on_sys_data=sys_audio_callback,
                    on_mic_level=lambda v: self.transcript_queue.put(("VU", "mic", v)),
                    on_sys_level=lambda v: self.transcript_queue.put(("VU", "sys", v)),
                    use_sys_stream=True
                )

    def switch_recording_devices(self, show_errors=True):
        if not self.is_recording:
            return
        if self.sys_capture_mode == "App específico":
            if not self.sys_app_target or self.sys_app_target == "Nenhum app encontrado":
                if show_errors:
                    messagebox.showerror("Erro", "Selecione um aplicativo para captura por app.")
                else:
                    self.log_transcript("Sistema", "Selecione um aplicativo para captura por app.", True)
                return
        mic_sel = self.selected_mic or self.combo_mic.get()
        sys_sel = self.selected_sys or self.combo_sys.get()
        mic_info = next((d for d in self.mic_devices if f"{d[1]} ({d[2]}Hz)" == mic_sel), None)
        sys_info = next((d for d in self.sys_devices if f"{d[1]} ({d[2]}Hz)" == sys_sel), None)

        if not mic_info or not sys_info:
            if show_errors:
                messagebox.showerror("Erro", "Dispositivos inválidos.")
            else:
                self.log_transcript("Sistema", "Dispositivos inválidos para troca.", True)
            return

        if not self.recorder.validate_device_index(mic_info[0]) or not self.recorder.validate_device_index(sys_info[0]):
            self.recorder.reinitialize()
            self.refresh_devices(preserve_selection=True)
            mic_sel = self.combo_mic.get()
            sys_sel = self.combo_sys.get()
            mic_info = next((d for d in self.mic_devices if f"{d[1]} ({d[2]}Hz)" == mic_sel), None)
            sys_info = next((d for d in self.sys_devices if f"{d[1]} ({d[2]}Hz)" == sys_sel), None)
            if not mic_info or not sys_info:
                if show_errors:
                    messagebox.showerror("Erro", "Dispositivos inválidos.")
                else:
                    self.log_transcript("Sistema", "Dispositivos inválidos após atualização.", True)
                return

        try:
            if self.streaming_client_mic:
                self.streaming_client_mic.disconnect(terminate=True)
            if self.streaming_client_sys:
                self.streaming_client_sys.disconnect(terminate=True)
        except Exception:
            pass

        try:
            stream_sys_rate = self.sys_capture_rate if self.sys_capture_mode == "App específico" else sys_info[2]
            self._connect_streaming_clients(self.api_key.strip(), mic_info[2], stream_sys_rate)
            self._start_audio_streams(mic_info, sys_info, restart=True)
        except Exception as e:
            if show_errors:
                messagebox.showerror("Erro Áudio", f"Falha ao trocar dispositivos: {e}")
            else:
                self.log_transcript("Sistema", f"Falha ao trocar dispositivos: {e}", True)
    def switch_language(self):
        if not self.is_recording:
            return
        try:
            if self.streaming_client_mic:
                self.streaming_client_mic.disconnect(terminate=True)
            if self.streaming_client_sys:
                self.streaming_client_sys.disconnect(terminate=True)
        except Exception:
            pass

        try:
            stream_sys_rate = self.sys_capture_rate if self.sys_capture_mode == "App específico" else self.recorder.sys_rate
            self._connect_streaming_clients(self.api_key.strip(), self.recorder.mic_rate, stream_sys_rate)
        except Exception as e:
            messagebox.showerror("Erro Áudio", f"Falha ao trocar idioma: {e}")


    def render_transcript_window(self):
        if not (self.transcript_window and self.transcript_window.winfo_exists()):
            return
        window = self.transcript_window
        window.reset_partial_lines()
        window.textbox.configure(state="normal")
        window.textbox.delete("1.0", "end")
        for entry_msg, entry_err, _ in self.transcript_history:
            window._insert_line("end-1c", entry_msg, entry_err)
        window.textbox.see("end")
        window.textbox.configure(state="disabled")

        # Append partials after finalized entries
        for source, (text, ts) in sorted(self.partial_transcripts.items(), key=lambda x: x[1][1]):
            self.transcript_window.set_partial_line(source, text, ts)

    def open_transcript_window(self):
        if self.transcript_window is None or not self.transcript_window.winfo_exists():
            self.transcript_window = TranscriptWindow(self)
            self.render_transcript_window()
        else:
            # Clear existing window and repopulate with current history
            self.render_transcript_window()
            self.transcript_window.lift()

    def open_settings_window(self):
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self.settings_window = SettingsWindow(self)
            self.settings_window.after(0, self.settings_window.bring_to_front)
        else:
            self.settings_window.bring_to_front()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.api_key = config.get("api_key", "")
                    self.user_name = config.get("user_name", "Você")
                    self.selected_mic = config.get("selected_mic", "")
                    self.selected_sys = config.get("selected_sys", "")
                    self.save_directory = config.get("save_directory", self.save_directory)
                    self.mic_enabled = bool(config.get("mic_enabled", True))
                    self.sys_enabled = bool(config.get("sys_enabled", True))
                    self.sys_capture_mode = "Sistema inteiro"
                    self.sys_app_target = config.get("sys_app_target", "")
                    self.realtime_transcript = True
            except: pass

    def save_config(self, show_message=True):
        config = {
            "api_key": self.api_key,
            "user_name": self.user_name,
            "realtime_transcript": self.realtime_transcript,
            "save_directory": self.save_directory,
        }
        # Save current device selections if combo boxes exist
        if hasattr(self, 'combo_mic') and hasattr(self, 'combo_sys'):
            config["selected_mic"] = self.combo_mic.get()
            config["selected_sys"] = self.combo_sys.get()
        config["mic_enabled"] = self.mic_enabled
        config["sys_enabled"] = self.sys_enabled
        config["sys_capture_mode"] = self.sys_capture_mode
        config["sys_app_target"] = self.sys_app_target
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f)
        if show_message:
            messagebox.showinfo("Salvo", "Configurações salvas.")


    def _finalize_recording_with_title(self, folder, meeting_title=None, user_name=None, participants=None):
        """Finalize recording by building a local title and renaming files."""
        try:
            if getattr(self, 'current_txt_path', None) and os.path.exists(self.current_txt_path):
                self.lbl_status.configure(text="Definindo título...", text_color="blue")
                title = self._build_recording_title(
                    meeting_title=meeting_title,
                    user_name=user_name,
                    participants=participants
                )

                # Add title as header comment to transcript file
                try:
                    with open(self.current_txt_path, "r", encoding="utf-8") as f:
                        existing_content = f.read()

                    with open(self.current_txt_path, "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\n")
                        f.write(existing_content)
                except Exception as header_error:
                    print(f"Error adding title header: {header_error}")

                # Rename transcript file and subfolder to use title as filename
                if os.path.exists(self.current_txt_path):
                    safe_title = title
                    if not safe_title:
                        safe_title = "meeting"
                    new_filename = f"{safe_title}.txt"
                    new_txt_path = os.path.join(folder, new_filename)

                    parent_folder = os.path.dirname(folder)
                    new_folder_name = safe_title
                    new_folder_path = os.path.join(parent_folder, new_folder_name)

                    try:
                        # Rename the transcript file
                        os.rename(self.current_txt_path, new_txt_path)
                        self.current_txt_path = new_txt_path

                        # Rename the subfolder (retry on Windows lock)
                        for _ in range(5):
                            try:
                                os.rename(folder, new_folder_path)
                                folder = new_folder_path
                                break
                            except PermissionError:
                                time.sleep(0.2)

                    except Exception as rename_error:
                        print(f"Error renaming transcript file or folder: {rename_error}")

                self.log_transcript("Sistema", f"Título definido: {title}", False)

            # Close transcript window after recording stops
            if self.transcript_window and self.transcript_window.winfo_exists():
                # Properly close the window to ensure cleanup (removes theme callbacks)
                self.transcript_window.on_close()
                self.transcript_window = None

            colors = get_colors()
            self.lbl_status.configure(text="● Salvo com Sucesso", text_color=colors["success"])
            os.startfile(folder)

        except Exception as e:
            print(f"Error in finalization: {e}")
            # Fallback: just open the folder
            try:
                os.startfile(folder)
            except:
                pass
        finally:
            # Clear current transcript path after finalization completes
            self.current_txt_path = None

    def _normalize_meeting_slug(self, text, keep_hyphen=False):
        value = (text or "").strip().lower()
        if not value:
            return ""
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        cleaned = []
        prev_sep = False
        for ch in value:
            if ch.isalnum():
                cleaned.append(ch)
                prev_sep = False
            elif keep_hyphen and ch == "-":
                cleaned.append("-")
                prev_sep = False
            elif ch in (" ", "-", "_", ",", ";", ":"):
                if not prev_sep:
                    cleaned.append("_")
                    prev_sep = True
        slug = "".join(cleaned).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        return slug

    def _build_recording_title(self, meeting_title=None, user_name=None, participants=None):
        recording_time = self.recorder.start_time or datetime.datetime.now()
        date_str = recording_time.strftime("%d_%m_%Y")
        time_str = recording_time.strftime("%H_%M_%S")
        title_slug = self._normalize_meeting_slug(meeting_title, keep_hyphen=True) or "Meeting"
        host_slug = self._normalize_meeting_slug(user_name) or "host"
        participant_slug = self._normalize_meeting_slug(participants, keep_hyphen=True) or "outros"
        return f"{date_str}_{time_str}_{title_slug}_{participant_slug}_{host_slug}"

    def open_folder(self):
        if not os.path.exists(self.save_directory): os.makedirs(self.save_directory)
        os.startfile(self.save_directory)

    def on_close(self):
        """Handle main window close"""
        if self.is_recording:
            should_close = messagebox.askyesno(
                "Transcrição em andamento",
                "Transcrição em andamento. Fechar sem salvar?",
                parent=self
            )
            if not should_close:
                try:
                    self.lift()
                    self.focus_force()
                except Exception:
                    pass
                return
            self._force_stop_recording()

        theme_manager.remove_theme_callback(self.on_theme_changed)
        self.quit()

    def _force_stop_recording(self):
        """Stop recording without saving"""
        try:
            if self.streaming_client_mic:
                self.streaming_client_mic.disconnect(terminate=True)
            if self.streaming_client_sys:
                self.streaming_client_sys.disconnect(terminate=True)
        except Exception:
            pass
        try:
            if self.recorder.mic_stream:
                self.recorder.mic_stream.stop_stream()
                self.recorder.mic_stream.close()
            if self.recorder.sys_stream:
                self.recorder.sys_stream.stop_stream()
                self.recorder.sys_stream.close()
        except Exception:
            pass

        self.stop_recording_cleanup()

if __name__ == "__main__":
    app = TranscriptionApp()
    app.mainloop()


