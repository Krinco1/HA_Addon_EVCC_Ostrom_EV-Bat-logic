# Changelog

## v4.3.9 (2026-02-15)

### 🐛 Solar-Berechnung, ORA-Duplikat, 0%-SoC Filter

**Solar-Surplus 54466 kWh → realistische Werte:**
- Root cause: Forecast-Einträge wurden ohne Slot-Dauer summiert (128 × Rohwert = Unsinn)
- Neue Helper-Funktion `calc_solar_surplus_kwh()` in state.py:
  - Berechnet Slot-Dauer aus Zeitstempeln (z.B. 15min oder 1h)
  - Auto-Erkennung W vs kW (Median > 100 → Watt)
  - Energie = kW × Stunden pro Slot
  - Sanity-Cap: max 100 kWh (realistisches 2-Tage-Maximum)
- Wird sowohl in main.py als auch server.py genutzt

**ORA_03/ora_03 Duplikat endgültig gefixt:**
- Dedup lief VOR Pre-Registrierung → wurde sofort wieder angelegt
- Fix: `dedup_case_duplicates()` läuft jetzt NACH Pre-Registration
- Reihenfolge: 1) Pre-Register aus vehicles.yaml 2) Dedup 3) Main-Loop

**0% SoC Filter für Battery→EV:**
- KIA meldet 0% über evcc-Fallback wenn API fehlschlägt
- 0% = "unbekannt", nicht "leer"
- Fahrzeuge mit 0% SoC werden aus der EV-Bedarf-Berechnung ausgeschlossen
  (es sei denn: am Wallbox angeschlossen ODER direct_api Quelle)
- Verhindert falsche "79 kWh EV-Bedarf" Berechnung

**EV-Bedarf > 100% gekappt:**
- ev_need_pct wird auf max 100% begrenzt (Hausbatterie kann nie mehr als 100% liefern)

---

## v4.3.8 (2026-02-15)

### 🔧 Batterie→EV Karte + ORA Duplikat-Fix

**Batterie→EV Karte immer sichtbar:**
- Karte verschwindet nicht mehr wenn kein Ladebedarf besteht
- Zeigt dann: "Alle Fahrzeuge geladen — kein Entladebedarf" + verfügbare kWh und Netzpreis
- Vorher: Karte wurde komplett ausgeblendet → User dachte Feature sei kaputt

**ORA_03/ora_03 Duplikat-Fix:**
- evcc liefert Fahrzeugnamen lowercase (`ora_03`), vehicles.yaml hat Großbuchstaben (`ORA_03`)
- Case-insensitive Matching in `_merge_evcc_data`: evcc-Daten werden auf den kanonischen Namen gemappt
- Case-insensitive Dedup bei RL-Device-Registrierung im Main-Loop
- Startup-Cleanup: `_dedup_case_duplicates()` entfernt bestehende Duplikate aus SQLite

---

## v4.3.7 (2026-02-15)

### 🎯 Dynamische Entladegrenze (bufferSoc/prioritySoc via evcc API)

**Dynamische Batterie-Entladegrenze:**
- Berechnet automatisch wie tief die Batterie fürs EV entladen werden darf
- Basiert auf Solar-Prognose, günstigen Strompreisen und EV-Bedarf
- Setzt `bufferSoc`, `bufferStartSoc` und `prioritySoc` via evcc API
- Beispiel: Viel Sonne erwartet → Batterie darf tief entladen (Solar füllt auf)
- Beispiel: Bewölkt + teure Preise → Batterie wird geschont

**Algorithmus:**
1. Solar-Refill: PV-Prognose minus Hausverbrauch → erwartete Aufladung in %
2. Netz-Refill: Günstige Stunden × Ladeleistung × Effizienz → erwartete Aufladung in %
3. Gesamt-Refill = Solar + Netz (max 80%, mit 80% Sicherheitsfaktor)
4. Entladegrenze = max(Untergrenze, Aktuell - Sicherheits-Entladung, Aktuell - EV-Bedarf)
5. `bufferSoc` = Entladegrenze (darüber: Batterie→EV erlaubt)
6. `prioritySoc` = Untergrenze - 5% (darunter: Batterie hat absoluten Vorrang)

**Dashboard-Visualisierung:**
- Batterie-Balken mit farbigen Zonen: Rot (Schutz), Gelb (Puffer), Grün (für EV)
- Aufschlüsselung: Solar-Refill, Günstig-Netz, EV-Bedarf, Untergrenze
- Aktualisiert sich alle 15 Minuten

**Neue evcc API-Methoden:**
- `set_buffer_soc(soc)` → bufferSoc setzen
- `set_buffer_start_soc(soc)` → bufferStartSoc setzen
- `set_priority_soc(soc)` → prioritySoc setzen
- `set_battery_boost(lp_id, enabled)` → Battery-Boost an/aus

**Neue Konfigurationsparameter:**
- `battery_to_ev_dynamic_limit`: true (dynamisch an/aus)
- `battery_to_ev_floor_soc`: 20 (absolute Untergrenze in %)

---

## v4.3.6 (2026-02-15)

### 🔋→🚗 Batterie-Entladung für EV + Solar-Linie + KIA-RL-Fix

**KIA fehlt in RL (endgültig gefixt):**
- Root cause: Fahrzeuge wurden nach `start_polling()` registriert, aber `get_all_vehicles()` war zu dem Zeitpunkt noch leer (2s async delay)
- Fix: Fahrzeugnamen direkt aus `vehicles.yaml` lesen → sofortige Registrierung, unabhängig vom Polling
- Zusätzlich: dynamische Nachregistrierung im Main-Loop für Fahrzeuge die erst via evcc erscheinen

**Solar-Prognose: SVG-Linie statt transparentes Overlay:**
- Gelbe Linie (2.5px) mit Punkten an jedem Datenpunkt
- Subtile gelbe Füllung unter der Linie
- Skala-Label ("☀ max 8.2kW") oben rechts
- Deutlich besser sichtbar als das alte rgba-Overlay

**🔋→🚗 Batterie-Entladung für EV-Laden:**
- Neue Sektion im Dashboard: zeigt ob Batterie-Entladung ins EV günstiger ist als Netzstrom
- Berechnung berücksichtigt:
  - Lade-Effizienz (default 92%) und Entlade-Effizienz (default 92%)
  - Roundtrip-Effizienz: 92% × 92% = 84.6%
  - Effektive Batterie-Kosten = Ladepreis / Roundtrip-Effizienz
  - Vergleich mit aktuellem Netzpreis und Ø der nächsten 6h
  - Mindest-Vorteil: 3ct/kWh (konfigurierbar)
- Controller aktiviert automatisch:
  - `batterymode: normal` (Entladung erlauben)
  - `batterydischargecontrol: true` (Batterie versorgt Wallbox)
  - `loadpoint/1/mode: now` (EV sofort laden)
- Deaktiviert automatisch wenn nicht mehr profitabel

**Neue evcc API-Methoden:**
- `set_battery_mode(mode)` → normal/hold/charge
- `set_battery_discharge_control(enabled)` → Entladung an/aus
- `set_loadpoint_mode(lp_id, mode)` → off/now/minpv/pv
- `set_loadpoint_minsoc(lp_id, soc)` → Min-SoC setzen
- `set_loadpoint_targetsoc(lp_id, soc)` → Ziel-SoC setzen

**Neue Konfigurationsparameter:**
- `battery_charge_efficiency`: 0.92 (AC→DC)
- `battery_discharge_efficiency`: 0.92 (DC→AC)
- `battery_to_ev_min_profit_ct`: 3.0 (Mindest-Vorteil in ct/kWh)

---

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
