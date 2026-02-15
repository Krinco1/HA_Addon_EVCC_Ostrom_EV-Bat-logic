# Changelog

## v4.3.5 (2026-02-15)

### 🔧 RL: Alle Fahrzeuge tracken + Persistence Fix

**KIA fehlt in RL-Tabelle (Root Cause):**
- `compare_per_device()` trackte nur das Fahrzeug an der Wallbox (`state.ev_connected`)
- KIA_EV9 war nie angeschlossen → wurde nie verglichen → 0 Comparisons → unsichtbar
- Fix: Neue Methode `_eval_vehicle_charge_cost()` bewertet ALLE Fahrzeuge pro Loop-Iteration
- Jedes Fahrzeug aus `vehicle_monitor.get_all_vehicles()` wird jetzt verglichen
- Für nicht-angeschlossene EVs: theoretische Preisbewertung ("wäre jetzt gut zum Laden?")

**Win-Rate/Vergleiche Reset (Root Cause):**
- `device_comparisons` Dict war in-memory, wurde bei Neustart auf 0 zurückgesetzt
- Erste Comparison nach Restart schrieb `comparisons=1` in SQLite (SET, nicht INCREMENT)
- Fix (v4.3.4): Per-Device Stats werden in JSON persistiert und beim Start geladen
- Beim nächsten Neustart lädt der Comparator die korrekten Zähler

**Dynamische Registrierung (v4.3.4):**
- Fahrzeuge werden im Main-Loop registriert, nicht beim Start (wo vehicles noch leer ist)
- `time.sleep(3)` Hack entfernt, registriert automatisch sobald Vehicle-Daten verfügbar

---

## v4.3.4 (2026-02-15)

### 🐛 RL Device Registration & Persistence Fix

**KIA fehlt in RL-Tabelle:**
- Ursache: Registrierung lief VOR `vehicle_monitor.start_polling()` → `get_all_vehicles()` war leer
- Fix: Dynamische Registrierung im Main-Loop — jedes neue Fahrzeug wird automatisch registriert
- KIA_EV9 erscheint jetzt in der RL-Tabelle sobald es erstmals gepollt wird

**Win-Rate/Vergleiche resettet bei Neustart:**
- Ursache: `device_comparisons` und `device_wins` waren nur in-memory (defaultdict), nicht persistiert
- Nach jedem Neustart: Zähler bei 0 → erster Vergleich überschreibt SQLite mit `comparisons=1`
- Fix: Per-Device Stats werden jetzt in `comparator.save()` mitgespeichert und beim Start geladen
- Neue persistierte Felder: `device_comparisons`, `device_wins`, `device_costs_lp`, `device_costs_rl`

---

## v4.3.3 (2026-02-15)

### ☀️ Echte Solar-Prognose & Chart-Overlay

**Solar-Forecast von evcc:**
- Neuer API-Aufruf: `/api/tariff/solar` liefert stündliche PV-Prognose
- Wird automatisch genutzt wenn evcc Solar-Forecast konfiguriert hat
- Fallback auf Schätzung (60% × aktuell × Stunden) wenn kein Forecast vorhanden

**Chart: Solar-Overlay:**
- Gelbe halbtransparente Fläche zeigt PV-Prognose je Stunde
- Tooltip: "14:00: 28.5ct | ☀️ 4.2kW"
- Zusammenfassung: "☀️ Aktuell: 2.4 kW PV | 📈 Prognose: 18 kWh heute"
- Neue Legende: "☀️ Solar-Prognose"

**Ladeplanung mit echtem Forecast:**
- Slot-Berechnung nutzt echte PV-Prognose statt grober Schätzung
- Überschuss = Solar - Hausverbrauch pro Stunde (realistischer)
- `forecast_source: "evcc"` vs `"estimate"` in API sichtbar

---

## v4.3.2 (2026-02-15)

### 🕐 Timestamp-Fix & 📱 Mobile-First Dashboard

