# EVCC-Smartload Changelog

---

## v6.1.0 — Vehicle Polling + evcc Lademodus-Steuerung + Batterie-Arbitrage

### Neue Features

**Vehicle SoC Polling (Phase 9)**
- KiaProvider: Persistent VehicleManager, Progressive Backoff (2h→24h Cap), RateLimitingError-Handling
- RenaultProvider: Persistent aiohttp Session + RenaultClient, 401 Retry, asyncio-Loop Reuse
- evcc-Live-Suppression: API-Poll wird übersprungen wenn Fahrzeug an Wallbox hängt (evcc liefert Live-SoC)
- Per-Vehicle `poll_interval_minutes` in vehicles.yaml überschreibt Global-Default
- `disabled: true` Flag in vehicles.yaml schließt Fahrzeug vom Polling aus
- Stale-Threshold auf 720min (12h) erhöht — 60min war zu aggressiv für API-Provider
- Telegram Bot Token Validation beim Start (getMe-Check)

**Poll Now Button & Fahrzeuge Tab (Phase 10)**
- Neuer Dashboard-Tab "Fahrzeuge" mit Vehicle Cards (SoC, Datenalter, Provider)
- "Poll Now" Button pro Fahrzeug für manuellen SoC-Abruf
- Server-seitiger Throttle: 5 Min Cooldown zwischen Polls pro Fahrzeug
- Freshness Aging: Visuelle Alterungsanzeige der SoC-Daten
- `GET /vehicles` erweitert: freshness, poll_age, data_age, last_poll, is_stale

**evcc Lademodus-Steuerung (Phase 11)**
- EvccModeController: SmartLoad setzt aktiv PV/Min+PV/Schnell je nach optimalem Plan
- Preis-Perzentil-Logik: p≤30 → "now", p30–p60 → "minpv", p>60 → "pv"
- Override-Detection: Manuelle evcc-Modus-Änderungen werden erkannt und respektiert
- Override-Lifecycle: Override gilt bis EV-Disconnect oder Ziel-SoC erreicht
- evcc-Unreachable-Detection: Warnung nach 30 Min ohne Verbindung
- Dashboard Banners: Override-Status und evcc-Erreichbarkeit
- Neuer Endpoint: `GET /mode-control`

**LP-Gated Battery Arbitrage (Phase 12)**
- Hausbatterie speist EV wenn wirtschaftlich sinnvoll (Grid-Preis > Batterie-Kosten + Marge)
- 7-Gate Logik: EV-Bedarf, LP-Autorisierung, Modus, Profitabilität, 6h-Lookahead, Floor-SoC, Mutual Exclusion
- Dynamischer Floor: max(battery_to_ev_floor_soc, DynamicBufferCalc)
- Dashboard Banner: "Batterie speist EV (spare X ct/kWh, Y kWh verfügbar)"
- 13 Unit Tests für alle Gates und Edge Cases

### Neue Konfigurationsfelder

```yaml
battery_charge_efficiency: 0.92        # Lade-Effizienz Hausbatterie
battery_discharge_efficiency: 0.92     # Entlade-Effizienz Hausbatterie
battery_to_ev_min_profit_ct: 3.0       # Min. Ersparnis für Batterie→EV (ct/kWh)
battery_to_ev_dynamic_limit: true      # Dynamisches Floor-SoC Limit
battery_to_ev_floor_soc: 20            # Min. Batterie-SoC für Batterie→EV (%)
vehicle_poll_interval_minutes: 60      # Globales Poll-Intervall (pro Fahrzeug überschreibbar)
```

### Neue API-Endpunkte

| Methode | Endpoint | Beschreibung |
|---|---|---|
| POST | `/vehicles/refresh` | Poll Now — sofortiger SoC-Abruf (5 Min Throttle) |
| GET | `/mode-control` | Lademodus-Status (Modus, Override, evcc-Erreichbarkeit) |

### 42 neue Unit Tests

- Vehicle Provider Backoff und Session-Handling
- Poll Throttle und Freshness Tracking
- Mode Controller Perzentil-Logik und Override-Lifecycle
- Battery Arbitrage 7-Gate Logik und Profitabilitätsberechnung

