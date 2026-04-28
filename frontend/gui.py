from math import *
import tkinter as tk
from tkinter import scrolledtext
import time
import threading
import queue
from datetime import datetime

# Global state and timing
state = "idle"
state_change_time = time.time()
last_state = "idle"
is_muted = False
listening_start_time = None
thinking_start_time = None
thinking_timer_active = False

# Color themes
NORMAL_COLORS = {
    "bg": "#0a0e27",
    "top_bg": "#0f1538",
    "primary": "#00d4ff",
    "secondary": "#b5fdff",
    "dark1": "#16213e",
    "dark2": "#1a1a2e",
    "dark3": "#0f3460"
}

MUTED_COLORS = {
    "bg": "#2d0a0a",
    "top_bg": "#380f0f",
    "primary": "#ff3333",
    "secondary": "#ff9999",
    "dark1": "#3e1616",
    "dark2": "#2e1a1a",
    "dark3": "#603f0f"
}

current_colors = NORMAL_COLORS.copy()
_MAIN_THREAD_ID = threading.get_ident()
_ui_queue = queue.Queue()


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

def __init__():
    """Initialize the GUI"""
    global root, canvas, glow_circles, outer_circle, inner_circle, center_circle
    global time_label, chat_box, title_label, clock_label, decorative_elements, star_elements
    
    root = tk.Tk()
    root.title("Jarvis")
    root.geometry("900x900")
    root.configure(bg=current_colors["bg"])
    
    # Top bar with title and clock
    top_frame = tk.Frame(root, bg=current_colors["top_bg"], height=60)
    top_frame.pack(fill=tk.X)
    
    # Title "J.A.R.V.I.S."
    title_label = tk.Label(top_frame, text="J.A.R.V.I.S.", font=("Consolas", 28, "bold"), 
                           bg=current_colors["top_bg"], fg=current_colors["primary"])
    title_label.pack(side=tk.LEFT, padx=20, pady=10)
    
    # Clock in top right
    clock_label = tk.Label(top_frame, text="", font=("Consolas", 14), 
                          bg=current_colors["top_bg"], fg=current_colors["primary"])
    clock_label.pack(side=tk.RIGHT, padx=20, pady=10)
    
    # Mute indicator
    mute_indicator = tk.Label(top_frame, text="", font=("Consolas", 12), 
                             bg=current_colors["top_bg"], fg=current_colors["secondary"])
    mute_indicator.pack(side=tk.RIGHT, padx=10, pady=10)
    root.mute_indicator = mute_indicator
    
    # Separator line
    separator = tk.Frame(root, bg=current_colors["primary"], height=2)
    separator.pack(fill=tk.X)
    
    # Main content frame
    content_frame = tk.Frame(root, bg=current_colors["bg"])
    content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
    
    # Canvas for animation (bigger)
    canvas = tk.Canvas(content_frame, width=500, height=500, bg=current_colors["bg"], highlightthickness=0)
    canvas.pack(pady=20)
    
    # Create decorative elements
    decorative_elements = []
    star_elements = []
    
    # Orbital rings for decoration
    for i in range(3):
        ring = canvas.create_oval(250-100-i*40, 250-100-i*40, 250+100+i*40, 250+100+i*40,
                                 outline=current_colors["primary"], width=1, fill="")
        canvas.itemconfig(ring, dash=(4, 4))
        decorative_elements.append(ring)
    
    # Create multiple circles for glow effect (bigger)
    glow_circles = []
    for i in range(5):
        glow = canvas.create_oval(150-i*12, 150-i*12, 350+i*12, 350+i*12, 
            outline=current_colors["primary"], width=2, 
            fill="", state="hidden")
        glow_circles.append(glow)
    
    # Main circle with gradient-like appearance (MUCH BIGGER)
    outer_circle = canvas.create_oval(100, 100, 400, 400, fill=current_colors["dark1"], 
                                      outline=current_colors["primary"], width=4)
    inner_circle = canvas.create_oval(150, 150, 350, 350, fill=current_colors["dark2"], 
                                      outline=current_colors["primary"], width=3)
    center_circle = canvas.create_oval(200, 200, 300, 300, fill=current_colors["dark3"], 
                                       outline=current_colors["primary"], width=2)
    
    # Time display label
    time_label = tk.Label(content_frame, text="", font=("Consolas", 16, "bold"), 
                         bg=current_colors["bg"], fg=current_colors["secondary"])
    time_label.pack(pady=10)
    
    # Chat box frame (bigger)
    chat_frame = tk.Frame(content_frame, bg=current_colors["top_bg"], height=300)
    chat_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=10)
    
    # Text widget for chat (no scrollbar)
    chat_box = tk.Text(chat_frame, bg=current_colors["dark2"], fg=current_colors["primary"], 
                       font=("Consolas", 14), height=12, state=tk.DISABLED,
                       wrap=tk.WORD, insertbackground=current_colors["primary"])
    
    chat_box.pack(fill=tk.BOTH, expand=True)
    
    # Add text tags for different senders
    chat_box.tag_config("Jarvis", foreground="#00758d", font=("Consolas", 14, "bold"))
    chat_box.tag_config("User", foreground="#0073FF", font=("Consolas", 14, "bold"))
    chat_box.tag_config("System", foreground="#ff3333", font=("Consolas", 14, "bold"))
    chat_box.tag_config("jarvis_text", foreground="#00d4ff", font=("Consolas", 14))
    chat_box.tag_config("user_text", foreground="#003E8A", font=("Consolas", 14))
    chat_box.tag_config("system_text", foreground="#ff3333", font=("Consolas", 14))
    
    root.canvas_bg = canvas
    
    return root, canvas, glow_circles, outer_circle, inner_circle, center_circle, time_label, clock_label, chat_box, decorative_elements, star_elements