**Timestamp-Fix:**
- Zwei separate Zeitstempel: `last_poll` (wann System gepollt hat) vs `last_update` (wann Fahrzeug gemeldet hat)
- Dashboard zeigt jetzt "📡 gerade eben" nach erfolgreichem Poll statt falsches "vor 2h"
- Stale-Warning zeigt Quelle: "Letzte Fahrzeugmeldung: vor 2h 13min (evcc)"

**Mobile-First Dashboard:**
- Status-Karten: 2×2 Grid auf Mobile, 4-spaltig ab 600px
- Device-Header: vertikal gestapelt auf Mobile
- Chart: kleinere Bars/Labels auf Mobile, scrollbar
- Energiebilanz: 2-spaltig auf Mobile, auto-fit ab Tablet
- RL-Tabelle: horizontal scrollbar auf Mobile
- Touch-freundliche Buttons (größer auf Touch-Geräten)
- Kein horizontaler Overflow mehr

---

## v4.3.1 (2026-02-15)

### ☀️ PV-bewusste Ladeplanung & Energiebilanz

**PV-Integration in Ladeplanung:**
- Slot-Berechnung berücksichtigt jetzt PV-Prognose → Netto-Bedarf statt Brutto
- Konservative PV-Schätzung: 60% der aktuellen Leistung × verbleibende Sonnenstunden
- Dashboard zeigt "Netz-Bedarf" mit PV-Offset: "Brutto: 94 kWh, PV spart ~5 kWh"

**Neue Energiebilanz-Karte:**
- ☀️ PV-Erzeugung, 🏠 Hausverbrauch, 🔌 Netzbezug/-einspeisung, 🔋 Batterie-Leistung
- Echtzeit-Werte als übersichtliche Kacheln

**Strategie-Text erweitert:**
- Zeigt jetzt Hausverbrauch im Kontext: "PV: 3.8 kW → 1.7 kW Überschuss (Haus: 2.1 kW)"
- Grid/Battery Power jetzt in /status API

**KIA-Fix:**
- Ursache: `vehicles.yaml` wurde nie geladen weil `yaml`-Modul fehlte (v4.3.0 fix)
- Sobald `pyyaml` installiert ist, werden KIA-Bluelink-Credentials aus vehicles.yaml geladen
- Direct API überschreibt evcc's 0%-Fallback für nicht-angeschlossene Fahrzeuge

---

## v4.3.0 (2026-02-15)

### 🎯 Major Dashboard & RL Update

**7 Fixes:**
1. **YAML-Modul**: `py3-yaml` Alpine-Paket nicht verfügbar → `pyyaml` via pip installiert
2. **Manueller SoC sichtbar**: Manual SoC gewinnt jetzt immer über evcc SoC=0%; "✏️ manuell" Badge im Dashboard
3. **RL pro Gerät**: Tabelle mit Auto/LP/RL-Toggle pro Device im Dashboard
4. **Preis-Chart**: Balkendiagramm mit Strompreisen, Lade-Limits als gestrichelte Linien, PV-Anzeige
5. **Strategie-Text**: Verständliche Erklärung der aktuellen Lade-Strategie im Dashboard
6. **Alle Geräte registriert**: battery + alle Fahrzeuge werden beim Start für RL registriert (inkl. KIA)
7. **InfluxDB-Bootstrap**: Historische Daten fließen in Comparator-Reife ein (seed_from_bootstrap)

**Neue API-Endpoints:**
- `GET /strategy` – Aktuelle Lade-Strategie als Text
- `GET /chart-data` – Preisdaten für Chart-Visualisierung

---

## v4.2.1 (2026-02-15)

### 🐛 Bugfix: numpy ModuleNotFoundError

- Alpine-Paket `py3-numpy` nicht verfügbar in HA Base Image
- numpy, requests, aiohttp jetzt via `pip install` statt Alpine `apk`
- Zwei separate RUN-Layer: Core-Deps (numpy, requests, aiohttp) + optionale Vehicle-APIs

---

## v4.2.0 (2026-02-15)

### 🏠 HA Addon Guidelines Compliance