---

## v6.0.1 — Bugfix: RL-Learning State-Transition + Repo-Bereinigung

### Bugfix

**RL learn_from_correction() State-Parameter vertauscht**
- `learn_from_correction(state, action, reward, state)` übergab denselben State als State und Next-State
- Q-Learning konnte keine echten State-Übergänge lernen (Q[s,a] → Q[s',a'] war identisch)
- Fix: `learn_from_correction(last_state, action, reward, state)` — korrekte Transition

### Repo-Bereinigung

- Private IPs (192.168.1.x) durch generische Platzhalter ersetzt (evcc.local, influxdb.local)
- Default-Passwörter neutralisiert (leere Strings)
- `.planning/` Entwicklungsdokumentation aus öffentlichem Repo entfernt
- MIT-Lizenz hinzugefügt
- Duplizierte Dateien entfernt (Root-CHANGELOG, vehicles.yaml.example)
- DOCS.md aktualisiert: fehlende Endpoints `/forecast`, `/events`, Override-Endpoints ergänzt
- Translations (en/de) aktualisiert
- CI-Workflow entfernt (HA Supervisor baut lokal)
- Stale `claude/*` Remote-Branches gelöscht
- GitHub-Repository-Beschreibung gesetzt

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

## v5.0.2 — Bugfixes: ManualSocStore · InfluxDB SSL

### Bugfixes

**ManualSocStore.get() gab dict statt float zurück**
- `set()` speichert `{"soc": 80, "timestamp": "..."}`, aber `get()` gab das gesamte dict zurück
- Verursachte `TypeError: '>' not supported between instances of 'dict' and 'int'` in:
  - `vehicle_monitor.py:102` (predict_charge_need)
  - `comparator.py:194` (EV-SoC Vergleiche)
  - `web/server.py` (API-Responses)
  - `main.py:276` (Hauptschleife)
- Fix: `get()` extrahiert jetzt den `soc`-Wert als float
- Zusätzlich: `get_timestamp()` Methode für sauberen Timestamp-Zugriff
- Defensive Absicherung in `get_effective_soc()` gegen dict-Typ

**InfluxDB SSL-Support**
- InfluxDB-Client war hardcoded auf `http://` — bei aktiviertem SSL im InfluxDB-Addon kam HTTP 401
- Neue Config-Option `influxdb_ssl: true/false` (Default: false)
- SSL-Kontext akzeptiert selbstsignierte Zertifikate (lokales Netzwerk)
- Protokoll-Erkennung beim Start geloggt

### Geänderte Dateien
- `rootfs/app/state.py` — ManualSocStore.get() + get_timestamp() + defensive get_effective_soc()
- `rootfs/app/influxdb_client.py` — SSL-Support mit konfigurierbarem Protokoll
- `rootfs/app/config.py` — neues Feld `influxdb_ssl: bool`
- `config.yaml` — Option `influxdb_ssl` + Schema-Eintrag
- `rootfs/app/version.py` — 5.0.2

### Neue Konfigurationsfelder
```yaml
influxdb_ssl: true   # Default: false — auf true setzen wenn InfluxDB SSL aktiviert hat
```

### Rückwärtskompatibilität
- `influxdb_ssl` Default ist `false` → bestehende HTTP-Setups unverändert
- ManualSocStore-Fix ist transparent — bestehende JSON-Daten werden korrekt gelesen

---

## v5.0.1 — Bugfixes: Module · SystemState · InfluxDB · DriverManager

### Fixed
- **`No module named 'yaml'`** — `pyyaml` zu pip-Dependencies im Dockerfile hinzugefügt
- **`SystemState() missing 'ev_power'`** — Pflichtfeld im DataCollector-Konstruktor ergänzt (`ev_power=0.0`)
- **`InfluxDBClient has no attribute 'get_history_hours'`** — Methode `get_history_hours()` in `influxdb_client.py` implementiert
- **`DriverManager.to_api_list()`** — Methode fehlte, wird von `web/server.py` unter `/drivers` aufgerufen

---

## v5.0.0 — Percentil-Optimierung · Charge-Sequencer · Telegram

### Neue Features

