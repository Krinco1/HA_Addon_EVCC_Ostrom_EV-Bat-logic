# ⚡ EVCC-Smartload v4.3.7

**Intelligentes Energiemanagement für Home Assistant**

Optimiert Hausbatterie und Elektrofahrzeug-Ladung auf Basis dynamischer Strompreise, PV-Erzeugung und Verbrauchsprognosen. Nutzt einen Hybrid-Ansatz aus Linear Programming (LP) und Reinforcement Learning (RL).

---

## 🌟 Features

- **Holistische Optimierung** — Batterie, EV, PV und Hauslast werden gemeinsam betrachtet
- **Shadow RL** — Ein DQN-Agent lernt parallel zum LP-Optimizer und übernimmt automatisch wenn er besser ist
- **Pro-Device RL Control** — RL kann für jedes Gerät (Batterie, einzelne Fahrzeuge) individuell gesteuert werden
- **Multi-Fahrzeug-Support** — KIA Connect, Renault/Dacia API, manueller SoC-Input, evcc-Fallback
- **🔋→🚗 Batterie-Entladung für EV** — Automatische Profitabilitätsberechnung mit Lade-/Entladeverlusten
- **🎯 Dynamische Entladegrenzen** — bufferSoc/prioritySoc werden automatisch via evcc API angepasst
- **☀️ Solar-Prognose** — Echte PV-Forecast von evcc als SVG-Linie im Chart
- **📱 Mobile-First Dashboard** — Responsive Design für Smartphone, Tablet und Desktop
- **Persistenter manueller SoC** — Für Fahrzeuge ohne API (z.B. GWM ORA 03)
- **Modulare Architektur** — Sauber getrennte Module, einfach erweiterbar

---

## 📦 Installation

### Als Home Assistant Add-on

1. Repository hinzufügen:
   ```
   https://github.com/Krinco1/HA_Addon_EVCC-Smartload
   ```
2. Add-on **EVCC-Smartload** installieren
3. Konfiguration anpassen (siehe unten)
4. Add-on starten
5. Dashboard öffnen: `http://homeassistant:8099`

### Voraussetzungen

- **evcc** (Electric Vehicle Charge Controller) auf demselben Netzwerk
- **InfluxDB v1** (optional, für Historie und RL-Bootstrap)
- Dynamischer Stromtarif in evcc konfiguriert (z.B. Tibber, aWATTar)
- **Solar-Forecast** in evcc konfiguriert (optional, für PV-Prognose im Chart)

---

## ⚙️ Konfiguration

### Grundeinstellungen

| Option | Default | Beschreibung |
|--------|---------|--------------|
| `evcc_url` | `http://192.168.1.66:7070` | evcc-Adresse |
| `evcc_password` | *(leer)* | evcc-Passwort (falls gesetzt) |
| `battery_capacity_kwh` | `33.1` | Kapazität der Hausbatterie |
| `battery_max_price_ct` | `25.0` | Maximaler Ladepreis Batterie (ct/kWh) |
| `ev_max_price_ct` | `30.0` | Maximaler Ladepreis EV (ct/kWh) |
| `ev_target_soc` | `80` | Ziel-SoC für alle EVs (%) |
| `ev_charge_deadline_hour` | `6` | Deadline für EV-Ladung (Uhrzeit) |

### Batterie-Effizienz & EV-Entladung

| Option | Default | Beschreibung |
|--------|---------|--------------|
| `battery_charge_efficiency` | `0.92` | AC→DC Ladeeffizienz (0.0–1.0) |
| `battery_discharge_efficiency` | `0.92` | DC→AC Entladeeffizienz (0.0–1.0) |
| `battery_to_ev_min_profit_ct` | `3.0` | Mindest-Preisvorteil für Batterie→EV (ct/kWh) |
| `battery_to_ev_dynamic_limit` | `true` | Dynamische bufferSoc/prioritySoc Anpassung |
| `battery_to_ev_floor_soc` | `20` | Absolute Entlade-Untergrenze (%) |

**Roundtrip-Effizienz:** Bei 92% Lade- und 92% Entladeeffizienz ergibt sich eine Roundtrip-Effizienz von 84.6%. Strom der für 20ct/kWh geladen wurde kostet effektiv 23.6ct/kWh bei der Entladung.

### InfluxDB

| Option | Default | Beschreibung |
|--------|---------|--------------|
| `influxdb_host` | `192.168.1.67` | InfluxDB Host |
| `influxdb_port` | `8086` | InfluxDB Port |
| `influxdb_database` | `smartload` | Datenbank-Name |

