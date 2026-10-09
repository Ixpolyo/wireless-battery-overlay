# -*- coding: utf-8 -*-
"""Lecteurs de batterie pour peripheriques sans fil.

Deux familles de peripheriques sont gerees :

- Clavier Logitech (recepteur USB) : protocole HID++ 2.0, fonctionnalite
  ``0x1001 batteryVoltage``. Elle renvoie une tension en millivolts ; le
  pourcentage est estime via une courbe Li-Po (le pourcentage direct n'est pas
  expose par ce modele).

- Souris ATK / VXE / VGN (dongle 2,4 GHz) : protocole HID actif. On ecrit un
  rapport de sortie de 17 octets puis on lit la reponse (voir VxeMouseReader).

Aucune dependance en dehors de ``hidapi`` (module ``hid``).
"""
from __future__ import annotations

import os
import struct
import time

import hid

# Intervalle entre deux lectures d'un peripherique (secondes).
POLL_SECONDS = 10

# ---------------------------------------------------------------------------
# Clavier Logitech (HID++)
# ---------------------------------------------------------------------------
LOGITECH_VID = 0x046D
# Recepteurs "gaming" / unify susceptibles d'exposer batteryVoltage.
LOGITECH_PIDS = (
    0xC33E,  # G915
    0xC539,  # Lightspeed
    0xC545,
    0xC547,  # Bolt
    0xC52B, 0xC532, 0xC534,  # Unifying
)
BATTERY_VOLTAGE_FEATURE = 0x1001

# Nom affiche par defaut pour un clavier Logitech (les recepteurs generiques
# renvoient "USB Receiver" et n'exposent pas le nom du clavier).
KEYBOARD_LABEL = "Logitech G915"

# Courbe tension -> pourcentage pour une cellule Li-Po (estimation).
_VOLT_CURVE = [
    (4180, 100), (4100, 95), (4050, 90), (4000, 82), (3960, 75),
    (3920, 68), (3880, 60), (3850, 54), (3820, 48), (3790, 42),
    (3760, 36), (3730, 31), (3700, 26), (3670, 21), (3640, 17),
    (3610, 13), (3580, 10), (3550, 7), (3520, 5), (3480, 3), (3400, 0),
]


def battery_percent_from_mv(mv):
    """Estime un pourcentage a partir d'une tension en millivolts."""
    if mv is None:
        return None
    if mv >= _VOLT_CURVE[0][0]:
        return 100
    if mv <= _VOLT_CURVE[-1][0]:
        return 0
    for (v1, p1), (v2, p2) in zip(_VOLT_CURVE, _VOLT_CURVE[1:]):
        if v2 <= mv <= v1:
            return round(p2 + (mv - v2) * (p1 - p2) / (v1 - v2))
    return None


def _short_logitech_name(product_name):
    """Raccourcit un nom produit Logitech, ex. 'Logitech G915'.

    Les recepteurs generiques renvoient "USB Receiver" et n'exposent pas le
    nom du clavier : on retombe alors sur KEYBOARD_LABEL.
    """
    if not product_name:
        return KEYBOARD_LABEL
    name = str(product_name).strip()
    low = name.lower()
    if any(k in low for k in ("keyboard", "clavier")):
        token = next((p for p in name.split() if any(c.isdigit() for c in p)),
                     None)
        return f"Logitech {token}" if token else KEYBOARD_LABEL
    if len(name) <= 3 or any(k in low for k in ("receiver", "usb", "logitech")):
        return KEYBOARD_LABEL
    return f"Logitech {name}" if len(name) <= 20 else KEYBOARD_LABEL


class LogitechKeyboardReader:
    """Lit la tension de batterie d'un clavier Logitech via HID++ 2.0."""

    def __init__(self, device_index=1):
        self.device_index = device_index
        self._dev = None
        self._feature = None
        self.product_name = None

    @property
    def label(self):
        """Nom court a afficher dans l'overlay."""
        return _short_logitech_name(self.product_name)

    # -- connexion ---------------------------------------------------------
    def _find_path(self):
        fallback = None
        for pid in LOGITECH_PIDS:
            for d in hid.enumerate(LOGITECH_VID, pid):
                if d.get("usage_page") != 0xFF00:
                    continue
                if d.get("product_string"):
                    self.product_name = d["product_string"]
                if d.get("usage") == 0x2:          # interface des rapports longs
                    return d["path"]
                if fallback is None:
                    fallback = d["path"]
        return fallback

    def _ensure(self):
        if self._dev is not None:
            return True
        path = self._find_path()
        if not path:
            return False
        try:
            dev = hid.device()
            dev.open_path(path)
            dev.set_nonblocking(1)
        except OSError:
            return False
        self._dev = dev
        self._feature = None
        return True

    def close(self):
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None
        self._feature = None

    # -- protocole ---------------------------------------------------------
    def _drain(self):
        for _ in range(20):
            try:
                if not self._dev.read(64, 10):
                    return True
            except OSError:
                return False
        return True

    def _call(self, feature, function, params=b"", timeout=0.6):
        # Dans le protocole de ce recepteur : octet = (function << 4) | swid
        b3 = (function & 0x0F) << 4
        msg = bytearray(20)
        msg[0] = 0x11                       # rapport long
        msg[1] = self.device_index
        msg[2] = feature
        msg[3] = b3
        msg[4:4 + len(params)] = params
        if not self._drain():
            return None
        try:
            self._dev.write(bytes(msg))
        except OSError:
            return None
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = self._dev.read(64, 200)
            except OSError:
                return None
            if not r:
                continue
            if (len(r) >= 7 and r[1] == self.device_index
                    and r[2] == feature and r[3] == b3):
                return list(r)
        return None

    def _feature_index(self):
        if self._feature:
            return self._feature
        r = self._call(0x00, 0x00, struct.pack(">H", BATTERY_VOLTAGE_FEATURE))
        if not r or r[4] == 0:
            return None
        self._feature = r[4]
        return self._feature

    def read(self):
        """Renvoie un dict {percent, voltage_mv, plugged, flags} ou None."""
        if not self._ensure():
            return None
        feature = self._feature_index()
        if feature is None:
            return None
        r = self._call(feature, 0x00)
        if not r:
            self.close()
            return None
        mv = (r[4] << 8) | r[5]
        flags = r[6]
        return {
            "percent": battery_percent_from_mv(mv),
            "voltage_mv": mv,
            "plugged": bool(flags & 0x80),
            "flags": flags,
        }


