# Wireless Battery Overlay

A tiny Windows desktop widget showing the **battery level of your wireless
keyboard and mouse** — no vendor software required.

The widget lives **on the desktop**: it stays above the wallpaper but **behind
your open windows**, so it never gets in your way. Drag it anywhere, lock it in
place, and **hover it for one second** to see the estimated remaining runtime.

<!-- Add a screenshot here, e.g.:
![screenshot](docs/screenshot.png)
-->

> 🇫🇷 **[Lire en français](README.fr.md)**

## Features

- **Logitech keyboards** over HID++ 2.0 (`0x1001 batteryVoltage`); the
  percentage is estimated from the cell voltage.
- **ATK / VXE / VGN mice** over the 2.4 GHz dongle (active HID protocol).
- **Desktop widget**: stays behind your windows, position is remembered.
- **Lock the position** once it is where you want it (right-click → Lock).
- **Estimated runtime** on hover, based on the observed discharge rate.
- **Keeps the last known value** when a device goes to sleep.
- **Start with Windows** (per-user, no admin rights).
- Single dependency: [`hidapi`](https://pypi.org/project/hidapi/). Everything
  else is the Python standard library (Tkinter).

## Requirements

- Windows 10 / 11
- Python 3.10+ (Tkinter is bundled with the official Windows installer)
- `hidapi`

```bash
pip install -r requirements.txt
```

## Usage

Run without a console:

```bash
pythonw battery_overlay.pyw
```

or double-click `start_overlay.bat`.

Diagnostic mode (prints readings to the console):

```bash
python battery_overlay.pyw --test
```

## Controls

| Action | Result |
|---|---|
| **Drag** the widget | Move it (position is saved automatically) |
| **Hover 1 s** | Replace the percentages with the estimated remaining runtime |
| **Right-click** | Menu: reset position, lock position, start with Windows, quit |

## Start with Windows

From the right-click menu, tick **"Start with Windows"**. You can also run:

```bat
install_autostart.bat    :: enable
remove_autostart.bat     :: disable
```

This only writes a value under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (no administrator rights).

## Supported devices

| Kind | Devices | How |
|---|---|---|
| Keyboard | Logitech G915 and other Lightspeed / Bolt / Unifying receivers | HID++ 2.0 (`0x1001`) |
| Mouse | VXE R1 Pro Max, VXE R1 SE+, VGN F1 Pro, ATK F1 Ultimate, VXE MAD R, VXE MAD R Major Plus, ATK A9 Ultimate | 2.4 GHz dongle, active HID protocol |

Adding a new mouse is usually a one-line change in the `ATK_MICE` table in
`battery_readers.py` (vendor id, wireless/wired product ids, display name). The
keyboard label is the `KEYBOARD_LABEL` constant in the same file.

## How it works

- **Keyboard** — the HID++ 2.0 feature `0x1001` returns a voltage in millivolts;
  the percentage is interpolated on a Li-Po discharge curve (these keyboards do
  not expose a direct percentage).
- **Mouse** — an active HID protocol writes a 17-byte output report
  `[0x08, 0x04, 0x00, …, 0x49]` and reads a 17-byte reply where `response[6]` is
  the battery percentage, `response[7]` the wired flag and `response[8:10]` the
  battery voltage in millivolts.
- The **remaining runtime** is estimated from the discharge observed over the
  last few hours. The voltage (available for both devices) gives a finer signal
  than the integer percentage, so the estimate appears much sooner.

The overlay reads the devices every 10 seconds in background threads and only
repaints when a value actually changes.

## Files

| File | Purpose |
|---|---|
| `battery_overlay.pyw` | UI (Tkinter), auto-start, configuration |
| `battery_readers.py` | HID readers (Logitech keyboard, ATK/VXE/VGN mouse) |
| `start_overlay.bat` | Launcher without a console |
| `install_autostart.bat` / `remove_autostart.bat` | Enable / disable start with Windows |
| `requirements.txt` | Dependencies |

Runtime configuration (position, lock state, hover history) is stored in
`%LOCALAPPDATA%\BatteryOverlay\config.json`.

## Credits

- Mouse protocol: [Fan4Metal/ATK_tray](https://github.com/Fan4Metal/ATK_tray).
- Passive mouse protocol reference: [incconutwo/mouse-battery-tray](https://github.com/incconutwo/mouse-battery-tray).
- Logitech HID++ documentation: [openlogi.org](https://openlogi.org/hidpp/features/x1001-battery-voltage).

## License

[MIT](LICENSE).
