# EVCC-Smartload v6.0 — Predictiver LP+RL Optimizer

**Intelligentes Energiemanagement für Home Assistant** — optimiert Hausbatterie und EV-Ladung anhand dynamischer Strompreise, 24h LP-Prognose, Solar- und Verbrauchsvorhersagen sowie Fahrer-Präferenzen.

## Features

| Feature | Details |
|---|---|
| **24h LP-Planner** | Rolling-Horizon LP (scipy/HiGHS) optimiert Battery+EV gemeinsam über 96 Slots (15-Min) |
| **Verbrauchsprognose** | Hour-of-day EMA aus InfluxDB-Historie, persistentes Modell, Echtzeit-Korrektur |
| **PV-Prognose** | evcc Solar Tariff API, Rolling Correction [0.3–3.0], stündliche Aktualisierung |
| **StateStore** | Thread-safe RLock, atomare Snapshots, SSE-Broadcast |
| **SSE Live-Updates** | /events Endpoint, kein Polling, 30s Keepalive |
| **Config Validation** | Startup-Prüfung, HTML-Fehlerseite bei kritischen Fehlern |
| **Percentil-Thresholds** | Batterie+EV laden in günstigsten P20/P30/P40-Fenstern statt statischer ct-Grenze |
| **Hybrid LP+RL** | Linear Programming als Basis, Reinforcement Learning lernt dazu (7×5=35 Aktionen) |
| **Charge-Sequencer** | Koordiniert mehrere EVs an einer Wallbox mit Quiet Hours (21–06 Uhr) |
| **Telegram-Notifications** | Fahrer werden direkt gefragt: "Auf wieviel % laden?" → Inline-Buttons |
| **Batterie→EV Entladung** | Entlädt Hausbatterie ins EV wenn Netzstrom teuer ist |
| **Solar-Integration** | PV-Prognose beeinflusst Lade-Aggressivität und Entladetiefe |
| **Vehicle Providers** | KIA (ccapi), Renault (renault-api), evcc, Manual, Custom |
| **Dashboard** | SVG-Preischart mit P30-Linie, 24h Forecast-Diagramm, Lade-Zeitplan, Decision-Log, RL-Reife |

## Installation

1. Repository als Custom Add-on in Home Assistant hinzufügen:
   `Einstellungen → Add-ons → Add-on Store → ⋮ → Custom repositories`
   URL: `https://github.com/Krinco1/HA_Addon_EVCC-Smartload`

2. Add-on installieren und starten

3. Dashboard öffnen: `http://homeassistant:8099`

## Konfiguration

### config.yaml (Add-on Optionen)

```yaml
evcc_url: "http://evcc.local:7070"
battery_capacity_kwh: 33.1
battery_charge_power_kw: 5.0             # Max Ladeleistung Batterie in kW
battery_min_soc: 10                      # Min SoC in % (LP-Untergrenze)
battery_max_soc: 90                      # Max SoC in % (LP-Obergrenze)
battery_max_price_ct: 25.0              # Hard-Ceiling — kein Laden teurer als das
feed_in_tariff_ct: 7.0                   # Einspeisevergütung ct/kWh
ev_max_price_ct: 30.0
ev_default_energy_kwh: 60              # Default EV-Kapazität wenn unbekannt
quiet_hours_enabled: true               # Kein EV-Wechsel nachts
quiet_hours_start: 21
quiet_hours_end: 6
sequencer_enabled: true                 # Charge Sequencer aktiv
sequencer_default_charge_power_kw: 11.0 # Default Ladeleistung EV
rl_bootstrap_max_records: 1000         # Max Records für RL Bootstrap
```

### vehicles.yaml (Fahrzeug-APIs)

Wird beim ersten Start unter `/config/vehicles.yaml` angelegt (Beispieldatei):

```yaml
vehicles:
  - name: KIA_EV9
    type: kia
    username: "..."
    password: "..."
    capacity_kwh: 99.8

  - name: my_Twingo
    type: evcc           # SoC direkt von evcc
    capacity_kwh: 22
```

### drivers.yaml (optional)

Für Telegram-Notifications unter `/config/drivers.yaml`:

```yaml
# Bot erstellen: @BotFather in Telegram → /newbot
telegram_bot_token: "123456:ABC-DEF..."

drivers:
  - name: "Nico"
    vehicles: ["KIA_EV9"]
    telegram_chat_id: 123456789    # /start im Bot, dann getUpdates

  - name: "Fahrer2"
    vehicles: ["ora_03", "my_Twingo"]
    telegram_chat_id: 987654321
```

**Ohne `drivers.yaml`**: System läuft vollständig ohne Notifications — EV-Ladung mit statischen Limits wie in v4.

## API-Endpunkte