# ---------------------------------------------------------------------------
# Souris ATK / VXE / VGN (dongle 2,4 GHz)
# ---------------------------------------------------------------------------
# Protocole actif (dit "protocole 1", MCU Nordic). On ecrit un rapport de
# sortie de 17 octets :
#     [0x08, 0x04, 0, ..., 0x49]      (report id 8, commande 4, marqueur 0x49)
# puis on lit la reponse de 17 octets :
#     res[6] = niveau de batterie (%),  res[7] = 1 si branchee en filaire.
#
# Reference : projet Fan4Metal/ATK_tray (models.py, get_battery_1).
ATK_MICE = (
    # (vendor_id, pid_sans_fil, pid_filaire, nom)
    (0x3554, 0xF58A, 0xF58C, "VXE R1 Pro Max"),
    (0x3554, 0xF58E, 0xF58F, "VXE R1 SE+"),
    (0x3554, 0xF503, 0xF502, "VGN F1 Pro"),
    (0x373B, 0x1031, 0x102E, "ATK F1 Ultimate"),
    (0x373B, 0x104D, 0x103F, "VXE MAD R"),
    (0x373B, 0x1040, 0x104C, "VXE MAD R Major Plus"),
    (0x373B, 0x11D9, 0x11B6, "ATK A9 Ultimate"),
)
ATK_VIDS = {vid for vid, _w, _p, _n in ATK_MICE}
ATK_INTERFACE = (0xFF02, 0x0002)   # (usage_page, usage) de l'interface utile


def _short_mouse_name(product_name):
    """Raccourcit un nom produit de dongle, ex. 'VXE NordicMouse 1K'."""
    if not product_name:
        return None
    name = str(product_name)
    for word in ("Dongle", "dongle", "Receiver", "receiver"):
        name = name.replace(word, "")
    name = name.strip()
    return name or None


class VxeMouseReader:
    """Lit la batterie d'une souris ATK/VXE/VGN via le protocole HID actif."""

    def __init__(self):
        self._dev = None
        self._path = None
        self._stop = False
        self._latest = None
        self._last_time = 0.0
        self._debug = bool(os.environ.get("BATT_DEBUG"))
        self.model = None

    @property
    def label(self):
        """Nom court a afficher dans l'overlay."""
        return self.model or "Souris"

    # -- connexion ---------------------------------------------------------
    def _find_path(self):
        up, us = ATK_INTERFACE
        fallback = None
        for d in hid.enumerate():
            if d.get("usage_page") != up or d.get("usage") != us:
                continue
            pair = (d.get("vendor_id"), d.get("product_id"))
            for vid, wpid, ppid, name in ATK_MICE:
                if pair == (vid, wpid) or pair == (vid, ppid):
                    self.model = name
                    return d["path"]
            if d.get("vendor_id") in ATK_VIDS and fallback is None:
                fallback = d["path"]
                if not self.model:
                    self.model = _short_mouse_name(d.get("product_string"))
        return fallback

    def _ensure(self):
        if self._dev is not None:
            return True
        path = self._find_path()
        if not path:
            return False
        try:
            dev = hid.device()
            dev.open_path(path)
            dev.set_nonblocking(1)
        except OSError:
            return False
        self._dev = dev
        self._path = path
        return True

    def close(self):
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None
        self._path = None

    # -- protocole ---------------------------------------------------------
    def _read_protocol1(self):
        report = [0] * 17
        report[0] = 0x08        # report id
        report[1] = 0x04        # commande batterie
        report[16] = 0x49       # marqueur de fin
        self._dev.write(report)
        for _ in range(10):
            time.sleep(0.02)
            res = self._dev.read(17)
            if not res:
                continue
            res = list(res)
            if self._debug:
                print("VXE <<", " ".join(f"{x:02x}" for x in res))
            if len(res) >= 8 and res[0] == 0x08:
                battery = res[6]
                if 0 <= battery <= 100:
                    wired = bool(res[7])
                    result = {
                        "percent": battery,
                        "charging": wired,
                        "wired": wired,
                    }
                    # Octets 8-9 : tension batterie en millivolts (ex. 0x0FC2
                    # = 4034 mV). Utile pour estimer l'autonomie avec une
                    # resolution plus fine que le pourcentage entier.
                    if len(res) >= 10:
                        mv = (res[8] << 8) | res[9]
                        if 2500 <= mv <= 4400:
                            result["voltage_mv"] = mv
                    return result
        return None

    def read(self):
        """Renvoie un dict {percent, charging, wired} ou None."""
        if not self._ensure():
            return None
        try:
            return self._read_protocol1()
        except OSError:
            self.close()
            return None

    # -- boucle (compatibilite avec l'overlay) ----------------------------
    def run(self):
        """Boucle bloquante a lancer dans un thread."""
        while not self._stop:
            result = self.read()
            if result is not None:
                self._latest = result
                self._last_time = time.time()
            time.sleep(POLL_SECONDS)

    def stop(self):
        self._stop = True

    def latest(self):
        return self._latest, self._last_time