root, canvas, glow_circles, outer_circle, inner_circle, center_circle, time_label, clock_label, chat_box, decorative_elements, star_elements = __init__()

def interpolate_color(color1, color2, t):
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
    delay = duration // steps
    def fade_step(i):
        if i > steps:
            return
        t = i / steps
        color = interpolate_color(start_color, target_color, t)
        canvas.itemconfig(item, fill=color)
        root.after(delay, fade_step, i+1)
    fade_step(0)

# Animation functions
def reset_circles():
    for glow in glow_circles:
        canvas.itemconfig(glow, state="hidden")
    canvas.itemconfig(outer_circle, fill=current_colors["dark1"], outline=current_colors["primary"])
    canvas.itemconfig(inner_circle, fill=current_colors["dark2"], outline=current_colors["primary"])
    canvas.itemconfig(center_circle, fill=current_colors["dark3"], outline=current_colors["primary"])

def update_clock():
    """Update the clock in the top right corner"""
    current_time = datetime.now().strftime("%H:%M:%S")
    clock_label.config(text=current_time)
    root.after(1000, update_clock)

def update_timer():
    """Update the delta time display"""
    global state_change_time, last_state, listening_start_time, thinking_start_time, thinking_timer_active
    
    if state == "idle":
        time_label.config(text="Ready")
        thinking_timer_active = False
    elif state == "listening":
        if listening_start_time is None:
            listening_start_time = time.time()
        elapsed = time.time() - listening_start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_label.config(text=f"LISTENING: {minutes}:{seconds:02d}")
    elif state == "thinking":
        if thinking_start_time is None:
            thinking_start_time = time.time()
            thinking_timer_active = True
        elapsed = time.time() - thinking_start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_label.config(text=f"THINKING: {minutes}:{seconds:02d}")
    else:
        elapsed = time.time() - state_change_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_label.config(text=f"{state.upper()}: {minutes}:{seconds:02d}")
    
    root.after(100, update_timer)

def animate_thinking():
    global state, thinking_start_time
    state = "thinking"
    thinking_start_time = None
    reset_circles()
    fade_item(center_circle, current_colors["dark1"], duration=500, steps=20)
    
    dots = []
    for i in range(8):
        angle = i * 45
        x = 250 + 80 * (1 if angle < 180 else -1) * abs(sin(radians(angle)))
        y = 250 + 80 * (1 if 90 <= angle < 270 else -1) * abs(cos(radians(angle)))
        dot = canvas.create_oval(x-6, y-6, x+6, y+6, fill=current_colors["primary"], outline=current_colors["secondary"], width=2)
        dots.append(dot)

    def rotate_dots():
        if state != "thinking":
            for dot in dots:
                try:
                    canvas.delete(dot)
                except:
                    pass
            return
        for i, dot in enumerate(dots):
            angle = (i * 45 + int(time.time() * 60) % 360) % 360
            x = 250 + 120 * cos(radians(angle))
            y = 250 + 120 * sin(radians(angle))
            canvas.coords(dot, x-6, y-6, x+6, y+6)
        root.after(50, rotate_dots)

    rotate_dots()

def animate_listening():
    global state, listening_start_time
    state = "listening"
    listening_start_time = None
    reset_circles()
    fade_item(center_circle, current_colors["dark2"], duration=500, steps=20)

    bars = []
    for i in range(9):
        bar = canvas.create_rectangle(162 + i*20, 220, 177 + i*20, 280, 
                                       fill=current_colors["secondary"], outline=current_colors["primary"], width=1)
        bars.append(bar)
    
    def animate_bars():
        if state != "listening":
            for bar in bars:
                try:
                    canvas.delete(bar)
                except:
                    pass
            return
        for i, bar in enumerate(bars):
            height = 30 + 25 * sin((time.time() * 6) + i * 0.4)
            canvas.coords(bar, 162 + i*20, 250 - height, 177 + i*20, 250 + height)
        root.after(50, animate_bars)

    animate_bars()

