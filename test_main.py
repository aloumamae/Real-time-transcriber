import datetime
import queue
import re
import threading
import unittest
from types import SimpleNamespace

import io
import os
import tempfile
import zipfile

from main import TranscriptWindow, TranscriptionApp, install_update, place_window, version_tuple, vu_level


class FakeTextbox:
    """Small in-memory model of the Tk Text operations used by TranscriptWindow."""

    def __init__(self):
        self.text = ""
        self.marks = {}
        self.gravities = {}
        self.state = "disabled"

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)

    view = (0.0, 1.0)  # (top, bottom) fractions; bottom 1.0 = scrolled to the end
    seen = 0

    def see(self, _index):
        self.seen += 1

    def yview(self):
        return self.view

    def yview_moveto(self, fraction):
        self.view = (fraction, self.view[1])

    def tag_config(self, *_args, **_kwargs):
        pass

    def _offset(self, index):
        if isinstance(index, int):
            return index
        index = str(index).strip()
        if index in self.marks:
            return self.marks[index]
        if index in ("end", "end-1c"):
            return len(self.text)
        if index == "1.0":
            return 0
        match = re.fullmatch(r"(.+?)\s*\+\s*(\d+)c", index)
        if match:
            return self._offset(match.group(1)) + int(match.group(2))
        match = re.fullmatch(r"(\d+)\.0", index)
        if match:  # Tk "line.0": start of that line, clamped to end like Tk
            lines = self.text.split("\n")
            line = int(match.group(1))
            return len(self.text) if line > len(lines) else sum(len(l) + 1 for l in lines[: line - 1])
        return int(index)

    def index(self, index):
        return str(self._offset(index))

    def insert(self, index, value, tags=None):
        self.tagged = getattr(self, "tagged", {})
        if tags:
            self.tagged[value] = tags
        position = self._offset(index)
        for mark, mark_position in list(self.marks.items()):
            if mark_position > position or (
                mark_position == position and self.gravities.get(mark, "right") == "right"
            ):
                self.marks[mark] += len(value)
        self.text = self.text[:position] + value + self.text[position:]

    def delete(self, index1, index2=None):
        start = self._offset(index1)
        end = self._offset(index2) if index2 is not None else start + 1
        removed = max(0, end - start)
        for mark, position in list(self.marks.items()):
            if position >= end:
                self.marks[mark] = position - removed
            elif position >= start:
                self.marks[mark] = start
        self.text = self.text[:start] + self.text[end:]

    def mark_set(self, mark, index):
        self.marks[mark] = self._offset(index)
        self.gravities.setdefault(mark, "right")

    def mark_gravity(self, mark, gravity=None):
        if gravity is not None:
            self.gravities[mark] = gravity
        return self.gravities.get(mark, "right")

    def mark_unset(self, mark):
        self.marks.pop(mark, None)
        self.gravities.pop(mark, None)


def make_transcript_window():
    window = object.__new__(TranscriptWindow)
    window.parent_app = SimpleNamespace(user_name="Clarice")
    window.textbox = FakeTextbox()
    window.partial_lines = {}
    window.partial_mark_counter = 0
    return window


def make_timeline_app():
    app = object.__new__(TranscriptionApp)
    app.user_name = "Clarice"
    app.participants = "Outros"
    app.audio_timeline_lock = threading.Lock()
    app.audio_stream_position_ms = {}
    app.audio_wall_segments = {}
    app.turn_start_times = {}
    app.audio_timeline_ready = False
    app.audio_timeline_generation = 0
    app._reset_audio_timeline(ready=True)
    return app


