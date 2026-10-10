# -*- coding: utf-8 -*-
"""Overlay de bureau : affiche la batterie du clavier et de la souris.

Un petit cadre sombre pose sur le bureau (derriere les fenetres), que l'on peut
deplacer a la souris et verrouiller, avec un clic droit pour les options
(position, verrouillage, demarrage Windows, quitter).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import tkinter as tk

try:
    import hid  # noqa: F401
except ImportError:
    import tkinter.messagebox as mb
    _r = tk.Tk()
    _r.withdraw()
    mb.showerror(
        "Dependance manquante",
        "Le module Python 'hidapi' est requis.\n\nInstalle-le avec :\n\n"
        "    pip install hidapi",
    )
    sys.exit(1)

from battery_readers import (  # noqa: E402
    POLL_SECONDS, LogitechKeyboardReader, VxeMouseReader,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
CONFIG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BatteryOverlay"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "BatteryOverlay"

BG = "#1c1c1e"
BORDER = "#3a3a3c"
FG = "#f2f2f7"
DIM = "#8e8e93"
GREEN = "#34c759"
ORANGE = "#ff9f0a"
RED = "#ff3b30"
BLUE = "#0a84ff"

HOVER_SECONDS = 1.0           # duree de survol avant d'afficher l'autonomie
HISTORY_WINDOW = 24 * 3600    # fenetre d'historique conservee (24 h)
HISTORY_SAVE_INTERVAL = 60    # sauvegarde du fichier au plus toutes les 60 s

EMPTY_MV = 3400               # tension approximative d'une cellule Li-Po vide
MIN_VOLT_POINTS = 2           # nb mini de points pour estimer via la tension
MIN_VOLT_SPAN = 120           # duree mini (s) pour estimer via la tension
MIN_VOLT_DROP = 1             # chute mini (mV) pour estimer via la tension
MAX_REMAINING = 300 * 3600    # au-dela : estimation non credible (300 h)

# Autonomie nominale (heures) a 100 %, utilisee UNIQUEMENT tant qu'aucune
# decharge n'a encore ete mesuree (batterie sur un palier, premiere utilisation).
NOMINAL_HOURS = {"kb": 30.0, "mouse": 60.0}


# ---------------------------------------------------------------------------
# Configuration / demarrage automatique
# ---------------------------------------------------------------------------
def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def _format_duration(seconds):
    """Formate une duree en chaine compacte : '4h10', '45min', '<1min'."""
    if seconds is None:
        return None
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h{m:02d}" if m else f"{h}h"
    if m:
        return f"{m}min"
    return "<1min"


def _trend(points, index):
    """Pente par seconde d'une serie (par moindres carres). None si inderterminee."""
    n = len(points)
    if n < 2:
        return None
    t0 = points[0][0]
    xs = [p[0] - t0 for p in points]
    ys = [p[index] for p in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return num / denom


def estimate_remaining(history, percent, voltage=None, now=None):
    """Estime le temps d'autonomie restant (en secondes) ou None si inconnu.

    Deux methodes, dans l'ordre :

    1. la tension (si connue) : sa variation est plus fine que le pourcentage
       entier, ce qui donne une estimation beaucoup plus rapidement ;
    2. le pourcentage : (baisse de %) / (duree ecoulee) sur la fenetre.

    La pente est calculee par regression lineaire (plus robuste au bruit qu'un
    simple premier/dernier point).
    """
    now = now if now is not None else time.time()
    pts = [p for p in history if now - p[0] <= HISTORY_WINDOW]
    if len(pts) < 2:
        return None

    # 1) estimation par la tension
    if voltage is not None:
        pv = [p for p in pts if len(p) > 2 and p[2] is not None]
        if len(pv) >= MIN_VOLT_POINTS:
            span = pv[-1][0] - pv[0][0]
            if span >= MIN_VOLT_SPAN and pv[0][2] - pv[-1][2] >= MIN_VOLT_DROP:
                slope = _trend(pv, 2)            # mV par seconde (< 0 si decharge)
                if slope is not None and slope < 0:
                    remaining = (voltage - EMPTY_MV) / (-slope)
                    if 0 < remaining <= MAX_REMAINING:
                        return remaining

    # 2) repli sur le pourcentage
    if percent is None:
        return None
    pp = [p for p in pts if p[1] is not None]
    if len(pp) >= 2:
        span = pp[-1][0] - pp[0][0]
        if span >= 60 and pp[0][1] - pp[-1][1] > 0:
            slope = _trend(pp, 1)                # % par seconde (< 0 si decharge)
            if slope is not None and slope < 0:
                remaining = percent / (-slope)
                if remaining <= MAX_REMAINING:
                    return remaining
    return None


def autostart_command():
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def is_autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_READ) as k:
            try:
                winreg.QueryValueEx(k, RUN_VALUE)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def set_autostart(enabled):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ,
                                  autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def apply_desktop_behavior(root):
    """Rend l'overlay non activable et le pose sur le bureau (sous les apps).

    Renvoie le handle de fenetre (HWND) pour pouvoir le replacer au besoin.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        HWND_BOTTOM = 1
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        )
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        return hwnd
    except Exception:
        return None


def send_to_bottom(hwnd):
    """Replace la fenetre au fond (au-dessus du bureau, sous les autres)."""
    if not hwnd:
        return
    try:
        import ctypes
        HWND_BOTTOM = 1
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_BOTTOM, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------
class Overlay:
    def __init__(self):
        self.cfg = load_config()
        self.hist = self.cfg.get("history", {}) or {}
        self.last_est = self.cfg.get("last_est", {}) or {}
        self._history_dirty = False
        self._last_history_save = time.time()
        self._show_est = False
        self._hover_start = None
        self._lock = threading.Lock()
        self.kb_value = None
        self.locked = bool(self.cfg.get("locked", False))
        self._user_moved = False
        self._target_xy = None

        self.kb_reader = LogitechKeyboardReader()
        self.mouse_reader = VxeMouseReader()

        self.root = tk.Tk()
        self.root.title("Batterie")
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-alpha", float(self.cfg.get("alpha", 0.92)))
        except Exception:
            pass
        self.root.configure(bg=BORDER)

        self._build_ui()
        self._place_window()
        self.hwnd = apply_desktop_behavior(self.root)
        self._bind_recursive(self.container)
        self._build_menu()

        threading.Thread(target=self._keyboard_loop, daemon=True).start()
        threading.Thread(target=self.mouse_reader.run, daemon=True).start()

        self.root.after(600, self._refresh)
        self.root.after(500, self._poll_hover)

    # -- interface ---------------------------------------------------------
    def _build_ui(self):
        self.container = tk.Frame(self.root, bg=BG, bd=0)
        self.container.pack(fill="both", expand=True, padx=1, pady=1)

        title = tk.Label(self.container, text="BATTERIE", bg=BG, fg=DIM,
                         font=("Segoe UI", 8, "bold"))
        title.pack(anchor="w", padx=14, pady=(10, 4))

        self.kb_ui = self._make_row(self.kb_reader.label, "kb")
        self.mouse_ui = self._make_row(self.mouse_reader.label, "mouse")

        hint = tk.Label(self.container,
                        text=self._hint_text(),
                        bg=BG, fg=DIM, font=("Segoe UI", 7))
        hint.pack(anchor="w", padx=14, pady=(2, 8))
        self.hint = hint

    def _hint_text(self):
        if self.locked:
            return "verrouille  •  clic droit pour liberer"
        return "glisser: deplacer  •  survol: autonomie"

    def _make_row(self, name, key):
        row = tk.Frame(self.container, bg=BG)
        row.pack(fill="x", padx=14, pady=(0, 6))

        top = tk.Frame(row, bg=BG)
        top.pack(fill="x")
        name_lbl = tk.Label(top, text=name, bg=BG, fg=FG, width=17,
                            anchor="w", font=("Segoe UI", 10))
        name_lbl.pack(side="left")
        value_lbl = tk.Label(top, text="—", bg=BG, fg=DIM, width=8,
                             anchor="e", font=("Segoe UI", 10, "bold"))
        value_lbl.pack(side="right")

        bar = tk.Canvas(row, width=190, height=8, bg=BG, highlightthickness=0)
        bar.pack(fill="x", pady=(4, 0))
        fill = bar.create_rectangle(0, 0, 0, 8, fill=DIM, width=0)
        bg_rect = bar.create_rectangle(0, 0, 190, 8, fill="#3a3a3c", width=0)
        bar.tag_lower(bg_rect)
        return {"bar": bar, "fill": fill, "value": value_lbl,
                "name": name_lbl, "key": key, "_bar": None, "_txt": None}

    def _set_bar(self, ui, percent, color):
        state = (percent, color)
        if ui.get("_bar") == state:
            return
        ui["_bar"] = state
        bar = ui["bar"]
        width = bar.winfo_width()
        if width <= 1:
            width = 190
        w = int(width * max(0, min(100, percent)) / 100)
        bar.coords(ui["fill"], 1, 1, max(1, w), 7)
        bar.itemconfig(ui["fill"], fill=color)

    @staticmethod
    def _color_for(percent, charging):
        if charging:
            return BLUE
        if percent >= 50:
            return GREEN
        if percent >= 20:
            return ORANGE
        return RED

    def _render_row(self, ui, data, show_estimate=False):
        if not data or data.get("percent") is None:
            if ui.get("_txt") != ("—", DIM):
                ui["value"].config(text="—", fg=DIM)
                ui["_txt"] = ("—", DIM)
            self._set_bar(ui, 0, DIM)
            return
        percent = int(data["percent"])
        charging = bool(data.get("charging") or data.get("plugged"))
        color = self._color_for(percent, charging)
        self._set_bar(ui, percent, color)

        if show_estimate and not charging:
            secs, measured = self._estimate_for(ui, percent,
                                                data.get("voltage_mv"))
            if secs is None:
                text, fg = "≈ …", DIM
            else:
                # Valeur mesuree : claire. Valeur nominale (repli) : estompee.
                text, fg = "≈" + _format_duration(secs), (FG if measured else DIM)
        else:
            text = f"{percent}%"
            if charging:
                text += "  ⚡"
            fg = color

        if ui.get("_txt") != (text, fg):
            ui["value"].config(text=text, fg=fg)
            ui["_txt"] = (text, fg)

    def _estimate_for(self, ui, percent, voltage):
        """Estimation courante -> (secondes, mesuree?) ou (None, False).

        Ordre : decharge mesuree, puis derniere decharge connue (mise a
        l'echelle du niveau actuel), puis autonomie nominale de secours.
        """
        key = ui["key"]
        secs = estimate_remaining(self.hist.get(key, []), percent, voltage)
        if secs is not None:
            self.last_est[key] = [secs, percent, time.time()]
            self._history_dirty = True
            return secs, True
        last = self.last_est.get(key)
        if last and len(last) >= 2 and last[1]:
            return last[0] * percent / last[1], True
        nominal = NOMINAL_HOURS.get(key)
        if nominal and percent:
            return nominal * 3600 * percent / 100, False
        return None, False

    def _update_display(self):
        with self._lock:
            kb = self.kb_value

        # On conserve la derniere valeur connue, meme si le peripherique
        # passe en veille : le niveau ne repasse pas a "—".
        mouse, _ts = self.mouse_reader.latest()

        self._maybe_relabel(self.kb_ui, self.kb_reader.label)
        self._maybe_relabel(self.mouse_ui, self.mouse_reader.label)
        self._render_row(self.kb_ui, kb, self._show_est)
        self._render_row(self.mouse_ui, mouse, self._show_est)
        return kb, mouse

    @staticmethod
    def _maybe_relabel(ui, label):
        if label and ui["name"].cget("text") != label:
            ui["name"].config(text=label)

    def _refresh(self):
        self._keep_on_desktop()
        kb, mouse = self._update_display()
        if kb is not None:
            self._record("kb", kb.get("percent"), bool(kb.get("plugged")),
                         kb.get("voltage_mv"))
        if mouse is not None:
            self._record("mouse", mouse.get("percent"),
                         bool(mouse.get("charging")), mouse.get("voltage_mv"))
        self._maybe_save_history()
        self.root.after(1000, self._refresh)

    def _keep_on_desktop(self):
        """Repose l'overlay au fond (au cas ou un clic l'aurait remonte)."""
        send_to_bottom(self.hwnd)

    def _record(self, key, percent, charging, voltage=None):
        """Met a jour l'historique de decharge d'un peripherique.

        Chaque point est ``[timestamp, pourcentage, tension_mv]``. La tension
        permet d'estimer l'autonomie avant meme que 1 % soit consomme.
        """
        if percent is None and voltage is None:
            return
        if percent is not None:
            percent = int(percent)
        hist = self.hist.setdefault(key, [])
        if charging:
            if hist:
                hist.clear()
                self._history_dirty = True
            return
        now = time.time()
        if hist:
            last = hist[-1]
            dt = now - last[0]
            same_pct = (percent == last[1])
            last_v = last[2] if len(last) > 2 else None
            v_moved = (voltage is not None and last_v is not None
                       and voltage != last_v)
            if same_pct and not v_moved and dt < 300:
                return
            if same_pct and v_moved and dt < 60:
                return
        hist.append([now, percent, voltage])
        cutoff = now - HISTORY_WINDOW
        self.hist[key] = [p for p in hist if p[0] >= cutoff]
        self._history_dirty = True

    def _maybe_save_history(self):
        now = time.time()
        if (self._history_dirty
                and now - self._last_history_save >= HISTORY_SAVE_INTERVAL):
            self.cfg["history"] = self.hist
            self.cfg["last_est"] = self.last_est
            save_config(self.cfg)
            self._history_dirty = False
            self._last_history_save = now

    def _poll_hover(self):
        """Affiche l'autonomie apres HOVER_SECONDS de survol du cadre."""
        inside = False
        try:
            px = self.root.winfo_pointerx()
            py = self.root.winfo_pointery()
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            inside = x <= px < x + w and y <= py < y + h
        except Exception:
            pass

        if inside:
            if self._hover_start is None:
                self._hover_start = time.time()
            if (not self._show_est
                    and time.time() - self._hover_start >= HOVER_SECONDS):
                self._show_est = True
                self._update_display()
        elif self._show_est or self._hover_start is not None:
            self._hover_start = None
            self._show_est = False
            self._update_display()
        self.root.after(200, self._poll_hover)

    # -- placement / deplacement ------------------------------------------
    def _place_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.container.winfo_reqwidth()
        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            x = sw - w - 24
            y = 24
        x = max(0, min(int(x), sw - 50))
        y = max(0, min(int(y), sh - 50))
        self._target_xy = (x, y)
        self.root.geometry(f"+{x}+{y}")
        # Au demarrage Windows, la fenetre se mappe apres coup et peut retomber
        # a (0,0) : on reapplique la position quelques instants apres.
        for delay in (10, 150, 500, 1200):
            self.root.after(delay, self._reapply_position)

    def _reapply_position(self):
        if self._user_moved or self._target_xy is None:
            return
        x, y = self._target_xy
        try:
            self.root.geometry(f"+{x}+{y}")
            self.root.update_idletasks()
        except Exception:
            pass

    def _bind_recursive(self, widget):
        widget.bind("<ButtonPress-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        widget.bind("<ButtonRelease-1>", self._drag_end)
        widget.bind("<Button-3>", self._show_menu)
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _drag_start(self, event):
        if self.locked:
            return
        self._user_moved = True
        self._dx = event.x_root - self.root.winfo_x()
        self._dy = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        if self.locked:
            return
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")

    def _drag_end(self, _event):
        if self.locked:
            return
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        save_config(self.cfg)

    # -- menu --------------------------------------------------------------
    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Reinitialiser la position",
                              command=self.reset_position)
        self.var_lock = tk.BooleanVar(value=self.locked)
        self.menu.add_checkbutton(label="Verrouiller la position",
                                  variable=self.var_lock,
                                  command=self._toggle_lock)
        self.var_auto = tk.BooleanVar(value=is_autostart_enabled())
        self.menu.add_checkbutton(label="Demarrer avec Windows",
                                  variable=self.var_auto,
                                  command=self._toggle_autostart)
        self.menu.add_separator()
        self.menu.add_command(label="Quitter", command=self.quit)

    def _show_menu(self, event):
        self.var_auto.set(is_autostart_enabled())
        self.var_lock.set(self.locked)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _toggle_lock(self):
        self.locked = bool(self.var_lock.get())
        self.cfg["locked"] = self.locked
        save_config(self.cfg)
        try:
            self.hint.config(text=self._hint_text())
        except Exception:
            pass

    def reset_position(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.container.winfo_reqwidth()
        x = sw - w - 24
        y = 24
        self.root.geometry(f"+{x}+{y}")
        self.cfg["x"] = x
        self.cfg["y"] = y
        save_config(self.cfg)

    def _toggle_autostart(self):
        if not set_autostart(self.var_auto.get()):
            self.var_auto.set(is_autostart_enabled())

    # -- threads -----------------------------------------------------------
    def _keyboard_loop(self):
        while True:
            try:
                result = self.kb_reader.read()
            except Exception:
                result = None
            if result is not None:
                with self._lock:
                    self.kb_value = result
            time.sleep(POLL_SECONDS)

    # -- fermeture ---------------------------------------------------------
    def quit(self):
        try:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
        except Exception:
            pass
        self.cfg["history"] = self.hist
        self.cfg["last_est"] = self.last_est
        save_config(self.cfg)
        try:
            self.mouse_reader.stop()
        except Exception:
            pass
        try:
            self.kb_reader.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Mode test (console)
# ---------------------------------------------------------------------------
def test_mode():
    print("Lecture batterie (Ctrl+C pour quitter)...")
    kb = LogitechKeyboardReader()
    mouse = VxeMouseReader()
    threading.Thread(target=mouse.run, daemon=True).start()
    try:
        while True:
            print("Clavier :", kb.read())
            m, ts = mouse.latest()
            print("Souris  :", m, f"(il y a {time.time() - ts:.0f}s)" if ts else "")
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        kb.close()
        mouse.stop()


def main():
    if "--test" in sys.argv:
        test_mode()
        return
    if "--install-autostart" in sys.argv:
        print("Demarrage auto:", "ok" if set_autostart(True) else "echec")
        return
    if "--remove-autostart" in sys.argv:
        print("Demarrage auto:", "ok" if set_autostart(False) else "echec")
        return
    Overlay().run()


if __name__ == "__main__":
    main()
