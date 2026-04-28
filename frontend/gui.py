import math
import queue
import random
import subprocess
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
import psutil
from config import ducking_default
from backend.sounds import MUTE_SOUND, UNMUTE_SOUND, play_sound_async

try:
    import ctypes
    import ctypes.wintypes
except ImportError:
    ctypes = None



SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "Version 0.1"
BASE_DIR = Path(__file__).resolve().parents[1]
APP_ICON = BASE_DIR / "Assets" / "sprites" / "icon.png"

C_BG = "#000000"
C_PRI = "#00d4ff"
C_MID = "#007a99"
C_DIM = "#003344"
C_DIMMER = "#001520"
C_ACC = "#ff4fa3"
C_ACC2 = "#8b7cff"
C_TEXT = "#8ffcff"
C_PANEL = "#010c10"
C_GREEN = "#00ff88"
C_RED = "#ff3333"
C_MUTED = "#ff3366"

_MAIN_THREAD_ID = threading.get_ident()
_ui_queue = queue.Queue()

state = "idle"
state_change_time = time.time()
is_muted = False
audio_ducking_enabled = bool(ducking_default)


class WindowsCpuMeter:
    def __init__(self):
        self._last_idle = None
        self._last_kernel = None
        self._last_user = None

    @staticmethod
    def _filetime_to_int(filetime):
        return (filetime.dwHighDateTime << 32) | filetime.dwLowDateTime

    def percent(self):
        if ctypes is None or not hasattr(ctypes, "windll"):
            return None

        idle = ctypes.wintypes.FILETIME()
        kernel = ctypes.wintypes.FILETIME()
        user = ctypes.wintypes.FILETIME()

        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None

        idle_time = self._filetime_to_int(idle)
        kernel_time = self._filetime_to_int(kernel)
        user_time = self._filetime_to_int(user)

        if self._last_idle is None:
            self._last_idle = idle_time
            self._last_kernel = kernel_time
            self._last_user = user_time
            return 0.0

        idle_delta = idle_time - self._last_idle
        kernel_delta = kernel_time - self._last_kernel
        user_delta = user_time - self._last_user
        total_delta = kernel_delta + user_delta

        self._last_idle = idle_time
        self._last_kernel = kernel_time
        self._last_user = user_time

        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))


class MemoryStatus(ctypes.Structure if ctypes is not None else object):
    if ctypes is not None:
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]


_cpu_meter = WindowsCpuMeter()


def _run_or_queue(callback, *args):
    if threading.get_ident() == _MAIN_THREAD_ID:
        callback(*args)
    else:
        _ui_queue.put((callback, args))


def _drain_ui_queue():
    while True:
        try:
            callback, args = _ui_queue.get_nowait()
        except queue.Empty:
            break
        callback(*args)

    root.after(30, _drain_ui_queue)