class TranscriptPartialMarkTests(unittest.TestCase):
    def test_updating_one_partial_does_not_delete_other_final(self):
        window = make_transcript_window()
        stamp = datetime.datetime(2026, 1, 1, 12, 0, 0)

        window.set_partial_line("Outros", "parcial do sistema", stamp)
        window.set_partial_line("Clarice", "parcial antiga", stamp)
        window.clear_partial_line("Outros")
        window.append_text("[12:00:00] Outros: frase final")
        window.set_partial_line("Clarice", "parcial atualizada", stamp)

        contents = window.textbox.text
        self.assertIn("[12:00:00] Outros: frase final", contents)
        self.assertNotIn("parcial antiga", contents)
        self.assertEqual(contents.count("parcial atualizada"), 1)

    def test_clearing_one_partial_preserves_the_other(self):
        window = make_transcript_window()
        stamp = datetime.datetime(2026, 1, 1, 12, 0, 0)

        window.set_partial_line("Clarice", "fala da Clarice", stamp)
        window.set_partial_line("Outros", "fala dos outros", stamp)
        window.clear_partial_line("Clarice")

        self.assertNotIn("fala da Clarice", window.textbox.text)
        self.assertIn("fala dos outros", window.textbox.text)
        self.assertIn("Outros", window.partial_lines)

    def test_autoscroll_only_while_reader_is_at_the_bottom(self):
        window = make_transcript_window()
        window.append_text("[10:00:00] Clarice: oi")
        window.set_partial_line("Mic", "falando")
        self.assertEqual(window.textbox.seen, 2)

        window.textbox.view = (0.2, 0.5)  # user scrolled up to read history
        window.append_text("[10:00:05] Clarice: nova linha")
        window.set_partial_line("Mic", "falando mais")
        self.assertEqual(window.textbox.seen, 2)

    def test_end_mark_uses_left_gravity_and_reset_unsets_marks(self):
        window = make_transcript_window()
        window.set_partial_line("Outros", "fala")
        start_mark, end_mark = window.partial_lines["Outros"]

        self.assertRegex(start_mark, r"^partial_start_\d+$")
        self.assertRegex(end_mark, r"^partial_end_\d+$")
        self.assertEqual(window.textbox.gravities[end_mark], "left")

        window.reset_partial_lines()
        self.assertEqual(window.partial_lines, {})
        self.assertNotIn(start_mark, window.textbox.marks)
        self.assertNotIn(end_mark, window.textbox.marks)


class PlaceWindowTests(unittest.TestCase):
    def test_full_hd_at_150_percent_fits_on_screen(self):
        calls = {}
        win = SimpleNamespace(
            _get_window_scaling=lambda: 1.5,
            winfo_screenwidth=lambda: 1920,
            winfo_screenheight=lambda: 1080,
            geometry=lambda g: calls.__setitem__("geometry", g),
            minsize=lambda w, h: calls.__setitem__("minsize", (w, h)),
        )
        place_window(win, 560, 760, min_size=(420, 360))

        size, x, y = re.fullmatch(r"(\d+x\d+)\+(\d+)\+(\d+)", calls["geometry"]).groups()
        width, height = map(int, size.split("x"))
        self.assertLessEqual(int(height * 1.5) + int(y), 1080 - 48)  # bottom edge above the taskbar
        self.assertLessEqual(int(width * 1.5) + int(x), 1920)
        self.assertGreaterEqual(int(y), 0)
        self.assertLessEqual(calls["minsize"][1], height)


class SpeakerHighlightTests(unittest.TestCase):
    def test_timestamped_lines_tag_speaker_and_keep_text(self):
        window = make_transcript_window()
        window.append_text("[12:00:00] Clarice: oi")
        window.append_text("[12:00:01] João: tudo bem")

        self.assertEqual(window.textbox.text, "[12:00:00] Clarice: oi\n[12:00:01] João: tudo bem\n")
        self.assertEqual(window.textbox.tagged["Clarice: "], "user")
        self.assertEqual(window.textbox.tagged["João: "], "other")
        self.assertEqual(window.textbox.tagged["[12:00:00] "], "time")


