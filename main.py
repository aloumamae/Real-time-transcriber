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

from ui_theme import (
    theme_manager, apply_theme, add_theme_callback, pick, C, F, FONT, ICON,
    card, entry, combo, segmented, switch, primary_button, secondary_button, icon_button,
)

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

def place_window(window, width, height, min_size=None):
    """Center a window, clamped to the screen. Sizes are logical px.

    CustomTkinter multiplies width/height by the Windows display scale (125%, 150%...)
    but not x/y, while winfo_screen* reports physical px, so convert both ways.
    Without this, a 760px window becomes 1140px on a 1080p screen at 150%.
    """
    scale = window._get_window_scaling()
    screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    width = min(width, int(screen_w / scale) - 40)
    height = min(height, int(screen_h / scale) - 110)  # taskbar + title bar
    x = max(0, (screen_w - int(width * scale)) // 2)
    y = max(0, (screen_h - int(height * scale)) // 2 - int(24 * scale))
    window.geometry(f"{width}x{height}+{x}+{y}")
    if min_size:
        window.minsize(min(min_size[0], width), min(min_size[1], height))

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
        self.parent_app = parent
        self.configure(fg_color=C["bg"])
        place_window(self, 900, 640, min_size=(480, 360))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(250, lambda: apply_window_icon(self))

        # Font zoom state
        self.current_font_size = 13
        self.default_font_size = 13
        self.min_font_size = 10
        self.max_font_size = 24
        self.font_family = FONT

        # Track partial lines per speaker
        self.partial_lines = {}
        self.partial_mark_counter = 0

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(14, 10))
        ctk.CTkLabel(header, text="Transcrição", font=F["title"], text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(header, text="Ctrl + roda do mouse para zoom", font=F["small"], text_color=C["muted"]).pack(
            side="left", padx=(12, 0), pady=(4, 0)
        )
        icon_button(header, ICON["zoom_in"], self.zoom_in).pack(side="right")
        icon_button(header, ICON["zoom_out"], self.zoom_out).pack(side="right", padx=(0, 4))

        self.textbox = ctk.CTkTextbox(
            self,
            fg_color=C["surface"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text"],
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["muted"],
            font=(self.font_family, self.current_font_size),
            corner_radius=14,
            border_spacing=14,
            spacing3=8,
            wrap="word"
        )
        self.textbox.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.textbox.configure(state="disabled")

        self.on_theme_changed()
        self.bind_zoom_controls()
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
                self.textbox.insert(start_index, line_text, "partial")
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
        self.textbox.insert("end", line_text, "partial")
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
        stamp, rest = "", text
        if text.startswith("[") and "] " in text:
            stamp, rest = text.split("] ", 1)
            stamp += "] "
        if ": " not in rest:
            self.textbox.insert(index, text + "\n")
            return
        speaker, content = rest.split(": ", 1)
        name = speaker.strip()
        if name in (self.parent_app.user_name, "Você"):
            tag = "user"
        elif name in ("Sistema", "App", "Microfone"):
            tag = "system"
        else:
            tag = "other"
        # Same fixed index: each insert lands before the previous one.
        self.textbox.insert(index, f"{content}\n")
        self.textbox.insert(index, f"{speaker}: ", tag)
        if stamp:
            self.textbox.insert(index, stamp, "time")

    def on_theme_changed(self, theme_name=None):
        """Text tags are raw Tk, so they need hex colors for the current mode."""
        for tag, token in (("user", "accent"), ("other", "info"), ("system", "muted"),
                           ("time", "muted"), ("partial", "muted"), ("error", "danger")):
            self.textbox.tag_config(tag, foreground=pick(C[token]))

    def on_close(self):
        theme_manager.remove_theme_callback(self.on_theme_changed)
        self.parent_app.transcript_window = None
        self.destroy()

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Voilà | Configurações")
        self.parent_app = parent
        self.configure(fg_color=C["bg"])
        place_window(self, 560, 760, min_size=(420, 360))
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<FocusIn>", self._on_settings_focus_in)
        self.after(250, lambda: apply_window_icon(self))

        self.original_values = {}
        self.output_app_label_to_exe = {}
        self.output_app_exe_to_label = {}
        self.output_apps_poll_job = None
        self.output_apps_refresh_in_progress = False
        self.output_apps_last_refresh_ts = 0.0
        self.output_apps_poll_interval_ms = 3000

        # Footer is packed first so Save/Cancel stay visible however small the window gets.
        footer = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0)
        footer.pack(side="bottom", fill="x")
        ctk.CTkFrame(self, height=1, fg_color=C["border"], corner_radius=0).pack(side="bottom", fill="x")
        footer_row = ctk.CTkFrame(footer, fg_color="transparent")
        footer_row.pack(fill="x", padx=20, pady=12)
        self.btn_save = primary_button(footer_row, "Salvar", self.save_settings, width=110, state="disabled")
        self.btn_save.pack(side="right")
        secondary_button(footer_row, "Cancelar", self.on_close, width=110).pack(side="right", padx=(0, 8))
        self.lbl_dirty = ctk.CTkLabel(footer_row, text="", font=F["small"], text_color=C["muted"])
        self.lbl_dirty.pack(side="left")

        self.settings_scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["muted"]
        )
        self.settings_scroll.pack(fill="both", expand=True, padx=(8, 2))

        ctk.CTkLabel(self.settings_scroll, text="Configurações", font=F["title"], text_color=C["text"]).pack(
            anchor="w", padx=12, pady=(14, 0)
        )

        # --- Próxima reunião (temporary, reset after each recording) ---
        body = self._section("Próxima reunião", "reseta após cada gravação")

        box = self._field(body, "Título")
        self.entry_meeting_title = entry(box, placeholder_text="Opcional — ex.: Planejamento semanal")
        self.entry_meeting_title.pack(fill="x", pady=(6, 0))
        if self.parent_app.meeting_title:
            self.entry_meeting_title.insert(0, self.parent_app.meeting_title)
        self.entry_meeting_title.bind("<KeyRelease>", self.on_value_changed)

        box = self._field(body, "Participantes", "Separados por espaço")
        self.entry_participants = entry(box)
        self.entry_participants.pack(fill="x", pady=(6, 0))
        self.entry_participants.insert(0, self.parent_app.participants)
        self.entry_participants.bind("<KeyRelease>", self.on_participants_changed)

        box = self._field(body, "Idioma")
        self.combo_language = segmented(box, ["Multilingual", "Inglês"], self.on_language_changed)
        self.combo_language.pack(fill="x", pady=(6, 0))
        self.combo_language.set(self.parent_app.language_choice)

        # --- Captura ---
        body = self._section("Captura")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=6)
        self.switch_realtime = switch(row, self.on_realtime_changed)
        self.switch_realtime.pack(side="right")
        ctk.CTkLabel(row, text="Transcrição em tempo real", font=F["label"], text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(row, text="Mostra as falas enquanto ainda estão sendo transcritas", font=F["small"],
                     text_color=C["muted"], anchor="w").pack(fill="x")
        if self.parent_app.realtime_transcript:
            self.switch_realtime.select()

        box = self._field(body, "Áudio do sistema", "Grave o computador inteiro ou só um aplicativo")
        self.combo_output_capture_mode = segmented(
            box, ["Sistema inteiro", "App específico"], self.on_output_capture_mode_changed
        )
        self.combo_output_capture_mode.pack(fill="x", pady=(6, 0))
        self.combo_output_capture_mode.set(self.parent_app.sys_capture_mode or "Sistema inteiro")

        self.app_row = ctk.CTkFrame(box, fg_color="transparent")
        self.combo_output_app = combo(self.app_row, values=["Selecione um app"], command=self.on_output_app_changed)
        self.combo_output_app.pack(fill="x")
        self._bind_combo_toggle(self.combo_output_app)
        self.after(0, lambda: self._update_combo_menu_width(self.combo_output_app))
        self.combo_output_app.bind("<Configure>", lambda e: self._update_combo_menu_width(self.combo_output_app))

        self.lbl_output_capture_status = ctk.CTkLabel(box, text="", font=F["small"], text_color=C["muted"], anchor="w", height=0)
        self.lbl_output_capture_status.pack(fill="x")

        # --- Geral (persistent) ---
        body = self._section("Geral")

        box = self._field(body, "Seu nome", "Como você aparece na transcrição")
        self.entry_name = entry(box)
        self.entry_name.pack(fill="x", pady=(6, 0))
        self.entry_name.insert(0, self.parent_app.user_name)
        self.entry_name.bind("<KeyRelease>", self.on_value_changed)

        box = self._field(body, "Pasta das transcrições")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self.btn_browse_dir = secondary_button(row, "Procurar", self.browse_save_directory, width=96, height=36)
        self.btn_browse_dir.pack(side="right", padx=(8, 0))
        self.entry_save_dir = entry(row)
        self.entry_save_dir.pack(fill="x")
        self.entry_save_dir.insert(0, self.parent_app.save_directory)
        self.entry_save_dir.bind("<KeyRelease>", self.on_save_dir_changed)

        box = self._field(body, "Chave da API AssemblyAI", "Cada pessoa usa a própria chave (assemblyai.com)")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        icon_button(row, ICON["eye"], self._toggle_api_visibility).pack(side="right", padx=(8, 0))
        self.entry_api = entry(row, show="•")
        self.entry_api.pack(fill="x")
        self.entry_api.insert(0, self.parent_app.api_key)
        self.entry_api.bind("<KeyRelease>", self.on_value_changed)

        ctk.CTkFrame(self.settings_scroll, height=16, fg_color="transparent").pack()

        self._set_output_capture_controls_state()
        if self.combo_output_capture_mode.get().strip() == "App específico":
            self.refresh_output_apps_async()
            self._start_output_apps_auto_refresh()

        self.store_original_values()
        self.after(0, self.bring_to_front)

    def _section(self, title, note=None):
        head = ctk.CTkFrame(self.settings_scroll, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(18, 6))
        ctk.CTkLabel(head, text=title, font=F["h"], text_color=C["text"]).pack(side="left")
        if note:
            ctk.CTkLabel(head, text=note, font=F["small"], text_color=C["muted"]).pack(side="right")
        frame = card(self.settings_scroll)
        frame.pack(fill="x", padx=12)
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=10)
        return body

    def _field(self, body, label, hint=None):
        box = ctk.CTkFrame(body, fg_color="transparent")
        box.pack(fill="x", pady=6)
        ctk.CTkLabel(box, text=label, font=F["label"], text_color=C["text"], anchor="w").pack(fill="x")
        if hint:
            ctk.CTkLabel(box, text=hint, font=F["small"], text_color=C["muted"], anchor="w").pack(fill="x")
        return box

    def _toggle_api_visibility(self):
        self.entry_api.configure(show="" if self.entry_api.cget("show") else "•")

    def bring_to_front(self):
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(120, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def _current_values(self):
        return {
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

    def store_original_values(self):
        """Store the original values when window opens"""
        self.original_values = self._current_values()
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
            self.app_row.pack(fill="x", pady=(8, 0), before=self.lbl_output_capture_status)
        else:
            self.app_row.pack_forget()
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
        """Enable Save only when something differs from what the window opened with."""
        dirty = self._current_values() != self.original_values
        self.btn_save.configure(state="normal" if dirty else "disabled", fg_color=C["accent"] if dirty else C["field"])
        self.lbl_dirty.configure(text="Alterações não salvas" if dirty else "")

    def save_settings(self):
        current_values = self._current_values()
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

        self.original_values = current_values
        self.on_close()

    def on_close(self):
        if self.check_dirty_state_and_confirm_close():
            self._stop_output_apps_auto_refresh()
            self.parent_app.settings_window = None
            self.destroy()

    def check_dirty_state_and_confirm_close(self):
        if self._current_values() != self.original_values:
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
        self._fit_to_content()
        self.after(50, self.process_queue)

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
        pad = 20
        self.configure(fg_color=C["bg"])

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=pad, pady=(16, 14))
        ctk.CTkLabel(header, text=ICON["mic"], font=("Segoe MDL2 Assets", 22), text_color=C["accent"]).pack(side="left")
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(brand, text="Voilà", font=F["title"], text_color=C["text"], height=24).pack(anchor="w")
        ctk.CTkLabel(brand, text="Never lose the thread", font=F["small"], text_color=C["muted"], height=16).pack(anchor="w")
        self.btn_settings = icon_button(header, ICON["settings"], self.open_settings_window)
        self.btn_settings.pack(side="right")
        self.btn_theme = icon_button(header, self._theme_glyph(), self.toggle_theme)
        self.btn_theme.pack(side="right", padx=(0, 4))

        # Status bar is packed before the body so it stays pinned to the bottom edge.
        status_bar = ctk.CTkFrame(self, fg_color="transparent")
        status_bar.pack(side="bottom", fill="x", padx=pad, pady=(0, 12))
        self.lbl_status = ctk.CTkLabel(status_bar, text="● Pronto", font=F["small"], text_color=C["muted"])
        self.lbl_status.pack(side="left")
        self.lbl_timer = ctk.CTkLabel(status_bar, text="", font=("Segoe UI Semibold", 12), text_color=C["text"])
        self.lbl_timer.pack(side="right")

        self.create_device_section("Microfone", "mic")
        self.create_device_section("Áudio do sistema", "sys")
        if self.mic_enabled:
            self.switch_mic_enabled.select()
        if self.sys_enabled:
            self.switch_sys_enabled.select()

        self.btn_record = ctk.CTkButton(
            self, font=F["big"], height=52, corner_radius=12, text_color="#FFFFFF", command=self.toggle_recording
        )
        self.btn_record.pack(fill="x", padx=pad, pady=(6, 10))
        self._set_record_button(False)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=pad, pady=(0, 14))
        row.grid_columnconfigure((0, 1), weight=1, uniform="actions")
        self.btn_transcript = secondary_button(row, "Ver transcrição", self.open_transcript_window)
        self.btn_transcript.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_folder = secondary_button(row, "Abrir pasta", self.open_folder)
        self.btn_folder.grid(row=0, column=1, sticky="ew", padx=(5, 0))

    def _fit_to_content(self):
        """Size the window to its content (in logical px) and center it on screen."""
        self.update_idletasks()
        height = int(self.winfo_reqheight() / self._get_window_scaling())
        place_window(self, 440, height, min_size=(380, height))

    def _set_record_button(self, recording):
        if recording:
            self.btn_record.configure(text="■   Parar gravação", fg_color=C["danger"], hover_color=C["danger_hover"])
        else:
            self.btn_record.configure(text="●   Iniciar gravação", fg_color=C["accent"], hover_color=C["accent_hover"])

    def _tick_timer(self):
        start = self.recorder.start_time
        if not self.is_recording or not start:
            self.lbl_timer.configure(text="")
            return
        secs = int((datetime.datetime.now() - start).total_seconds())
        self.lbl_timer.configure(text=f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}")
        self.after(1000, self._tick_timer)

    def create_device_section(self, label, type_key):
        frame = card(self)
        frame.pack(fill="x", padx=20, pady=(0, 10))

        head = ctk.CTkFrame(frame, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 8))
        glyph = ICON["mic"] if type_key == "mic" else ICON["speaker"]
        ctk.CTkLabel(head, text=glyph, font=F["icon"], text_color=C["muted"], width=20).pack(side="left")
        ctk.CTkLabel(head, text=label, font=F["h"], text_color=C["text"]).pack(side="left", padx=(8, 0))
        source_switch = switch(head, lambda t=type_key: self.on_source_enabled_changed(t))
        source_switch.pack(side="right")

        device_combo = combo(frame, command=lambda value, t=type_key: self.on_device_selected(t, value))
        device_combo.pack(fill="x", padx=16)
        self._bind_combo_refresh(device_combo)

        progress = ctk.CTkProgressBar(
            frame, height=6, corner_radius=3, fg_color=C["field"], progress_color=C["success"]
        )
        progress.set(0)
        progress.pack(fill="x", padx=16, pady=(12, 16))

        if type_key == "mic":
            self.combo_mic = device_combo
            self.progress_mic = progress
            self.switch_mic_enabled = source_switch
        else:
            self.combo_sys = device_combo
            self.progress_sys = progress
            self.switch_sys_enabled = source_switch

    def _theme_glyph(self):
        return ICON["sun"] if theme_manager.current_theme == "dark" else ICON["moon"]

    def toggle_theme(self):
        apply_theme("light" if theme_manager.current_theme == "dark" else "dark")
        self.btn_theme.configure(text=self._theme_glyph())

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

        self._set_record_button(True)
        self.open_transcript_window()
        self.log_transcript("App", "Iniciando conexão...", False)

        try:
            stream_sys_rate = self.sys_capture_rate if self.sys_capture_mode == "App específico" else sys_info[2]
            self._connect_streaming_clients(key, mic_info[2], stream_sys_rate)

        except Exception as e:
            self.stop_recording_cleanup()
            self.log_transcript("CRITICO", str(e), True)
            return

        self.lbl_status.configure(text="● Gravando", text_color=C["success"])
        
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
        self._tick_timer()

    def stop_recording(self):
        self.lbl_status.configure(text="● Salvando...", text_color=C["warning"])
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
                self.lbl_status.configure(text="● Erro ao salvar", text_color=C["danger"])
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

        self._set_record_button(False)
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
                self.lbl_status.configure(text="● Definindo título...", text_color=C["info"])
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

            self.lbl_status.configure(text="● Salvo com Sucesso", text_color=C["success"])
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