class JarvisGui:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.resizable(False, False)
        self._set_app_icon()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.W = min(sw, 984)
        self.H = min(sh, 816)
        self.root.geometry(
            f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2}"
        )
        self.root.configure(bg=C_BG)

        self.FACE_SZ = min(int(self.H * 0.54), 400)
        self.FCX = self.W // 2
        self.FCY = int(self.H * 0.13) + self.FACE_SZ // 2

        self.state = "idle"
        self.state_change_time = time.time()
        self.speaking = False
        self.muted = False
        self.audio_ducking_enabled = bool(ducking_default)
        self.scale = 1.0
        self.target_scale = 1.0
        self.halo_a = 60.0
        self.target_halo = 60.0
        self.last_t = time.time()
        self.tick = 0
        self.scan_angle = 0.0
        self.scan2_angle = 180.0
        self.rings_spin = [0.0, 120.0, 240.0]
        self.pulse_r = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text = "ONLINE"
        self.status_blink = True
        self.typing_queue = deque()
        self.is_typing = False
        self.on_text_command = None
        self.monitor_open = False
        self._ducking_refresh_job = None
        self._ducking_tooltip = None
        self.metrics = {"CPU": None, "RAM": None, "GPU": None}
        self.metric_history = {
            "CPU": deque([0.0] * 42, maxlen=42),
            "RAM": deque([0.0] * 42, maxlen=42),
            "GPU": deque([0.0] * 42, maxlen=42),
        }
        self.gpu_available = False

        self.canvas = tk.Canvas(
            self.root,
            width=self.W,
            height=self.H,
            bg=C_BG,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0)

        self._build_log()
        self._build_input_bar()
        self._build_mute_button()
        self._build_audio_ducking_button()
        self._build_monitor_button()
        self._apply_audio_ducking_enabled()

        self._sample_metrics()
        self._animate()

    def _set_app_icon(self):
        if not APP_ICON.exists():
            print(f"App icon not found: {APP_ICON}")
            return

        try:
            self._icon_image = tk.PhotoImage(file=str(APP_ICON))
            self.root.iconphoto(True, self._icon_image)
        except Exception as exc:
            print(f"App icon failed to load: {exc}")

    @staticmethod
    def _ac(r, g, b, a):
        f = max(0.0, min(1.0, a / 255.0))
        return f"#{int(r * f):02x}{int(g * f):02x}{int(b * f):02x}"

    def _build_log(self):
        self.log_w = int(self.W * 0.72)
        self.log_h = 110
        self.log_y = self.H - self.log_h - 80

        self.chat_frame = tk.Frame(
            self.root,
            bg=C_PANEL,
            highlightbackground=C_MID,
            highlightthickness=1,
        )
        self.chat_frame.place(
            x=(self.W - self.log_w) // 2,
            y=self.log_y,
            width=self.log_w,
            height=self.log_h,
        )

        self.chat_box = tk.Text(
            self.chat_frame,
            fg=C_TEXT,
            bg=C_PANEL,
            insertbackground=C_TEXT,
            borderwidth=0,
            wrap="word",
            font=("Consolas", 10),
            padx=10,
            pady=6,
        )
        self.chat_box.pack(fill="both", expand=True)
        self.chat_box.configure(state="disabled")
        self.chat_box.tag_config("Jarvis", foreground=C_PRI, font=("Consolas", 10))
        self.chat_box.tag_config("User", foreground="#e8e8e8", font=("Consolas", 10))
        self.chat_box.tag_config("System", foreground=C_ACC2, font=("Consolas", 10))
        self.chat_box.tag_config("Error", foreground=C_RED, font=("Consolas", 10))
        self.chat_box.tag_config("jarvis_text", foreground=C_PRI, font=("Consolas", 10))
        self.chat_box.tag_config("user_text", foreground="#e8e8e8", font=("Consolas", 10))
        self.chat_box.tag_config("system_text", foreground=C_ACC2, font=("Consolas", 10))

    def _build_input_bar(self):
        x0 = (self.W - self.log_w) // 2
        y = self.log_y + self.log_h + 6
        btn_w = 70
        inp_w = self.log_w - btn_w - 4

        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            self.root,
            textvariable=self._input_var,
            fg=C_TEXT,
            bg="#000d12",
            insertbackground=C_TEXT,
            borderwidth=0,
            font=("Consolas", 10),
            highlightthickness=1,
            highlightbackground=C_DIM,
            highlightcolor=C_PRI,
        )
        self._input_entry.place(x=x0, y=y, width=inp_w, height=28)
        self._input_entry.bind("<Return>", self._on_input_submit)
        self._input_entry.bind("<KP_Enter>", self._on_input_submit)

        self._send_btn = tk.Button(
            self.root,
            text="SEND >",
            command=self._on_input_submit,
            fg=C_PRI,
            bg=C_PANEL,
            activeforeground=C_BG,
            activebackground=C_PRI,
            font=("Consolas", 9, "bold"),
            borderwidth=0,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=C_MID,
        )
        self._send_btn.place(x=x0 + inp_w + 4, y=y, width=btn_w, height=28)

    def _build_mute_button(self):
        self._mute_canvas = tk.Canvas(
            self.root,
            width=110,
            height=32,
            bg=C_BG,
            highlightthickness=0,
            cursor="hand2",
        )
        self._mute_canvas.place(x=18, y=self.H - 70)
        self._mute_canvas.bind("<Button-1>", lambda _event: self.toggle_mute())
        self._draw_mute_button()

    def _build_monitor_button(self):
        self._monitor_canvas = tk.Canvas(
            self.root,
            width=110,
            height=32,
            bg=C_BG,
            highlightthickness=0,
            cursor="hand2",
        )
        self._monitor_canvas.place(x=18, y=76)
        self._monitor_canvas.bind("<Button-1>", lambda _event: self.toggle_monitor())
        self._draw_monitor_button()

    def _build_audio_ducking_button(self):
        self._ducking_canvas = tk.Canvas(
            self.root,
            width=110,
            height=32,
            bg=C_BG,
            highlightthickness=0,
            cursor="hand2",
        )
        self._ducking_canvas.place(x=self.W - 128, y=76)
        self._ducking_canvas.bind("<Button-1>", lambda _event: self.toggle_audio_ducking())
        self._ducking_canvas.bind("<Enter>", self._show_audio_ducking_tooltip)
        self._ducking_canvas.bind("<Leave>", self._hide_audio_ducking_tooltip)
        self._draw_audio_ducking_button()

    def _draw_mute_button(self):
        self._mute_canvas.delete("all")
        border = C_MUTED if self.muted else C_MID
        fill = "#1a0008" if self.muted else C_PANEL
        label = "OFFLINE" if self.muted else "ONLINE"
        fg = C_MUTED if self.muted else C_GREEN
        self._mute_canvas.create_rectangle(0, 0, 110, 32, outline=border, fill=fill, width=1)
        self._mute_canvas.create_text(
            55,
            16,
            text=label,
            fill=fg,
            font=("Consolas", 10, "bold"),
        )

    def _draw_audio_ducking_button(self):
        self._ducking_canvas.delete("all")
        border = C_ACC2 if self.audio_ducking_enabled else C_MID
        fill = "#0f0b22" if self.audio_ducking_enabled else C_PANEL
        label = "DUCK ON" if self.audio_ducking_enabled else "DUCK OFF"
        fg = C_ACC2 if self.audio_ducking_enabled else C_PRI
        self._ducking_canvas.create_rectangle(0, 0, 110, 32, outline=border, fill=fill, width=1)
        self._ducking_canvas.create_text(
            55,
            16,
            text=label,
            fill=fg,
            font=("Consolas", 10, "bold"),
        )

    def _show_audio_ducking_tooltip(self, event=None):
        self._hide_audio_ducking_tooltip()

        self._ducking_tooltip = tk.Toplevel(self.root)
        self._ducking_tooltip.wm_overrideredirect(True)
        self._ducking_tooltip.configure(bg=C_PRI)

        label = tk.Label(
            self._ducking_tooltip,
            text="Lowers other apps while listening",
            fg=C_TEXT,
            bg=C_PANEL,
            font=("Consolas", 9),
            padx=8,
            pady=4,
            borderwidth=0,
        )
        label.pack()

        x = self.root.winfo_rootx() + self.W - 286
        y = self.root.winfo_rooty() + 112
        self._ducking_tooltip.wm_geometry(f"+{x}+{y}")

    def _hide_audio_ducking_tooltip(self, event=None):
        if self._ducking_tooltip is None:
            return

        self._ducking_tooltip.destroy()
        self._ducking_tooltip = None

    def _draw_monitor_button(self):
        self._monitor_canvas.delete("all")
        border = C_PRI if self.monitor_open else C_MID
        fill = "#00131b" if self.monitor_open else C_PANEL
        label = "SYS >" if not self.monitor_open else "< SYS"
        self._monitor_canvas.create_rectangle(0, 0, 110, 32, outline=border, fill=fill, width=1)
        self._monitor_canvas.create_text(
            55,
            16,
            text=label,
            fill=C_PRI,
            font=("Consolas", 10, "bold"),
        )

    def toggle_monitor(self):
        self.monitor_open = not self.monitor_open
        self._draw_monitor_button()

    def toggle_audio_ducking(self):
        self.audio_ducking_enabled = not self.audio_ducking_enabled
        self._draw_audio_ducking_button()
        self._apply_audio_ducking_enabled()

        status = "enabled" if self.audio_ducking_enabled else "disabled"
        self.send_message("System", f"Ducking {status}")

    def _apply_audio_ducking_enabled(self):
        global audio_ducking_enabled

        audio_ducking_enabled = self.audio_ducking_enabled
        try:
            from backend.audio_ducking import set_enabled

            set_enabled(self.audio_ducking_enabled, self.state == "listening")
        except Exception as exc:
            print(f"Audio ducking toggle failed: {exc}")

        self._sync_audio_ducking_refresh()

    def _sample_metrics(self):
        cpu = self._get_cpu_percent()
        ram = self._get_ram_percent()
        gpu = self._get_gpu_percent()

        for name, value in (("CPU", cpu), ("RAM", ram), ("GPU", gpu)):
            self.metrics[name] = value
            self.metric_history[name].append(0 if value is None else value)

        self.root.after(1000, self._sample_metrics)

    def _get_cpu_percent(self):
        try:
            return float(psutil.cpu_percent(interval=None))
        except Exception:
            pass
        return _cpu_meter.percent()

    def _get_ram_percent(self):
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            pass
        if ctypes is None or not hasattr(ctypes, "windll"):
            return None

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return float(status.dwMemoryLoad)

    def _get_gpu_percent(self):
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=0.5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            self.gpu_available = False
            return None

        if result.returncode != 0:
            self.gpu_available = False
            return None

        values = []
        for line in result.stdout.splitlines():
            try:
                values.append(float(line.strip()))
            except ValueError:
                continue

        if not values:
            self.gpu_available = False
            return None

        self.gpu_available = True
        return max(0.0, min(100.0, sum(values) / len(values)))

    def _on_input_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()
        else:
            self.send_message("User", text)

    def set_state(self, new_state):
        global state, state_change_time

        self.state = new_state
        self.state_change_time = time.time()
        state = new_state
        state_change_time = self.state_change_time

        if new_state == "talking":
            self.status_text = "SPEAKING"
            self.speaking = True
        elif new_state == "thinking":
            self.status_text = "THINKING"
            self.speaking = False
        elif new_state == "listening":
            self.status_text = "LISTENING"
            self.speaking = False
        elif new_state == "idle":
            self.status_text = "ONLINE"
            self.speaking = False
        else:
            self.status_text = str(new_state).upper()
            self.speaking = False

        try:
            from backend.audio_ducking import set_listening

            set_listening(new_state == "listening")
        except Exception as exc:
            print(f"Audio ducking state sync failed: {exc}")

        self._sync_audio_ducking_refresh()

    def _sync_audio_ducking_refresh(self):
        should_refresh = self.audio_ducking_enabled and self.state == "listening"
        if should_refresh and self._ducking_refresh_job is None:
            self._ducking_refresh_job = self.root.after(750, self._refresh_audio_ducking)
        elif not should_refresh and self._ducking_refresh_job is not None:
            self.root.after_cancel(self._ducking_refresh_job)
            self._ducking_refresh_job = None

    def _refresh_audio_ducking(self):
        self._ducking_refresh_job = None
        if not self.audio_ducking_enabled or self.state != "listening":
            return

        try:
            from backend.audio_ducking import set_listening

            set_listening(True)
        except Exception as exc:
            print(f"Audio ducking refresh failed: {exc}")

        self._sync_audio_ducking_refresh()

    def send_message(self, sender, text):
        sender_lookup = {
            "jarvis": "Jarvis",
            "user": "User",
            "system": "System",
        }
        sender = sender_lookup.get(str(sender).lower(), "System")
        self.typing_queue.append((sender, str(text)))
        if sender == "Jarvis":
            self.set_state("talking")
        elif sender == "User":
            self.set_state("thinking")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking and not self.muted:
                self.set_state("idle")
            return

        self.is_typing = True
        sender, text = self.typing_queue.popleft()
        text_tag = f"{sender.lower()}_text"

        self.chat_box.configure(state="normal")
        self.chat_box.insert(tk.END, f"{sender}: ", sender)
        self._type_char(text, 0, text_tag)

    def _type_char(self, text, index, tag):
        if index < len(text):
            self.chat_box.insert(tk.END, text[index], tag)
            self.chat_box.see(tk.END)
            self.root.after(8, self._type_char, text, index + 1, tag)
            return

        self.chat_box.insert(tk.END, "\n")
        self.chat_box.see(tk.END)
        self.chat_box.configure(state="disabled")
        self.root.after(25, self._start_typing)

    def toggle_mute(self):
        global is_muted

        self.muted = not self.muted
        is_muted = self.muted
        self._draw_mute_button()
        if self.muted:
            play_sound_async(MUTE_SOUND, "Mute sound")
            self.set_state("muted")
            self.send_message("System", "Muted")
        else:
            play_sound_async(UNMUTE_SOUND, "Unmute sound")
            self.set_state("idle")
            self.send_message("System", "Unmuted")

    def _animate(self):
        self.tick += 1
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo = random.uniform(138, 182)
            elif self.muted:
                self.target_scale = random.uniform(0.998, 1.001)
                self.target_halo = random.uniform(20, 32)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo = random.uniform(50, 68)
            self.last_t = now

        speed = 0.35 if self.speaking else 0.16
        self.scale += (self.target_scale - self.scale) * speed
        self.halo_a += (self.target_halo - self.halo_a) * speed

        ring_speeds = [1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]
        for i, ring_speed in enumerate(ring_speeds):
            self.rings_spin[i] = (self.rings_spin[i] + ring_speed) % 360

        self.scan_angle = (self.scan_angle + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pulse_speed = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        self.pulse_r = [r + pulse_speed for r in self.pulse_r if r + pulse_speed < limit]
        if len(self.pulse_r) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            self.pulse_r.append(0.0)

        if self.tick % 40 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(16, self._animate)

    def _draw(self):
        c = self.canvas
        c.delete("all")

        self._draw_grid(c)
        self._draw_core(c)
        self._draw_header(c)
        self._draw_status(c)
        if self.monitor_open:
            self._draw_monitor_panel(c)
        self._draw_footer(c)

    def _draw_grid(self, c):
        for x in range(0, self.W, 44):
            for y in range(0, self.H, 44):
                c.create_rectangle(x, y, x + 1, y + 1, fill=C_DIMMER, outline="")

    def _draw_core(self, c):
        fc_x = self.FCX
        fc_y = self.FCY
        fw = self.FACE_SZ

        for r in range(int(fw * 0.54), int(fw * 0.28), -22):
            frac = 1.0 - (r - fw * 0.28) / (fw * 0.26)
            alpha = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            color = self._ac(255, 30, 80, alpha) if self.muted else self._ac(0, 212, 255, alpha)
            c.create_oval(fc_x - r, fc_y - r, fc_x + r, fc_y + r, outline=color, width=2)

        for radius in self.pulse_r:
            alpha = max(0, int(220 * (1.0 - radius / (fw * 0.72))))
            r = int(radius)
            color = self._ac(255, 30, 80, alpha // 3) if self.muted else self._ac(0, 212, 255, alpha)
            c.create_oval(fc_x - r, fc_y - r, fc_x + r, fc_y + r, outline=color, width=2)

        for idx, (r_frac, width, arc_len, gap) in enumerate(
            [(0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]
        ):
            ring_r = int(fw * r_frac)
            base_angle = self.rings_spin[idx]
            alpha = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            color = self._ac(255, 30, 80, alpha) if self.muted else self._ac(0, 212, 255, alpha)
            for segment in range(360 // (arc_len + gap)):
                start = (base_angle + segment * (arc_len + gap)) % 360
                c.create_arc(
                    fc_x - ring_r,
                    fc_y - ring_r,
                    fc_x + ring_r,
                    fc_y + ring_r,
                    start=start,
                    extent=arc_len,
                    outline=color,
                    width=width,
                    style="arc",
                )

        scan_r = int(fw * 0.49)
        scan_alpha = min(255, int(self.halo_a * 1.4))
        scan_extent = 70 if self.speaking else 42
        scan_col = self._ac(255, 30, 80, scan_alpha) if self.muted else self._ac(0, 212, 255, scan_alpha)
        c.create_arc(
            fc_x - scan_r,
            fc_y - scan_r,
            fc_x + scan_r,
            fc_y + scan_r,
            start=self.scan_angle,
            extent=scan_extent,
            outline=scan_col,
            width=3,
            style="arc",
        )
        c.create_arc(
            fc_x - scan_r,
            fc_y - scan_r,
            fc_x + scan_r,
            fc_y + scan_r,
            start=self.scan2_angle,
            extent=scan_extent,
            outline=self._ac(255, 100, 0, scan_alpha // 2),
            width=2,
            style="arc",
        )

        tick_out = int(fw * 0.495)
        tick_in = int(fw * 0.472)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inner = tick_in if deg % 30 == 0 else tick_in + 5
            c.create_line(
                fc_x + tick_out * math.cos(rad),
                fc_y - tick_out * math.sin(rad),
                fc_x + inner * math.cos(rad),
                fc_y - inner * math.sin(rad),
                fill=self._ac(0, 212, 255, 155),
                width=1,
            )

        cross_r = int(fw * 0.50)
        gap = int(fw * 0.15)
        cross_col = self._ac(0, 212, 255, int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
            (fc_x - cross_r, fc_y, fc_x - gap, fc_y),
            (fc_x + gap, fc_y, fc_x + cross_r, fc_y),
            (fc_x, fc_y - cross_r, fc_x, fc_y - gap),
            (fc_x, fc_y + gap, fc_x, fc_y + cross_r),
        ]:
            c.create_line(x1, y1, x2, y2, fill=cross_col, width=1)

        bracket_len = 22
        bracket_col = self._ac(0, 212, 255, 200)
        left = fc_x - fw // 2
        right = fc_x + fw // 2
        top = fc_y - fw // 2
        bottom = fc_y + fw // 2
        for bx, by, sdx, sdy in [
            (left, top, 1, 1),
            (right, top, -1, 1),
            (left, bottom, 1, -1),
            (right, bottom, -1, -1),
        ]:
            c.create_line(bx, by, bx + sdx * bracket_len, by, fill=bracket_col, width=2)
            c.create_line(bx, by, bx, by + sdy * bracket_len, fill=bracket_col, width=2)

        orb_r = int(fw * 0.27 * self.scale)
        orb_color = (255, 30, 80) if self.muted else (0, 65, 120)
        for i in range(7, 0, -1):
            r2 = int(orb_r * i / 7)
            frac = i / 7
            alpha = max(0, min(255, int(self.halo_a * 1.1 * frac)))
            c.create_oval(
                fc_x - r2,
                fc_y - r2,
                fc_x + r2,
                fc_y + r2,
                fill=self._ac(
                    int(orb_color[0] * frac),
                    int(orb_color[1] * frac),
                    int(orb_color[2] * frac),
                    alpha,
                ),
                outline="",
            )

        c.create_text(
            fc_x,
            fc_y,
            text=SYSTEM_NAME,
            fill=self._ac(0, 212, 255, min(255, int(self.halo_a * 2))),
            font=("Consolas", 14, "bold"),
        )

    def _draw_header(self, c):
        header_h = 62
        c.create_rectangle(0, 0, self.W, header_h, fill="#00080d", outline="")
        c.create_line(0, header_h, self.W, header_h, fill=C_MID, width=1)
        c.create_text(
            self.W // 2,
            22,
            text=SYSTEM_NAME,
            fill=C_PRI,
            font=("Consolas", 18, "bold"),
        )
        c.create_text(
            self.W // 2,
            44,
            text="Say 'Hey Jarvis'",
            fill=C_MID,
            font=("Consolas", 9),
        )
        c.create_text(16, 31, text=MODEL_BADGE, fill=C_DIM, font=("Consolas", 9), anchor="w")
        c.create_text(
            self.W - 16,
            31,
            text=datetime.now().strftime("%H:%M:%S"),
            fill=C_PRI,
            font=("Consolas", 14, "bold"),
            anchor="e",
        )

    def _draw_status(self, c):
        y = self.FCY + self.FACE_SZ // 2 + 45

        if self.muted:
            status = "OFFLINE"
            color = C_MUTED
        elif self.speaking:
            status = "SPEAKING"
            color = C_ACC
        elif self.state == "thinking":
            status = "THINKING"
            color = C_ACC2
        elif self.state == "listening":
            status = "LISTENING"
            color = C_GREEN
        else:
            status = self.status_text
            color = C_PRI

        lead = "⚫" if self.status_blink else "⚪"
        c.create_text(
            self.W // 2,
            y,
            text=f"{lead}{status}",
            fill=color,
            font=("Consolas", 11, "bold"),
        )

        wave_y = y + 22
        count = 32
        max_h = 18
        bar_w = 8
        start_x = (self.W - count * bar_w) // 2
        for i in range(count):
            if self.muted:
                height = 2
                color = C_MUTED
            elif self.speaking:
                height = random.randint(3, max_h)
                color = C_PRI if height > max_h * 0.6 else C_MID
            elif self.state == "thinking":
                height = int(6 + 8 * abs(math.sin(self.tick * 0.08 + i * 0.18)))
                color = C_ACC2 if i % 3 == 0 else C_DIM
            else:
                height = int(3 + 2 * math.sin(self.tick * 0.08 + i * 0.55))
                color = C_DIM
            x = start_x + i * bar_w
            c.create_rectangle(x, wave_y + max_h - height, x + bar_w - 1, wave_y + max_h, fill=color, outline="")

    def _draw_monitor_panel(self, c):
        x = 18
        y = 116
        w = 248
        h = 330

        c.create_rectangle(x, y, x + w, y + h, fill="#00080d", outline=C_MID, width=1)
        c.create_line(x, y + 36, x + w, y + 36, fill=C_DIM, width=1)
        c.create_text(
            x + 14,
            y + 18,
            text="SYSTEM MONITOR",
            fill=C_PRI,
            font=("Consolas", 11, "bold"),
            anchor="w",
        )

        rows = [
            ("CPU", C_PRI, y + 58),
            ("RAM", C_GREEN, y + 152),
            ("GPU", C_ACC2, y + 246),
        ]

        for name, color, row_y in rows:
            value = self.metrics[name]
            label = "N/A" if value is None else f"{value:.0f}%"
            c.create_text(
                x + 14,
                row_y,
                text=name,
                fill=color,
                font=("Consolas", 10, "bold"),
                anchor="w",
            )
            c.create_text(
                x + w - 14,
                row_y,
                text=label,
                fill=color if value is not None else C_DIM,
                font=("Consolas", 10, "bold"),
                anchor="e",
            )
            self._draw_metric_graph(c, x + 14, row_y + 16, w - 28, 50, self.metric_history[name], color, value)

        if self.metrics["GPU"] is None:
            c.create_text(
                x + 14,
                y + h - 14,
                text="GPU: nvidia-smi unavailable",
                fill=C_DIM,
                font=("Consolas", 8),
                anchor="w",
            )

    def _draw_metric_graph(self, c, x, y, w, h, history, color, value):
        c.create_rectangle(x, y, x + w, y + h, fill="#000d12", outline=C_DIM, width=1)
        for i in range(1, 4):
            gy = y + h - (h * i / 4)
            c.create_line(x + 1, gy, x + w - 1, gy, fill=C_DIMMER, width=1)

        values = list(history)
        if len(values) < 2:
            return

        step = w / (len(values) - 1)
        points = []
        for index, item in enumerate(values):
            px = x + index * step
            py = y + h - (max(0.0, min(100.0, item)) / 100.0) * (h - 4) - 2
            points.extend([px, py])

        c.create_line(*points, fill=color if value is not None else C_DIM, width=2, smooth=True)
        if value is not None:
            fill_h = (max(0.0, min(100.0, value)) / 100.0) * h
            c.create_rectangle(x + w, y + h - fill_h, x + w - 1, y + h, fill=color, outline="")

    def _draw_footer(self, c):
        c.create_rectangle(0, self.H - 28, self.W, self.H, fill="#00080d", outline="")
        c.create_line(0, self.H - 28, self.W, self.H - 28, fill=C_DIM, width=1)
        c.create_text(
            self.W - 16,
            self.H - 14,
            fill=C_DIM,
            font=("Consolas", 8),
            text="[F6] MUTE",
            anchor="e",
        )
        c.create_text(
            self.W // 2,
            self.H - 14,
            fill=C_DIM,
            font=("Consolas", 8),
            text="Made by Zero",
        )


_gui = JarvisGui()

root = _gui.root
canvas = _gui.canvas
chat_box = _gui.chat_box
time_label = None
clock_label = None


def set_state(new_state):
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(set_state, new_state)
        return

    _gui.set_state(new_state)


def send_message(sender, text):
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(send_message, sender, text)
        return

    _gui.send_message(sender, text)


def toggle_mute():
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(toggle_mute)
        return

    global is_muted
    _gui.toggle_mute()
    is_muted = _gui.muted


def toggle_audio_ducking():
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(toggle_audio_ducking)
        return

    global audio_ducking_enabled
    _gui.toggle_audio_ducking()
    audio_ducking_enabled = _gui.audio_ducking_enabled


def get_audio_ducking_enabled():
    return audio_ducking_enabled


def set_text_command(callback):
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(set_text_command, callback)
        return

    _gui.on_text_command = callback


def get_muted():
    return is_muted


def animate_text(label, text, delay=0.02):
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(animate_text, label, text, delay)
        return

    label.config(text="")

    def type_char(index=0):
        if index >= len(text):
            return
        label.config(text=label.cget("text") + text[index])
        root.after(max(1, int(delay * 1000)), type_char, index + 1)

    type_char()


def interpolate_color(color1, color2, t):
    t = max(0.0, min(1.0, t))
    r1 = int(color1[1:3], 16)
    g1 = int(color1[3:5], 16)
    b1 = int(color1[5:7], 16)
    r2 = int(color2[1:3], 16)
    g2 = int(color2[3:5], 16)
    b2 = int(color2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def fade_item(item, target_color, duration=300, steps=10):
    start_color = canvas.itemcget(item, "fill")
    delay = max(1, duration // max(1, steps))

    def fade_step(index):
        if index > steps:
            return
        canvas.itemconfig(item, fill=interpolate_color(start_color, target_color, index / steps))
        root.after(delay, fade_step, index + 1)

    fade_step(0)


def reset_circles():
    _gui.scale = 1.0
    _gui.target_scale = 1.0


def update_clock():
    return None


def update_timer():
    return None


def update_mute_indicator():
    _gui._draw_mute_button()


def animate_idle():
    set_state("idle")


def animate_listening():
    set_state("listening")


def animate_thinking():
    set_state("thinking")


def animate_talking():
    set_state("talking")


_drain_ui_queue()
