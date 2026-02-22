# EVCC-Smartload Changelog

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