| Methode | Endpoint | Beschreibung |
|---|---|---|
| GET | `/` | Dashboard (HTML) |
| GET | `/health` | Heartbeat — `{"status":"ok","version":"6.0.0"}` |
| GET | `/status` | Vollständiger System-Status inkl. Percentile, RL-Reife |
| GET | `/summary` | Kompakte Übersicht für externe Integrationen |
| GET | `/config` | Aktive Konfiguration (read-only) |
| GET | `/vehicles` | Alle Fahrzeuge mit SoC, Alter, Verbindungsstatus |
| GET | `/chart-data` | Preischart-Daten inkl. P30-Linie und Solar-Forecast |
| GET | `/slots` | Aktuelle Preis-Slots der nächsten 24h |
| GET | `/forecast` | **v6.0** 96-Slot Verbrauchs- und PV-Prognose mit Confidence |
| GET | `/events` | **v6.0** SSE-Stream für Live-Updates (Server-Sent Events) |
| GET | `/sequencer` | **v5.0** Lade-Zeitplan + offene Anfragen + Quiet Hours |
| GET | `/drivers` | **v5.0** Fahrer-Status (kein Telegram-Token/Chat-ID) |
| GET | `/decisions` | Letzte 40 Entscheidungen aus dem Decision-Log |
| GET | `/comparisons` | LP-vs-RL Vergleichsstatistiken der letzten 50 Runs |
| GET | `/strategy` | Aktuelle Strategie-Erklärung (Batterie + EV) |
| GET | `/rl-devices` | RL-Modus und Lern-Fortschritt pro Gerät |
| GET | `/docs` | Eingebaute Dokumentation (HTML) |
| GET | `/docs/api` | API-Referenz (HTML) |
| POST | `/vehicles/manual-soc` | Manuellen SoC setzen `{"vehicle":"KIA_EV9","soc":45}` |
| POST | `/vehicles/refresh` | Sofortigen API-Poll für ein Fahrzeug auslösen |
| POST | `/sequencer/request` | **v5.0** Lade-Anfrage stellen `{"vehicle":"...","target_soc":80}` |
| POST | `/sequencer/cancel` | **v5.0** Lade-Anfrage abbrechen `{"vehicle":"..."}` |
| POST | `/rl-override` | RL-Modus für ein Gerät überschreiben |

## v6.0 Architektur

```
Strompreise (24h)  ──┐
Verbrauchsprognose ──┤
PV-Prognose       ──┼──→ HorizonPlanner (LP/HiGHS)
Batterie-SoC      ──┤         ↓
EV-SoC + Deadline ──┘    PlanHorizon (96 Slots)
                              ↓
                    ┌─── Slot 0 Entscheidung ───┐
                    ↓                           ↓
              Batterie-Aktion            EV-Aktion
              (charge/discharge/hold)    (charge/off)
                    ↓                           ↓
              Controller ──→ evcc API ──→ Wallbox/Batterie
                    ↓
              StateStore ──→ SSE /events ──→ Dashboard
```

Der HorizonPlanner löst jeden 15-Min-Zyklus ein 96-Slot LP (MPC-Ansatz): Nur die Slot-0-Entscheidung wird angewendet; im nächsten Zyklus wird das LP mit dem tatsächlichen SoC neu gelöst. Der HolisticOptimizer ist automatischer Fallback bei LP-Fehler.

Der StateStore ist der RLock-geschützte Single Source of Truth. Der Web-Server greift ausschließlich über `snapshot()` lesend zu — keine Race Conditions möglich.

Der ConsumptionForecaster verwendet EMA aus InfluxDB-Historie (Tiered: 7d@15min, 8–30d@hourly). Der PVForecaster liest stündlich die evcc Solar Tariff API mit Rolling Correction Coefficient.

## Wichtige Hinweise

- **HorizonPlanner ist primärer Optimizer (LP)**; HolisticOptimizer nur automatischer Fallback bei LP-Fehler
- **StateStore garantiert Thread-Safety** — kein Race Condition möglich (RLock, read-only Web-Server via snapshot())
- **Forecaster brauchen 24h Daten** bevor sie bereit sind (is_ready Gate) — davor läuft LP ohne Prognose
- **RL Q-Table Reset bei v5.0**: State Space ändert sich (25→31 Features). RL lernt innerhalb ~2 Tagen vom LP neu
- **Quiet Hours**: Zwischen 21:00–06:00 kein automatisches EV-Umstecken. Wer hängt, lädt
- **Telegram**: Direkte Bot API, kein HA Automation/Webhook nötig
- **drivers.yaml optional**: Ohne Datei volles Bestandsverhalten

## Fahrzeug-Datenstand

| Fahrzeug | Provider | SoC-Verfügbarkeit |
|---|---|---|
| KIA EV9 (99.8 kWh) | kia (ccapi) | Jederzeit |
| Renault Twingo (22 kWh) | renault-api | Jederzeit |
| ORA 03 (63 kWh) | evcc | Nur wenn verbunden |

## Support & Updates

Dashboard: `http://homeassistant:8099`
Docs: `http://homeassistant:8099/docs`
GitHub: https://github.com/Krinco1/HA_Addon_EVCC-Smartload
