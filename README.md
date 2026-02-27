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
| [EVCC-Smartload](evcc-smartload/) | Predictiver LP+RL Optimizer für Batterie & EV-Ladung mit 24h Horizont | 6.1.0 |

## Features

- **HorizonPlanner (24h LP)** — Rolling-Horizon LP (scipy/HiGHS) optimiert Battery+EV gemeinsam über 96 Slots (15-Min)
- **evcc Lademodus-Steuerung** — SmartLoad setzt aktiv PV/Min+PV/Schnell mit Override-Detection
- **Battery Arbitrage** — LP-gated Batterie→EV Entladung mit 7-Gate Logik
- **Verbrauchsprognose** — Hour-of-day EMA aus InfluxDB-Historie, persistentes Modell, Echtzeit-Korrektur
- **PV-Prognose** — evcc Solar Tariff API, Rolling Correction [0.3–3.0], stündliche Aktualisierung
- **Vehicle SoC Polling** — Zuverlässige API-Provider (Kia, Renault) mit Backoff und evcc-Live-Suppression
- **Poll Now** — Manueller SoC-Abruf pro Fahrzeug im Dashboard
- **StateStore (Thread-safe)** — RLock-geschützter State, atomare Snapshots, SSE-Broadcast
- **SSE Live-Updates** — /events Endpoint, kein Polling, 30s Keepalive
- **Config Validation** — Startup-Prüfung, HTML-Fehlerseite bei kritischen Fehlern
- **Percentil-Thresholds** — Batterie+EV laden in günstigsten P20/P30/P40-Fenstern
- **Hybrid LP+RL** — Linear Programming als Basis, Reinforcement Learning lernt dazu
- **Charge-Sequencer** — Koordiniert mehrere EVs an einer Wallbox mit Quiet Hours
- **Telegram-Notifications** — Fahrer werden direkt per Bot gefragt
- **Vehicle Providers** — KIA, Renault, evcc, Custom
- **Dashboard** — 4 Tabs (Status, Plan/Gantt, Fahrzeuge, Lernen) mit SVG-Charts und Live-SSE-Updates

## Support

- Dashboard: `http://homeassistant.local:8099`
- GitHub: https://github.com/Krinco1/HA_Addon_EVCC-Smartload