### Reinforcement Learning

| Option | Default | Beschreibung |
|--------|---------|--------------|
| `rl_enabled` | `true` | Shadow RL aktivieren |
| `rl_auto_switch` | `true` | Automatisch zu RL wechseln wenn bereit |
| `rl_ready_threshold` | `0.8` | Win-Rate ab der RL „ready" ist |
| `rl_fallback_threshold` | `0.7` | Win-Rate unter der zurück zu LP gewechselt wird |
| `rl_ready_min_comparisons` | `200` | Mindest-Vergleiche vor Auto-Switch |

### Fahrzeug-Provider

Fahrzeuge werden über eine separate `vehicles.yaml` im Addon-Config-Verzeichnis konfiguriert.
Das Format ist **identisch zur evcc.yaml** — du kannst deine Fahrzeug-Einträge direkt kopieren.

Beim ersten Start wird automatisch eine Beispiel-Datei angelegt.

1. Im HA File Editor unter `addon_configs/xxx_evcc_smartload/` die `vehicles.yaml` öffnen
2. Einträge aus deiner `evcc.yaml` einfügen (auskommentieren)
3. Add-on neu starten

```yaml
vehicles:
  - name: KIA_EV9
    type: template
    template: kia
    title: KIA EV9
    user: email@example.com
    password: 'geheim'
    vin: KNXXXXXXX
    capacity: 99.8

  - name: my_Twingo
    type: template
    template: renault
    title: Renault Twingo Electric
    user: email@example.com
    password: 'geheim'
    capacity: 22

  # Smartload-spezifisch (kein evcc-Pendant):
  - name: ORA_03
    template: custom
    title: GWM ORA 03
    script: /config/scripts/ora_soc.py
    capacity: 63

  - name: ORA_03
    template: manual
    title: GWM ORA 03
    capacity: 63
```

**Feld-Mapping (automatisch):**

| evcc Feld | → Smartload intern | Beschreibung |
|-----------|-------------------|--------------|
| `name` | `evcc_name` | Fahrzeug-Referenz in evcc |
| `template` | `type` | Provider (kia, renault, custom, manual) |
| `capacity` | `capacity_kwh` | Batteriekapazität |