class AudioTimelineTests(unittest.TestCase):
    def test_first_system_buffer_after_silence_uses_real_wall_time(self):
        app = make_timeline_app()
        # A 100 ms buffer that starts at 12:00:20 is delivered at 12:00:20.100.
        delivered_at = datetime.datetime(2026, 1, 1, 12, 0, 20, 100000)
        app._record_audio_buffer("sys", 3200, 16000, delivered_at)

        self.assertEqual(
            app._wall_time_for_audio_offset("sys", 0),
            datetime.datetime(2026, 1, 1, 12, 0, 20),
        )
        self.assertEqual(
            app._wall_time_for_audio_offset("sys", 50),
            datetime.datetime(2026, 1, 1, 12, 0, 20, 50000),
        )

    def test_separated_blocks_preserve_wall_clock_gap(self):
        app = make_timeline_app()
        app._record_audio_buffer(
            "sys", 3200, 16000, datetime.datetime(2026, 1, 1, 12, 0, 10, 100000)
        )
        app._record_audio_buffer(
            "sys", 3200, 16000, datetime.datetime(2026, 1, 1, 12, 0, 30, 100000)
        )

        self.assertEqual(len(app.audio_wall_segments["sys"]), 2)
        # Offset 100 is both the old segment's end and the new one's start;
        # reverse lookup must choose the newer segment after the real gap.
        self.assertEqual(
            app._wall_time_for_audio_offset("sys", 100),
            datetime.datetime(2026, 1, 1, 12, 0, 30),
        )
        self.assertEqual(
            app._wall_time_for_audio_offset("sys", 150),
            datetime.datetime(2026, 1, 1, 12, 0, 30, 50000),
        )

    def test_late_buffer_from_old_connection_does_not_advance_new_timeline(self):
        app = make_timeline_app()
        old_generation = app.audio_timeline_generation
        app._reset_audio_timeline(ready=True)

        app._record_audio_buffer(
            "sys",
            3200,
            16000,
            datetime.datetime(2026, 1, 1, 12, 0, 20, 100000),
            expected_generation=old_generation,
        )

        self.assertEqual(app.audio_stream_position_ms["sys"], 0.0)
        self.assertEqual(app.audio_wall_segments["sys"], [])


class OrderedHistoryTests(unittest.TestCase):
    def test_out_of_order_finals_rebuild_the_window_in_timestamp_order(self):
        app = object.__new__(TranscriptionApp)
        app.transcript_queue = queue.Queue()
        app.transcript_history = []
        app.partial_transcripts = {
            "Clarice": ("parcial preservada", datetime.datetime(2026, 1, 1, 12, 0, 40))
        }
        app.partial_block_until = {}
        app.last_final_text = {}
        app.last_partial_update = {}
        app.render_interval_ms = 200
        app.after = lambda *_args, **_kwargs: None
        app.progress_mic = SimpleNamespace(set=lambda _value: None)
        app.progress_sys = SimpleNamespace(set=lambda _value: None)

        window = make_transcript_window()
        window.winfo_exists = lambda: True
        app.transcript_window = window
        # A third speaker's partial: a speaker's own final replaces their partial.
        window.set_partial_line("Kevin", "parcial preservada", datetime.datetime(2026, 1, 1, 12, 0, 40))

        newer = datetime.datetime(2026, 1, 1, 12, 0, 30)
        older = datetime.datetime(2026, 1, 1, 12, 0, 10)
        app.transcript_queue.put(("TXT", "[12:00:30] Outros: segunda", False, newer, "Outros"))
        app.transcript_queue.put(("TXT", "[12:00:10] Clarice: primeira", False, older, "Clarice"))

        app.process_queue()

        contents = window.textbox.text
        self.assertLess(contents.index("primeira"), contents.index("segunda"))
        self.assertLess(contents.index("segunda"), contents.index("parcial preservada"))

    def test_finals_are_inserted_not_rerendered_and_partial_is_replaced(self):
        app = object.__new__(TranscriptionApp)
        app.transcript_queue = queue.Queue()
        app.transcript_history = []
        app.partial_transcripts = {}
        app.partial_block_until = {}
        app.last_final_text = {}
        app.last_partial_update = {}
        app.render_interval_ms = 0
        app.after = lambda *_args, **_kwargs: None
        app.progress_mic = SimpleNamespace(set=lambda _value: None)
        app.progress_sys = SimpleNamespace(set=lambda _value: None)
        app.render_transcript_window = lambda: self.fail("full re-render per line freezes long meetings")
        app.user_name = "Clarice"
        app.participants = "Outros"

        window = make_transcript_window()
        window.winfo_exists = lambda: True
        app.transcript_window = window

        t = lambda s: datetime.datetime(2026, 1, 1, 12, 0, s)
        app.transcript_queue.put(("PARTIAL", "sys", "rascunho", t(50)))
        for s in (10, 30, 20, 40):  # 20 arrives late, must land between 10 and 30
            app.transcript_queue.put(("TXT", f"[12:00:{s}] Outros: linha {s}", False, t(s), "sys"))
        app.process_queue()

        self.assertEqual(
            window.textbox.text,
            "[12:00:10] Outros: linha 10\n[12:00:20] Outros: linha 20\n"
            "[12:00:30] Outros: linha 30\n[12:00:40] Outros: linha 40\n",
        )
        self.assertEqual([e[2] for e in app.transcript_history], [t(10), t(20), t(30), t(40)])