**config.yaml `map` korrigiert:**
- Alte Syntax `config:rw` durch neue List-Syntax ersetzt
- `addon_config` (read\_only: false) statt veraltetes `config` — Addon bekommt eigenes Config-Verzeichnis
- Pfad im Container bleibt `/config/`, aber auf dem Host liegt es unter `/addon_configs/{repo}_evcc_smartload/`
- User findet `vehicles.yaml` im HA File Editor unter dem Addon-Config-Ordner

**Pfad-Verifizierung nach HA Developer Docs:**
- `/data/` — persistenter Storage (State, RL-Modell, SoC) ✅
- `/data/options.json` — Addon-Optionen aus der UI ✅
- `/config/` — `addon_config` Mount für `vehicles.yaml` ✅

---

## v4.1.1 (2026-02-15)

### 📁 vehicles.yaml automatische Bereitstellung

- `vehicles.yaml.example` wird beim ersten Start automatisch nach `/config/vehicles.yaml` kopiert
- User findet die Datei sofort im HA File Editor — kein manuelles Kopieren nötig
- Dockerfile: `vehicles.yaml.example` wird ins Image aufgenommen
- Bugfix: `CHANGELOG_v4.0.0.md` Referenz in server.py korrigiert → `CHANGELOG.md`

---

## v4.1.0 (2026-02-15)

### 🔧 HA Addon Struktur & evcc-kompatible Fahrzeug-Config

**HA Addon Struktur korrigiert:**
- `build.yaml` hinzugefügt — Multi-Arch Base Images (aarch64, amd64, armv7)
- `services.d/` entfernt — bei `init: false` wird s6-overlay nicht genutzt
- `CMD` in Dockerfile ergänzt — ohne CMD startete der Container nicht
- Dockerfile: `COPY rootfs/app /app` statt `COPY rootfs /` (nur App-Code)
- `map: config:rw` in config.yaml — Zugriff auf HA Config-Verzeichnis
- Repo-level `README.md` hinzugefügt — nötig für HA Addon Store Anzeige

**Fahrzeug-Config evcc-kompatibel:**
- Neue `vehicles.yaml.example` im evcc-YAML-Format
- Vehicle-Config aus evcc.yaml 1:1 kopierbar nach `/config/vehicles.yaml`
- Automatisches Feld-Mapping: `name`→`evcc_name`, `template`→`type`, `capacity`→`capacity_kwh`
- Unbekannte evcc-Felder werden ignoriert — dieselbe YAML für beide Systeme
- `vehicle_providers` JSON-String aus config.yaml/Schema entfernt (war fehleranfällig)
- Vehicle-Credentials nicht mehr in Addon-UI, sondern in separater YAML-Datei

**Slug-Änderung:**
- `evcc_smartload` statt `evcc_smartload_v4` — kein Versionssuffix im Slug

---

## v4.0.0 (2026-02-08)

### 🏗️ Kompletter Architektur-Neuaufbau

**Breaking Changes:**
- Neuer Slug `evcc_smartload` — Add-on muss neu installiert werden
- Modulare Codebasis ersetzt monolithische `main.py`

**Neue Architektur:**
- `main.py` von 3716 auf ~120 Zeilen reduziert
- 20+ separate Module mit klarer Verantwortung
- HTML/JS komplett aus Python-Code entfernt
- JSON-API-First Dashboard mit Auto-Refresh

**Fixes:**
- ✅ Manueller SoC überlebt jetzt Neustarts (persistent in JSON)
- ✅ Dashboard-Refresh ohne Page-Reload
- ✅ Version nur noch in `version.py` (kein Hardcoding mehr)
- ✅ Keine HTML/JS in Python f-strings mehr (keine `{{`/`}}` Kollisionen)
- ✅ Thread-safe ManualSocStore mit Locking

**Features:**
- LP + Shadow RL Hybrid-Optimierung
- Pro-Device RL Control mit SQLite
- Multi-Fahrzeug-Support (KIA, Renault, Manual, Custom, evcc)
- InfluxDB-Integration mit RL-Bootstrap
- Vollständige REST-API mit 10+ Endpoints
