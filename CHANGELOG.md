# EVCC-Smartload Changelog

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

### Was sich NICHT ändert

- Dashboard URL: `http://homeassistant:8099`
- Alle bestehenden API-Endpunkte
- Vehicle Providers (KIA, Renault, Custom, Manual, evcc)
- SVG-Chart, Energiebilanz, Decision Log
- RL Device Control pro Gerät
- Batterie→EV Entladung
- ManualSocStore, InfluxDB, Docker-Struktur

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