class RenameMidMeetingTests(unittest.TestCase):
    def test_renaming_participants_mid_partial_leaves_no_orphan_lines(self):
        app = object.__new__(TranscriptionApp)
        app.transcript_queue = queue.Queue()
        app.transcript_history = []
        app.partial_transcripts = {}
        app.partial_block_until = {}
        app.last_final_text = {}
        app.last_partial_update = {}
        app.render_interval_ms = 0
        app.after = lambda *_args, **_kwargs: None
        app.user_name = "Clarice"
        window = make_transcript_window()
        window.winfo_exists = lambda: True
        app.transcript_window = window

        t = datetime.datetime(2026, 1, 1, 12, 0, 0)
        for name, text in (("K", "Hopefully"), ("Ke", "Hopefully you're"), ("Kevi", "Hopefully you're doing")):
            app.participants = name  # typed one key at a time in Settings
            app.transcript_queue.put(("PARTIAL", "sys", text, t))
            app.process_queue()
        self.assertEqual(window.textbox.text, "[12:00:00] Kevi: Hopefully you're doing\n")

        app.participants = "Kevin"
        app.transcript_queue.put(("TXT", "[12:00:00] Kevin: Hopefully you're doing well.", False, t, "sys"))
        app.process_queue()
        self.assertEqual(window.textbox.text, "[12:00:00] Kevin: Hopefully you're doing well.\n")


class VuLevelTests(unittest.TestCase):
    def test_meter_tracks_loudness_instead_of_pinning_full(self):
        import numpy as np
        tone = lambda amp: (amp * np.sin(np.arange(4096) / 5)).astype(np.int16)
        self.assertEqual(vu_level(np.zeros(4096, dtype=np.int16)), 0.0)
        self.assertLess(vu_level(tone(30)), 0.2)      # room noise: near the left
        speech = vu_level(tone(3000))                  # normal speech: mid bar
        self.assertTrue(0.4 < speech < 0.9, speech)
        self.assertEqual(vu_level(tone(32000)), 1.0)   # clipping: full
        self.assertEqual(vu_level(np.array([], dtype=np.int16)), 0.0)


class UpdaterTests(unittest.TestCase):
    def test_startup_check_only_interrupts_when_there_is_an_update(self):
        import main
        app = object.__new__(TranscriptionApp)
        app.is_recording = False
        asked = []
        original = main.messagebox.askyesno
        main.messagebox.askyesno = lambda *a, **k: asked.append(a) or False
        try:
            silent = lambda text, busy=False: None
            app._on_latest_release(ConnectionError("offline"), "", silent)
            app._on_latest_release({"tag_name": f"v{main.APP_VERSION}"}, "", silent)
            self.assertEqual(asked, [])

            app.is_recording = True  # never interrupt a meeting
            app._on_latest_release({"tag_name": "v99.0.0"}, "", silent)
            self.assertEqual(asked, [])

            app.is_recording = False
            app._on_latest_release({"tag_name": "v99.0.0"}, "", silent)
            self.assertEqual(len(asked), 1)
        finally:
            main.messagebox.askyesno = original

    def test_versions_compare_as_numbers(self):
        self.assertGreater(version_tuple("v1.10.0"), version_tuple("1.9.9"))
        self.assertEqual(version_tuple("v1.1.4"), version_tuple("1.1.4"))

    def test_update_overwrites_app_files_but_keeps_personal_data(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("owner-repo-abc123/", "")
            archive.writestr("owner-repo-abc123/main.py", "new")
            archive.writestr("owner-repo-abc123/Icons/a.ico", "icon")
            archive.writestr("owner-repo-abc123/../evil.txt", "x")
        with tempfile.TemporaryDirectory() as parent:
            app = os.path.join(parent, "app")
            os.makedirs(app)
            for name, text in (("main.py", "old"), ("config.json", "secret")):
                with open(os.path.join(app, name), "w") as f:
                    f.write(text)

            self.assertEqual(install_update(buffer.getvalue(), app), 2)
            read = lambda *p: open(os.path.join(*p)).read()
            self.assertEqual(read(app, "main.py"), "new")
            self.assertEqual(read(app, "Icons", "a.ico"), "icon")
            self.assertEqual(read(app, "config.json"), "secret")
            self.assertFalse(os.path.exists(os.path.join(parent, "evil.txt")))


if __name__ == "__main__":
    unittest.main()