def animate_talking():
    global state
    state = "talking"
    reset_circles()
    fade_item(center_circle, current_colors["dark3"], duration=500, steps=20)

    def pulse():
        if state != "talking":
            reset_circles()
            return
        for i, glow in enumerate(glow_circles):
            canvas.itemconfig(glow, state="normal")
            alpha = int(255 * (0.4 + 0.25 * sin(time.time() * 5 + i * 0.5)))
            color = interpolate_color(current_colors["primary"], current_colors["dark1"], 0.3)
            canvas.itemconfig(glow, outline=color, width=2)

        offset = 12 * sin(time.time() * 4)
        canvas.coords(outer_circle, 100-offset, 100-offset, 400+offset, 400+offset)
        canvas.coords(inner_circle, 150-offset/2, 150-offset/2, 350+offset/2, 350+offset/2)
        
        # Add pulsing effect to center circle fill
        pulse_color = interpolate_color(current_colors["dark3"], current_colors["primary"], 
                                       0.2 + 0.15 * sin(time.time() * 4))
        canvas.itemconfig(center_circle, fill=pulse_color)

        root.after(50, pulse)

    pulse()

def animate_idle():
    global state
    state = "idle"
    reset_circles()
    fade_item(center_circle, current_colors["dark3"], duration=500, steps=20)

    def breathe():
        if state != "idle":
            return
        offset = 6 * sin(time.time() * 1.5)
        canvas.coords(outer_circle, 100-offset, 100-offset, 400+offset, 400+offset)
        canvas.coords(inner_circle, 150-offset/2, 150-offset/2, 350+offset/2, 350+offset/2)
        
        # Subtle glow effect on standby
        for i, glow in enumerate(glow_circles):
            if i < 2:
                canvas.itemconfig(glow, state="normal")
                alpha = int(100 * (0.2 + 0.1 * sin(time.time() * 1 + i)))
                canvas.itemconfig(glow, outline=current_colors["primary"], width=1)
            else:
                canvas.itemconfig(glow, state="hidden")
        
        root.after(50, breathe)

    breathe()

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

def set_state(new_state):
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(set_state, new_state)
        return

    global state, state_change_time, listening_start_time, thinking_start_time
    state = new_state
    state_change_time = time.time()
    
    # Reset timers when transitioning states
    if new_state != "listening":
        listening_start_time = None
    if new_state != "thinking":
        thinking_start_time = None
    
    if new_state == "idle":
        animate_idle()
    elif new_state == "listening":
        animate_listening()
    elif new_state == "thinking":
        animate_thinking()
    elif new_state == "talking":
        animate_talking()

def send_message(sender, text):
    if threading.get_ident() != _MAIN_THREAD_ID:
        _run_or_queue(send_message, sender, text)
        return

    """Add a message to the chat box with color coding and animation"""
    chat_box.config(state=tk.NORMAL)

    sender_tag = sender.lower() if sender.lower() in ["jarvis", "user", "system"] else "System"
    chat_box.insert(tk.END, f"{sender}: ", sender_tag)

    text_tag = f"{sender.lower()}_text"

    def type_char(index=0):
        if index < len(text):
            chat_box.insert(tk.END, text[index], text_tag)
            chat_box.see(tk.END)
            root.after(10, type_char, index + 1)
            return

        chat_box.insert(tk.END, "\n")
        chat_box.see(tk.END)
        chat_box.config(state=tk.DISABLED)

    type_char()

def toggle_mute():
    """Toggle muted mode with theme animation"""
    global is_muted, current_colors
    
    is_muted = not is_muted
    target_colors = MUTED_COLORS if is_muted else NORMAL_COLORS
    
    # Animate theme change
    def animate_theme_change(step, total_steps=20):
        if step > total_steps:
            current_colors.update(target_colors)
            update_mute_indicator()
            return
        
        # Interpolate between current and target colors
        progress = step / total_steps
        for key in NORMAL_COLORS.keys():
            current_val = current_colors[key]
            target_val = target_colors[key]
            interpolated = interpolate_color(current_val, target_val, progress)
            current_colors[key] = interpolated
        
        # Update UI elements
        root.configure(bg=current_colors["bg"])
        canvas.configure(bg=current_colors["bg"])
        title_label.config(bg=current_colors["top_bg"], fg=current_colors["primary"])
        clock_label.config(bg=current_colors["top_bg"], fg=current_colors["primary"])
        root.mute_indicator.config(bg=current_colors["top_bg"], fg=current_colors["secondary"])
        time_label.config(bg=current_colors["bg"], fg=current_colors["secondary"])
        chat_box.config(bg=current_colors["dark2"], fg=current_colors["primary"], 
                       insertbackground=current_colors["primary"])
        
        # Update decorative elements
        for elem in decorative_elements:
            canvas.itemconfig(elem, outline=current_colors["primary"])
        for star in star_elements:
            canvas.itemconfig(star, fill=current_colors["primary"], outline=current_colors["secondary"])
        
        reset_circles()
        
        root.after(30, animate_theme_change, step + 1, total_steps)
    
    animate_theme_change(0)

def update_mute_indicator():
    """Update the mute indicator label"""
    if is_muted:
        root.mute_indicator.config(text="[MUTED]", fg=current_colors["primary"])
    else:
        root.mute_indicator.config(text="", fg=current_colors["primary"])

# Start the timer and clock updates
_drain_ui_queue()
update_timer()
update_clock()

# Bind keyboard shortcut for mute toggle (Ctrl+M)
root.bind('<Control-m>', lambda e: toggle_mute())