Unbekannte Felder (z.B. evcc's `language`, `mode`, `onIdentify`) werden ignoriert — dieselbe YAML funktioniert für beide Systeme.

**Unterstützte Templates:** `kia`, `hyundai`, `renault`, `dacia`, `custom`, `manual`, `evcc`

### Solar-Prognose (optional)

Für die PV-Forecast-Anzeige im Chart muss in deiner evcc-Konfiguration ein Solar-Forecast konfiguriert sein:

```yaml
# evcc.yaml
tariffs:
  grid:
    type: tibber
    token: ...
  solar:
    type: forecast.solar  # oder: solcast, etc.
    ...
```

Ohne Solar-Forecast nutzt Smartload eine Schätzung basierend auf aktueller PV-Leistung.

---

## 🖥️ Dashboard

Das Dashboard ist unter `http://homeassistant:8099` erreichbar und zeigt:

- **Aktueller Strompreis** mit Farbcodierung (grün < 25ct, orange < 35ct, rot ≥ 35ct)
- **Batterie-Status** mit SoC-Balken
- **PV-Leistung** und Hausverbrauch
- **📊 Strompreis-Chart** mit Solar-Prognose als gelbe SVG-Linie
- **⚡ Energiebilanz** — PV-Ist, Prognose, Forecast-Quelle
- **🔋→🚗 Batterie-Entladung** — Profitabilitätsberechnung mit dynamischen Grenzen
- **Ladeslots** pro Gerät mit Kosten-Kalkulation
- **🤖 RL-Reifegrad** — Fortschritt und Pro-Device Win-Rates
- **Manuelle SoC-Eingabe** für Fahrzeuge ohne API

Das Dashboard ist **responsive** (Mobile-First) und aktualisiert sich automatisch alle 60 Sekunden.

### Batterie→EV Visualisierung

Die Batterie-Entladung zeigt drei farbige Zonen:
- 🔴 **Rot** (0% → prioritySoc): Geschützt, keine Entladung
- 🟡 **Gelb** (prioritySoc → bufferSoc): Puffer, nur für Hausverbrauch
- 🟢 **Grün** (bufferSoc → 100%): Darf fürs EV genutzt werden

Die Grenzen werden dynamisch angepasst basierend auf Solar-Prognose, günstige Netzstunden und EV-Ladebedarf.

### Zwei Zeitstempel

Das Dashboard unterscheidet zwischen:
- **📡 Poll-Zeit** (wann unser System zuletzt geprüft hat) — prominent angezeigt
- **Daten-Alter** (wann das Fahrzeug zuletzt Daten gesendet hat) — in Stale-Warnungen

---

## 🔌 API Referenz

Basis-URL: `http://homeassistant:8099`

### GET Endpunkte

| Endpunkt | Beschreibung |
|----------|--------------|
| `/health` | Health-Check (`{"status": "ok", "version": "4.3.7"}`) |
| `/status` | Vollständiger System-Status inkl. RL-Metriken |
| `/vehicles` | Alle Fahrzeuge mit SoC, Datenquelle, manuellem Override |
| `/slots` | Detaillierte Ladeslots inkl. Batterie→EV Profitabilität |
| `/chart-data` | Preischart-Daten mit Solar-Prognose (kW pro Stunde) |
| `/rl-devices` | RL Device Control Status pro Gerät |
| `/config` | Aktuelle Konfiguration |
| `/summary` | Kurzübersicht für schnellen Check |
| `/comparisons` | Letzte 50 LP/RL-Vergleiche |
| `/strategy` | Aktuelle Strategie-Entscheidungen |

### POST Endpunkte

| Endpunkt | Body | Beschreibung |
|----------|------|--------------|
| `/vehicles/manual-soc` | `{"vehicle": "ORA_03", "soc": 45}` | Manuellen SoC setzen |
| `/vehicles/refresh` | `{"vehicle": "KIA_EV9"}` | Sofortigen Refresh auslösen |
| `/rl-override` | `{"device": "battery", "mode": "manual_lp"}` | RL-Mode Override (`manual_lp`, `manual_rl`, `auto`) |

### evcc API Integration

Smartload steuert folgende evcc-Parameter automatisch:

| evcc Endpunkt | Wann | Beschreibung |
|---------------|------|--------------|
| `POST /api/batterygridchargelimit/{eur}` | Jeder Loop | Batterie-Ladegrenze (Strompreis) |
| `POST /api/smartcostlimit/{eur}` | Jeder Loop | EV-Ladegrenze (Strompreis) |
| `POST /api/buffersoc/{soc}` | Bei Battery→EV | Ab welchem SoC Batterie EV unterstützt |
| `POST /api/bufferstartsoc/{soc}` | Bei Battery→EV | Ab welchem SoC EV-Laden starten darf |
| `POST /api/prioritysoc/{soc}` | Bei Battery→EV | Unter welchem SoC Batterie Vorrang hat |
| `POST /api/batterydischargecontrol/{bool}` | Bei Battery→EV | Batterie-Entladung an/aus |
| `POST /api/batterymode/{mode}` | Bei Bedarf | Batterie-Modus (normal/hold/charge) |
| `POST /api/loadpoints/{id}/mode/{mode}` | Bei Bedarf | Loadpoint-Modus (off/now/minpv/pv) |

---

## 🏗️ Architektur (v4.3.7)

```
rootfs/app/
├── main.py              # Startup + Main Loop + Battery→EV Orchestrierung
├── version.py           # Single source of truth für Version
├── config.py            # Konfiguration aus options.json + vehicles.yaml
├── logging_util.py      # Zentrales Logging
├── evcc_client.py       # evcc REST API Client (Tariffe, Battery, Loadpoint, Buffer)
├── influxdb_client.py   # InfluxDB Client
├── state.py             # SystemState, Action, VehicleStatus, ManualSocStore
├── controller.py        # Aktionen → evcc + dynamische Entladegrenzen
├── rl_agent.py          # DQN Agent + Replay Memory
├── comparator.py        # LP/RL Vergleich + RL Device Controller (SQLite)
├── vehicle_monitor.py   # VehicleMonitor + DataCollector
├── optimizer/
│   ├── holistic.py      # LP Optimizer
│   └── event_detector.py
├── vehicles/            # Modulares Provider-System
│   ├── base.py
│   ├── manager.py
│   ├── kia_provider.py
│   ├── renault_provider.py
│   ├── evcc_provider.py
│   └── custom_provider.py
└── web/
    ├── server.py        # HTTP Server + JSON API + Slot-Berechnung
    ├── template_engine.py
    ├── templates/
    │   └── dashboard.html  # Mobile-First Responsive Dashboard
    └── static/
        └── app.js       # Dashboard JS: Charts, Solar-Overlay, Battery→EV, RL-Tabelle
```

### Wichtige Design-Prinzipien

1. **HTML nie in Python f-strings** — Templates sind separate `.html`-Dateien
2. **Single Source of Truth** — `ManualSocStore` für manuelle SoC-Werte, `VehicleMonitor` für alle Fahrzeugdaten
3. **Version nur in `version.py`** — config.yaml referenziert nur für HA
4. **JSON-API First** — Dashboard lädt Daten via API, kein serverseitiges HTML-Rendering
5. **Thread-safe** — ManualSocStore nutzt Locks, alle Module sind thread-safe
6. **Per-Device Persistenz** — RL-Vergleiche und Win-Rates überleben Neustarts (JSON + SQLite)
7. **Dynamische evcc-Steuerung** — bufferSoc/prioritySoc werden basierend auf Forecasts gesetzt

---

## 🔋→🚗 Batterie-Entladung für EV

Smartload berechnet automatisch ob es sich lohnt, die Hausbatterie fürs EV zu entladen.

### Berechnung

```
Effektive Batterie-Kosten = Ladepreis ÷ Roundtrip-Effizienz
Beispiel: 20ct ÷ 0.846 = 23.6ct/kWh

Ersparnis = Netzpreis - Batterie-Kosten
Beispiel: 35ct - 23.6ct = 11.4ct/kWh → lohnt sich!
```

### Dynamische Entladegrenze

Statt einer fixen Grenze berechnet Smartload wie tief die Batterie sicher entladen werden darf:

1. **Solar-Refill**: PV-Prognose minus Hausverbrauch → erwartete Wiederaufladung
2. **Netz-Refill**: Günstige Stunden × Ladeleistung → zusätzliche Aufladung
3. **Sicherheit**: 80% der erwarteten Refill-Menge
4. **bufferSoc** = Aktueller SoC - sichere Entladung (min: floor_soc)

**Beispiel — Sonnig + günstige Nachtpreise:**
- Solar: +35% Refill, Netz: +15% → bufferSoc = 30% → 40% für EV frei

**Beispiel — Bewölkt + teuer:**
- Solar: +5%, Netz: 0% → bufferSoc = 66% → nur 4% für EV

---

## ❓ FAQ

**Q: Warum zeigt das Dashboard 0% für mein Fahrzeug?**
A: Prüfe ob ein Vehicle Provider konfiguriert ist. Ohne Provider sind Daten nur verfügbar wenn das Fahrzeug an der Wallbox hängt. Alternativ: Manuellen SoC eingeben.

**Q: Was passiert wenn evcc nicht erreichbar ist?**
A: Das Add-on wartet 60 Sekunden und versucht es erneut. Kein Datenverlust.

**Q: Wie sicher ist die RL-Steuerung?**
A: RL läuft im „Shadow Mode" — es beobachtet nur und lernt. Erst bei einer Win-Rate ≥ 80% über 200+ Vergleiche wird es automatisch aktiv. Du kannst das pro Gerät überschreiben.

**Q: GWM ORA hat keine API – was tun?**
A: Nutze den `manual` Provider und gib den SoC über das Dashboard ein. Der Wert wird persistent gespeichert und überlebt Neustarts.

**Q: Warum zeigt das Chart keine Solar-Linie?**
A: Du brauchst einen Solar-Forecast in deiner evcc-Konfiguration (z.B. `forecast.solar` oder `solcast`). Ohne Forecast nutzt Smartload eine Schätzung und zeigt keine Linie an.

**Q: Was bedeutet die Batterie→EV Karte?**
A: Sie zeigt ob es günstiger ist, die Hausbatterie ins EV zu entladen statt Netzstrom zu nutzen. Die Berechnung berücksichtigt Lade-/Entladeverluste und den aktuellen Strompreis.

**Q: Was ist bufferSoc und warum ändert es sich?**
A: `bufferSoc` ist ein evcc-Parameter der bestimmt, ab welchem SoC die Batterie EV-Laden unterstützen darf. Smartload setzt diesen Wert dynamisch basierend auf Solar-Prognose, günstige Strompreise und EV-Bedarf.

---

## 📜 Lizenz

MIT License – siehe [LICENSE](LICENSE)

## 🤝 Beitragen

Issues und Pull Requests sind willkommen auf [GitHub](https://github.com/Krinco1/HA_Addon_EVCC-Smartload).
