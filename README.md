# EVCC-Smartload Add-on Repository

Home Assistant Add-on Repository für **EVCC-Smartload** — intelligentes Energiemanagement mit hybridem LP+RL Optimizer.

## Installation

1. Dieses Repository als Custom Add-on Repository in Home Assistant hinzufügen:

   **Einstellungen** → **Add-ons** → **Add-on Store** → **⋮** (oben rechts) → **Repositories**

   URL einfügen:
   ```
   https://github.com/Krinco1/HA_Addon_EVCC-Smartload
   ```

2. Add-on Store aktualisieren (Seite neu laden)

3. **EVCC-Smartload - Hybrid Optimizer** installieren

4. Konfiguration anpassen und starten

## Enthaltene Add-ons

| Add-on | Beschreibung | Version |
|---|---|---|
| [EVCC-Smartload](evcc-smartload/) | Hybrid LP+RL Optimizer für Batterie & EV-Ladung | 5.0.2 |

## Features

- **Percentil-Thresholds** — Batterie+EV laden in günstigsten P20/P30/P40-Fenstern
- **Hybrid LP+RL** — Linear Programming als Basis, Reinforcement Learning lernt dazu
- **Charge-Sequencer** — Koordiniert mehrere EVs an einer Wallbox mit Quiet Hours
- **Telegram-Notifications** — Fahrer werden direkt per Bot gefragt
- **Batterie→EV Entladung** — Entlädt Hausbatterie ins EV wenn Netzstrom teuer ist
- **Vehicle Providers** — KIA, Renault, evcc, Custom
- **Dashboard** — SVG-Preischart, Lade-Zeitplan, Decision-Log, RL-Reife

## Support

- Dashboard: `http://homeassistant.local:8099`
- GitHub: https://github.com/Krinco1/HA_Addon_EVCC-Smartload
