# ConstantesCab

Widget unique regroupant la prise des constantes du patient, dans une seule fenêtre
flottante style Doctolib :

- **Tension artérielle** — tensiomètre BLE type BP2 / Viatom / LePu (issu du projet `bp2pro`)
- **Poids** — balance Xiaomi Mi Scale (issu du projet `miscale`)
- **Température** — thermomètre Beurer FT95 (issu du projet `beurerFT95`)

La saturation (oxymètre Aicare) sera intégrée dans ce même widget ultérieurement.

## Fenêtre flottante

Une seule bande bleu Doctolib (`#004080`, contour `#345677`, bords arrondis), toujours au
premier plan, déplaçable à la souris :

```
🩺 ● [progression] 125/82  72 bpm  14:32 | ⚖ 75.2 kg  14:35 | 🌡 36.8 °C  14:40 | 80% 💾 ✕
```

- **Tension** : point de statut (vert = connecté), barre de progression en temps réel pendant
  le gonflage, dernière mesure sys/dia, fréquence cardiaque, heure, batterie du tensiomètre.
- **Poids** : dernier poids stabilisé et heure de la mesure.
- **Température** : dernière température (orange si ≥ 38 °C) et heure.
- 🩺 ouvre le panneau de configuration, 💾 enregistre la position, ✕ ferme.

Comme le widget tension d'origine, la fenêtre peut ne s'afficher **que si Doctolib est
ouvert et maximisé** (option dans l'onglet Affichage).

## Panneau de configuration

Un panneau commun, un onglet par appareil :

- **Tension (BP2)** : scan Bluetooth, sélection de l'appareil (reconnexion immédiate),
  injection automatique dans Doctolib (son, blocage clavier), reconnexion automatique
  et délais.
- **Poids (Mi Scale)** : scan, sélection de la balance (l'adresse MAC n'est plus codée
  en dur), statut en direct.
- **Température (FT95)** : scan, adresse optionnelle (détection automatique par défaut),
  temporisations du cycle (attente 1ʳᵉ valeur / réception du lot / thermomètre libre),
  copie presse-papiers, nombre de mesures historisées, statut en direct.
- **Affichage** : fenêtre flottante, affichage uniquement si Doctolib est ouvert,
  sauvegarde de la position.

## Fonctionnement des appareils

- **Tension** : connexion BLE persistante avec reconnexion automatique, progression de la
  pression en direct, résultat final détecté et (option) injecté dans Doctolib via le
  module `doctolib_injector` (optionnel, non inclus).
- **Poids** : superviseur persistant qui relaie le sous-processus de scan BLE de la
  balance ; chaque poids mesuré s'affiche immédiatement.
- **Température** : cycle connexion → réception du lot de mesures → affichage de la plus
  récente → copie presse-papiers → déconnexion pour libérer le thermomètre (~25 s) →
  nouveau cycle. Chaque cycle s'exécute dans un sous-processus Python neuf
  (contournement du bug bleak/WinRT). Historique persistant dans
  `Documents/ConstantesCab/mesures.csv` et `mesures.jsonl`.

## Installation (PC Windows)

Prérequis : Python 3.9+ et un adaptateur Bluetooth.

```bash
git clone https://github.com/pefdore/constantescab.git
cd constantescab
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Jumelez le FT95 dans les paramètres Bluetooth Windows (PIN affiché sur le thermomètre),
puis lancez `python app.py` et ouvrez le panneau 🩺 pour configurer chaque appareil.

Configuration et statuts sont stockés dans `Documents/ConstantesCab/`
(`config.json`, `status_bp2.json`, `status_scale.json`, `status_ft95.json`).

## Avertissement

Outil d'aide à la saisie : les valeurs affichées restent celles des appareils de mesure,
à intégrer dans votre logiciel métier comme toute donnée clinique. Aucun diagnostic
n'est réalisé par ce logiciel.
