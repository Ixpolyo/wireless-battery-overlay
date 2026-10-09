# Wireless Battery Overlay

Un petit widget Windows qui affiche le **niveau de batterie de votre clavier et
de votre souris sans fil** — sans logiciel constructeur.

Le widget vit **sur le bureau** : il reste au-dessus du fond d'écran mais
**derrière vos fenêtres**, il ne gêne donc jamais. Déplacez-le où vous voulez,
verrouillez-le, puis **survolez-le une seconde** pour voir l'autonomie estimée.

<!-- Ajoutez une capture d'écran ici, par exemple :
![capture d'écran](docs/screenshot.png)
-->

> 🇬🇧 **[Read in English](README.md)**

## Fonctionnalités

- **Claviers Logitech** via HID++ 2.0 (`0x1001 batteryVoltage`) ; le pourcentage
  est estimé à partir de la tension de la cellule.
- **Souris ATK / VXE / VGN** via le dongle 2,4 GHz (protocole HID actif).
- **Widget de bureau** : reste derrière vos fenêtres, position mémorisée.
- **Verrouillage de la position** une fois placé (clic droit → Verrouiller).
- **Autonomie estimée** au survol, d'après la vitesse de décharge observée.
- **Conserve la dernière valeur** connue quand un périphérique s'endort.
- **Démarrage avec Windows** (par utilisateur, sans droits administrateur).
- Une seule dépendance : [`hidapi`](https://pypi.org/project/hidapi/). Le reste
  est la bibliothèque standard de Python (Tkinter).

## Prérequis

- Windows 10 / 11
- Python 3.10+ (Tkinter est fourni avec l'installeur officiel Windows)
- `hidapi`

```bash
pip install -r requirements.txt
```

## Utilisation

Sans console :

```bash
pythonw battery_overlay.pyw
```

ou double-cliquez sur `start_overlay.bat`.

Mode diagnostic (affiche les mesures dans la console) :

```bash
python battery_overlay.pyw --test
```

## Commandes

| Action | Résultat |
|---|---|
| **Glisser** le widget | Le déplacer (position sauvegardée automatiquement) |
| **Survoler 1 s** | Remplace les pourcentages par l'autonomie estimée |
| **Clic droit** | Menu : réinitialiser la position, verrouiller, démarrer avec Windows, quitter |

## Démarrage avec Windows

Dans le menu (clic droit), cochez **« Démarrer avec Windows »**. Vous pouvez aussi
lancer :

```bat
install_autostart.bat    :: activer
remove_autostart.bat     :: désactiver
```

Cela écrit uniquement une valeur sous
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (aucun droit administrateur).

## Périphériques pris en charge

| Type | Périphériques | Méthode |
|---|---|---|
| Clavier | Logitech G915 et autres récepteurs Lightspeed / Bolt / Unifying | HID++ 2.0 (`0x1001`) |
| Souris | VXE R1 Pro Max, VXE R1 SE+, VGN F1 Pro, ATK F1 Ultimate, VXE MAD R, VXE MAD R Major Plus, ATK A9 Ultimate | Dongle 2,4 GHz, protocole HID actif |

Ajouter une souris se fait en général en une ligne dans le tableau `ATK_MICE`
de `battery_readers.py` (vendor id, product ids sans fil/filaire, nom affiché).
Le libellé du clavier est la constante `KEYBOARD_LABEL` du même fichier.

## Fonctionnement

- **Clavier** — la fonctionnalité HID++ 2.0 `0x1001` renvoie une tension en
  millivolts ; le pourcentage est interpolé sur une courbe de décharge Li-Po
  (ces claviers n'exposent pas de pourcentage direct).
- **Souris** — un protocole HID actif écrit un rapport de sortie de 17 octets
  `[0x08, 0x04, 0x00, …, 0x49]` et lit une réponse de 17 octets où
  `response[6]` est le pourcentage, `response[7]` l'indicateur filaire et
  `response[8:10]` la tension batterie en millivolts.
- L'**autonomie restante** est estimée à partir de la décharge observée sur les
  dernières heures. La tension (disponible pour les deux périphériques) offre un
  signal plus fin que le pourcentage entier, l'estimation apparaît donc bien
  plus tôt.

L'overlay lit les périphériques toutes les 10 secondes dans des threads
d'arrière-plan et ne redessine que lorsqu'une valeur change réellement.

## Fichiers

| Fichier | Rôle |
|---|---|
| `battery_overlay.pyw` | Interface (Tkinter), démarrage auto, configuration |
| `battery_readers.py` | Lecteurs HID (clavier Logitech, souris ATK/VXE/VGN) |
| `start_overlay.bat` | Lanceur sans console |
| `install_autostart.bat` / `remove_autostart.bat` | Activer / désactiver le démarrage avec Windows |
| `requirements.txt` | Dépendances |

La configuration d'exécution (position, verrouillage, historique de survol) est
stockée dans `%LOCALAPPDATA%\BatteryOverlay\config.json`.

## Crédits

- Protocole souris : [Fan4Metal/ATK_tray](https://github.com/Fan4Metal/ATK_tray).
- Référence du protocole souris passif : [incconutwo/mouse-battery-tray](https://github.com/incconutwo/mouse-battery-tray).
- Documentation Logitech HID++ : [openlogi.org](https://openlogi.org/hidpp/features/x1001-battery-voltage).

## Licence

[MIT](LICENSE).
