# EVCC-Smartload Changelog

---

## v6.0.0 — Predictiver LP-Planner + PV/Verbrauchs-Prognose + Config-Validierung

### Neue Features

**HorizonPlanner (LP-basierter 24h Optimizer)**
- Rolling-Horizon Linear Programming mit scipy/HiGHS
- 96-Slot (15-Min) Joint Battery+EV Dispatch — Batterie und EV werden gemeinsam optimiert
- Ersetzt statische Euro-Preislimits durch dynamische planbasierte Optimierung
- MPC-Ansatz: nur Slot-0-Entscheidung wird angewendet, LP wird jeden Zyklus neu gelöst
- HolisticOptimizer bleibt als automatischer Fallback bei LP-Fehler aktiv

**ConsumptionForecaster**
- Hour-of-day Rolling-Average (EMA) aus InfluxDB-Historie
- Tiered Bootstrap: 7d@15min + 8-30d@hourly
- Persistentes JSON-Modell unter /data/
- Correction Factor [0.5–1.5] für Echtzeit-Anpassung

**PVForecaster**
- PV-Ertragsprognose via evcc Solar Tariff API (/api/tariff/solar)
- Rolling Correction Coefficient [0.3–3.0] mit Daytime-Guard
- Stündliche Aktualisierung
- Confidence 0.0–1.0 basierend auf Datenabdeckung

**StateStore (Thread-Safe State Management)**
- RLock-geschützter Single Source of Truth
- Atomare Snapshots für Web-Server (read-only)
- SSE-Broadcast nach jedem Update (außerhalb des Locks)

**SSE Endpoint /events**
- Server-Sent Events für Live-Dashboard-Updates ohne Polling
- ThreadedHTTPServer mit Daemon-Threads
- 30s Keepalive

**Config Validation**
- ConfigValidator prüft alle Felder beim Start
- Kritische Fehler blockieren Start mit HTML-Fehlerseite auf Port 8099
- Nicht-kritische Warnungen setzen sichere Defaults

**GET /forecast Endpoint**
- 96-Slot Verbrauchs- und PV-Prognose mit Confidence, Correction-Label, Quality-Label, Price-Zones

### Architektur-Änderungen

- Web-Server ist jetzt strikt read-only (alle Reads via StateStore.snapshot())
- Main Loop schreibt über store.update() — kein direkter State-Zugriff mehr
- HorizonPlanner als primärer Optimizer, HolisticOptimizer als Fallback bei LP-Fehler
- Forecaster-Package (forecaster/) mit ConsumptionForecaster und PVForecaster
- ThreadedHTTPServer ersetzt einfachen HTTPServer (SSE-Kompatibilität)

### Neue Konfigurationsfelder

```yaml
battery_charge_power_kw: 5.0             # Max Ladeleistung Batterie in kW
battery_min_soc: 10                      # Min SoC in % (LP-Untergrenze)
battery_max_soc: 90                      # Max SoC in % (LP-Obergrenze)
feed_in_tariff_ct: 7.0                   # Einspeisevergütung ct/kWh
ev_default_energy_kwh: 60               # Default EV-Kapazität wenn unbekannt
sequencer_enabled: true                  # Charge Sequencer aktiv
sequencer_default_charge_power_kw: 11.0 # Default Ladeleistung EV
rl_bootstrap_max_records: 1000          # Max Records für RL Bootstrap
```

### CI/CD

- GitHub Actions Workflow für Multi-Arch Dockerfile Build-Test
- home-assistant/builder@2025.09.0 mit --test Flag
- HA Supervisor baut lokal aus Dockerfile (Standard-Add-on-Modell)

### Rückwärtskompatibilität

- Bestehende config.yaml-Felder bleiben kompatibel
- HolisticOptimizer bleibt als automatischer Fallback aktiv
- Alle v5 API-Endpoints unverändert

---

## v5.2.0 — Verbrauchs- und PV-Prognose (Data Foundation)

