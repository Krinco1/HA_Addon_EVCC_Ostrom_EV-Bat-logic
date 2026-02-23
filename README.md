# EVCC-Smartload Add-on Repository

Home Assistant Add-on Repository für **EVCC-Smartload** — intelligentes Energiemanagement mit predictivem 24h LP-Planner, PV/Verbrauchs-Prognose und hybridem LP+RL Optimizer.

## Installation

1. Dieses Repository als Custom Add-on Repository in Home Assistant hinzufügen:

   **Einstellungen** → **Add-ons** → **Add-on Store** → **⋮** (oben rechts) → **Repositories**

   URL einfügen:
   ```
   https://github.com/Krinco1/HA_Addon_EVCC-Smartload
   ```

2. Add-on Store aktualisieren (Seite neu laden)

3. **EVCC-Smartload - Predictive LP Optimizer** installieren

4. Konfiguration anpassen und starten

## Enthaltene Add-ons

| Add-on | Beschreibung | Version |
|---|---|---|
| [EVCC-Smartload](evcc-smartload/) | Predictiver LP+RL Optimizer für Batterie & EV-Ladung mit 24h Horizont | 6.0.0 |

## Features

- **HorizonPlanner (24h LP)** — Rolling-Horizon LP (scipy/HiGHS) optimiert Battery+EV gemeinsam über 96 Slots (15-Min)
- **Verbrauchsprognose** — Hour-of-day EMA aus InfluxDB-Historie, persistentes Modell, Echtzeit-Korrektur
- **PV-Prognose** — evcc Solar Tariff API, Rolling Correction [0.3–3.0], stündliche Aktualisierung
- **StateStore (Thread-safe)** — RLock-geschützter State, atomare Snapshots, SSE-Broadcast
- **SSE Live-Updates** — /events Endpoint, kein Polling, 30s Keepalive
- **Config Validation** — Startup-Prüfung, HTML-Fehlerseite bei kritischen Fehlern
- **Percentil-Thresholds** — Batterie+EV laden in günstigsten P20/P30/P40-Fenstern
- **Hybrid LP+RL** — Linear Programming als Basis, Reinforcement Learning lernt dazu
- **Charge-Sequencer** — Koordiniert mehrere EVs an einer Wallbox mit Quiet Hours
- **Telegram-Notifications** — Fahrer werden direkt per Bot gefragt
- **Batterie→EV Entladung** — Entlädt Hausbatterie ins EV wenn Netzstrom teuer ist
- **Vehicle Providers** — KIA, Renault, evcc, Custom
- **Dashboard** — SVG-Preischart, 24h Forecast-Diagramm, Lade-Zeitplan, Decision-Log, RL-Reife
- **GET /forecast** — 96-Slot Prognose-API mit Confidence und Price-Zones

## Support

- Dashboard: `http://homeassistant.local:8099`
- GitHub: https://github.com/Krinco1/HA_Addon_EVCC-Smartload