**Percentil-basierte Preis-Thresholds (LP + RL)**
- Batterie und EVs laden nicht mehr gegen statische ct-Schwellen, sondern gegen dynamische Marktperzentile
- LP-Optimizer berechnet P20/P40/P60/P80 aus den nächsten 24h und wählt Aggressivität je nach Solar-Prognose, SoC und Saison
- RL-Agent bekommt 6 neue State-Features: P20, P60, Spread, günstige Stunden, Solar-Forecast, Saisonindex
- State Space: 25 → 31 Features · Action Space: 7×5 = 35 Aktionen (war 4×4 = 16)
- P30-Linie im Dashboard-Chart (cyan gestrichelt) zeigt günstigstes 30%-Fenster

**Charge-Sequencer (EV-Lade-Koordination)**
- Plant optimale Lade-Reihenfolge für mehrere EVs an einer Wallbox
- Quiet Hours: Kein EV-Wechsel zwischen 21:00–06:00 (konfigurierbar)
- Pre-Quiet-Hour-Empfehlung: 90 Minuten vorher wird empfohlen, welches EV angesteckt werden soll
- Dashboard zeigt Lade-Zeitplan mit Stunden, kWh, Preisen und Quelle (Solar/Günstig/Normal)
- Neuer API-Endpoint: `GET /sequencer`, `POST /sequencer/request`, `POST /sequencer/cancel`

**Telegram-Notifications (direkt, kein HA-Umweg)**
- Smartload → Telegram Bot API → Fahrer (kein HA Webhook/Automation nötig)
- Long-Polling Thread für Antworten (Inline-Keyboard: 80% / 100% / Nein)
- Fahrer bestätigt Ziel-SoC per Button → Sequencer plant automatisch
- Konfiguration über neue `drivers.yaml` (analog zu `vehicles.yaml`)
- Notification bei: Preisfenster öffnet, Ladung fertig, Umsteck-Empfehlung

**Driver Manager (drivers.yaml)**
- Neue optionale Konfigurationsdatei `/config/drivers.yaml`
- Fahrer ↔ Fahrzeug-Zuordnung + Telegram Chat-IDs
- Beim ersten Start wird `drivers.yaml.example` angelegt
- Neuer API-Endpoint: `GET /drivers`

### Geänderte Konfigurationsfelder
Neue optionale Felder in `config.yaml` (Defaults = Bestandsverhalten):
```yaml
quiet_hours_enabled: true   # Standard: true
quiet_hours_start: 21       # Ab wann kein EV-Wechsel
quiet_hours_end: 6          # Bis wann kein EV-Wechsel
```

### Rückwärtskompatibilität
- Alle bestehenden `config.yaml`-Felder bleiben unverändert
- `vehicles.yaml` Format bleibt identisch
- `drivers.yaml` ist optional — ohne Datei läuft alles wie bisher
- Ohne Telegram-Token: keine Notifications, EV mit statischen Limits (wie v4)
- RL Q-Table Reset notwendig (State Space ändert sich) — RL lernt in ~2 Tagen vom LP neu

---

## v4.3.11 — SVG-Chart Redesign · Dashboard-Verbesserungen
- SVG-Preischart vollständig neu (Y-Achse, Gitter, Solar-Fläche, Tooltip)
- Batterie-Entladetiefe mit dynamischem bufferSoc via evcc API
- Energiebilanz mit Echtzeit-Werten (PV, Haus, Netz, Batterie)
- Decision-Log mit Kategorien (observe, plan, action, warning, rl)

## v4.3.x — Batterie→EV Entladung · Dynamic Discharge
- evcc bufferSoc/prioritySoc/bufferStartSoc dynamisch berechnet
- Solar-Prognose-Integration für Entladetiefenberechnung
- Case-insensitive Fahrzeug-Matching korrigiert
- RL Pro-Device Control (Batterie + EVs einzeln steuerbar)

## v4.0.0 — Hybrid LP+RL
- Dualer Optimierungsansatz: Linear Programming + Reinforcement Learning
- Comparator: automatischer LP↔RL Switch nach Leistungsmetriken
- Neue Dashboard-Panels: RL-Reife, Vergleiche, Entscheidungs-Log