- ConsumptionForecaster: Hausverbrauch aus InfluxDB-Historie mit EMA-Modell
- PVForecaster: PV-Ertrag via evcc Solar Tariff API
- Forecaster in Main Loop integriert (15-Min Updates, stündliche PV-Aktualisierung)
- StateStore um Forecast-Felder erweitert (consumption_forecast, pv_forecast, pv_confidence, etc.)
- Dashboard: 24h Forecast-Diagramm mit SSE-Live-Updates

---

## v5.1.0 — Thread-Safe StateStore + Config Validation + Vehicle Reliability

- StateStore: Thread-safe RLock-geschützter State mit atomaren Snapshots
- SSE Push: /events Endpoint für Live-Dashboard-Updates
- ConfigValidator: Startup-Validierung mit kritisch/nicht-kritisch Klassifizierung
- HTML-Fehlerseite bei kritischen Config-Fehlern (vor Main Loop Start)
- Vehicle SoC Refresh bei Wallbox-Verbindung (Connection-Event-basiert)
- Charge Sequencer SoC-Sync im Decision Loop (sofortige Übergabe)
- RL Bootstrap mit Record-Cap (rl_bootstrap_max_records) und Progress-Logging
- RL Bootstrap Price-Field Fix (korrekte ct->EUR Konversion)

---

## v5.0.2 — Bugfixes: ManualSocStore · InfluxDB SSL · Repo-Struktur

### Repository-Umstrukturierung (HA Add-on konform)
- Doppelte `config.yaml`/`build.yaml`/`rootfs/` im Root entfernt — Supervisor findet jetzt nur noch ein Add-on
- `repository.json` → `repository.yaml` (HA Best Practice)
- `DOCS.md` hinzugefügt (HA UI Dokumentation-Tab)
- `translations/en.yaml` + `translations/de.yaml` hinzugefügt (UI-Labels)
- `webui` Feld in `config.yaml` hinzugefügt (HA Sidebar-Button)
- Schema-Validierung verbessert (`url`, `port`, Wertebereiche)

### Bugfixes

**ManualSocStore.get() gab dict statt float zurück**
- `set()` speichert `{"soc": 80, "timestamp": "..."}`, aber `get()` gab das gesamte dict zurück
- Verursachte `TypeError: '>' not supported between instances of 'dict' and 'int'`
- Fix: `get()` extrahiert jetzt den `soc`-Wert als float
- Zusätzlich: `get_timestamp()` Methode für sauberen Timestamp-Zugriff

**InfluxDB SSL-Support**
- Neue Config-Option `influxdb_ssl: true/false` (Default: false)
- SSL-Kontext akzeptiert selbstsignierte Zertifikate (lokales Netzwerk)

### Rückwärtskompatibilität
- `influxdb_ssl` Default ist `false` → bestehende HTTP-Setups unverändert
- ManualSocStore-Fix ist transparent — bestehende JSON-Daten werden korrekt gelesen

---

## v5.0.1 — Bugfixes: Module · SystemState · InfluxDB · DriverManager

### Fixed
- **`No module named 'yaml'`** — `pyyaml` zu pip-Dependencies im Dockerfile hinzugefügt
- **`SystemState() missing 'ev_power'`** — Pflichtfeld im DataCollector-Konstruktor ergänzt
- **`InfluxDBClient has no attribute 'get_history_hours'`** — Methode implementiert
- **`DriverManager.to_api_list()`** — Methode fehlte

---

## v5.0.0 — Percentil-Optimierung · Charge-Sequencer · Telegram

### Neue Features
- **Percentil-basierte Preis-Thresholds** (P20/P40/P60/P80)
- **Charge-Sequencer** für Multi-EV Koordination
- **Telegram-Notifications** (direkte Bot API)
- **Driver Manager** (drivers.yaml)
- **Quiet Hours** (kein EV-Wechsel nachts)

---

## v4.3.11 — SVG-Chart Redesign · Dashboard-Verbesserungen

## v4.3.x — Batterie→EV Entladung · Dynamic Discharge

## v4.0.0 — Hybrid LP+RL
