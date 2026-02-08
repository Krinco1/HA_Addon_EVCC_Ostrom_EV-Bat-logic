# EVCC-Smartload v3.0.5 - Intelligent Energy Management System

<div align="center">

**🔋 KI-gestützte Optimierung für Heimspeicher & Elektrofahrzeuge**

[![Version](https://img.shields.io/badge/version-3.0.5-blue.svg)](https://github.com/Krinco1/HA_Addon_EVCC-Smartload)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Addon-blue.svg)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## 📖 Inhaltsverzeichnis

1. [Überblick](#-überblick)
2. [Wie funktioniert EVCC-Smartload?](#-wie-funktioniert-evcc-smartload)
3. [LP vs RL](#-lp-vs-rl---der-unterschied)
4. [Features](#-features)
5. [Installation](#-installation)
6. [Konfiguration](#-konfiguration)
7. [Fahrzeug-System](#-modulares-fahrzeug-system)
8. [Dashboard](#-dashboard--monitoring)
9. [API](#-api-dokumentation)
10. [FAQ](#-faq)

---

## 🎯 Überblick

EVCC-Smartload optimiert **Heimspeicher und E-Fahrzeuge** basierend auf dynamischen Strompreisen.

**Hybrid-Ansatz:**
- **LP (Linear Programming)**: Mathematisch optimal, sofort einsatzbereit
- **RL (Reinforcement Learning)**: Lernt aus Erfahrung, wird kontinuierlich besser

### Warum EVCC-Smartload?

✨ **Sicher**: RL läuft zunächst im "Shadow Mode"  
📊 **Transparent**: Detaillierter LP vs RL Vergleich  
🚗 **Multi-Vehicle**: Mehrere Fahrzeuge gleichzeitig  
🔋 **Pro-Device RL**: Jedes Gerät hat eigenen Agent  
⚡ **Auto-Switch**: Automatischer Wechsel zu RL wenn besser  

---

## 🧠 Wie funktioniert EVCC-Smartload?

### Das Problem

- Dynamische Strompreise (Tibber, aWATTar)
- Auto soll **günstig** laden
- Heimspeicher **optimal** nutzen
- **Automatisch** beste Zeitfenster finden

### Die Lösung

```
┌────────────────────────────────────────────────┐
│  🔵 LP OPTIMIZER    vs    🟢 RL AGENT          │
│  ═══════════════          ════════             │
│                                                │
│  ✓ Steuert jetzt          ○ Lernt parallel    │
│  ✓ Mathematisch           ○ Wird schlauer     │
│  ✓ Erklärbar              ○ Erkennt Muster    │
└────────────────────────────────────────────────┘
```

**3 Phasen:**

1. **LP in Produktion** (Woche 1-2): LP steuert, RL lernt
2. **RL Training** (Woche 2-4): 200-1000 Entscheidungen sammeln
3. **RL Ready** (ab Woche 4+): Auto-Switch zu RL

---

## 🔬 LP vs RL - Der Unterschied

### LP (Linear Programming)

**Funktionsweise:**
```python
if preis < 25ct AND batterie < 90%:
    laden()
```

**Stärken:**
- ✅ Sofort optimal
- ✅ Deterministisch
- ✅ Erklärbar

**Schwächen:**
- ❌ Statisch
- ❌ Keine Adaptation
- ❌ Kurzsichtig

### RL (Reinforcement Learning)

**Funktionsweise:**
- Probiert Aktionen aus
- Bekommt Feedback (Reward)
- Merkt sich was funktioniert
- Wird mit der Zeit besser

**Was wird gelernt:**
1. **Zeitliche Muster**: "Freitags 20-22 Uhr niedrig"
2. **Saisonale Anpassung**: Winter vs Sommer
3. **Verhaltens-Muster**: Wochenende vs Werktag
4. **Optimale Strategie**: "85% reicht oft"

**Stärken:**
- ✅ Lernfähig
- ✅ Adaptiv
- ✅ Vorausschauend

**Schwächen:**
- ❌ Braucht Training
- ❌ Black Box
- ❌ Risiko

---

## ✨ Features

### 🎯 Kern
- 🔋 Batterie-Optimierung
- 🚗 Multi-Vehicle Support
- 📊 Dynamic Pricing
- ☀️ PV-Integration

### 🤖 KI
- 🎓 Imitation Learning
- 📈 Continuous Learning
- 🎯 Event Detection
- 🔄 Pro-Device RL

### 📱 Monitoring
- 📊 Live Dashboard
- 📈 Win-Rate Tracking
- 🔀 Manual Override
- 💰 Cost Tracking

---

## 📦 Installation

### Voraussetzungen
- Home Assistant
- evcc
- InfluxDB
- Dynamischer Tarif

### Schritte

1. Repository hinzufügen
2. EVCC-Smartload installieren
3. Konfigurieren
4. Starten
5. Dashboard: `http://homeassistant:8099`

---

## ⚙️ Konfiguration

### Basis
```yaml
evcc_url: "http://192.168.1.66:7070"
influxdb_host: "192.168.1.67"
influxdb_database: "evcc-smartload"
```

### Batterie
```yaml
battery_capacity_kwh: 33.1
battery_max_price_ct: 25.0
battery_min_soc: 10
battery_max_soc: 90
```

### EV
```yaml
ev_max_price_ct: 30.0
ev_target_soc: 80
ev_charge_deadline_hour: 6
```

### RL
```yaml
rl_enabled: true
rl_ready_threshold: 0.8        # 80% Win-Rate
rl_ready_min_comparisons: 200  # Min 200 Vergleiche
rl_auto_switch: true           # Auto zu RL
```

---

## 🚗 Modulares Fahrzeug-System

### Unterstützte Fahrzeuge

| Hersteller | Provider | Status |
|------------|----------|--------|
| KIA | `kia` | ✅ |
| Renault | `renault` | ✅ |
| Custom | `custom` | ✅ |

### Konfiguration
```yaml
vehicle_providers: |
  [
    {
      "evcc_name": "KIA_EV9",
      "type": "kia",
      "user": "email@example.com",
      "password": "secret",
      "capacity_kwh": 99.8,
      "rl_mode": "auto"
    }
  ]
```

### RL Modi
- `auto`: Automatisch LP→RL
- `lp`: Immer LP
- `rl`: Immer RL
- `manual_lp/rl`: User-Override

---

## 📊 Dashboard & Monitoring

Dashboard-URL: `http://homeassistant:8099`

### Anzeigen
1. **Status-Header**: Batterie, EV, Preis, PV, Verbrauch
2. **Ladeplanung**: Detaillierte Slots pro Gerät
3. **RL-Steuerung**: Toggle pro Gerät, Win-Rate, Ersparnis
4. **Konfiguration**: Übersicht

### RL-Steuerung
```
🔋 Hausbatterie
   [🔵 LP] ⟷ Toggle ⟷ [🟢 RL]
   
   ✅ Aktiv: RL (automatisch)
   📊 Win-Rate: 87% (341 Vergleiche)
   💰 Ersparnis: €12.45 diese Woche
```

---

## 🔌 API Dokumentation

### Endpoints

#### `GET /health`
Health-Check
```json
{"status": "ok", "version": "2.6.8"}
```

#### `GET /status`
System-Status inkl. RL
```json
{
  "current": {...},
  "rl_devices": {
    "battery": {
      "mode": "rl",
      "win_rate": 0.87,
      "comparisons": 341
    }
  }
}
```

#### `GET /vehicles`
Alle Fahrzeuge mit Status

#### `GET /slots`
Detaillierte Ladeslots

#### `GET /rl-devices`
RL-Status pro Gerät

#### `POST /rl-override`
Manueller Mode-Switch
```json
{
  "device": "battery",
  "mode": "manual_lp"  // oder: manual_rl, auto
}
```

---

## 🔧 Troubleshooting

### RL lernt nicht
- Prüfe LP-Entscheidungen in Logs
- Prüfe InfluxDB Verbindung
- Prüfe Comparison-Log

### Fahrzeug-SoC bei 0%
- Credentials korrekt?
- API erreichbar?
- Custom-Script ausführbar?

### Auto-Switch funktioniert nicht
- Win-Rate ≥ 80%?
- Comparisons ≥ 200?
- Override aktiv?

---

## ❓ FAQ

**Wann RL aktivieren?**  
Sofort! Shadow Mode ist risikofrei.

**Wie lange Training?**  
Minimum 2 Wochen, optimal 1-2 Monate.

**Kann ich nur RL nutzen?**  
Nein, Hybrid-Ansatz empfohlen für Fallback.

**Speichert RL bei Neustart?**  
Ja, alle Daten persistent.

**Wie viel spart RL?**  
Typisch: €50-150/Monat bei optimalen Bedingungen.

---

## 👨‍💻 Entwickler

### Repository
```
evcc-smartload/
├── config.yaml
├── Dockerfile
├── README.md
├── rootfs/
│   └── app/
│       ├── main.py
│       └── vehicles/
└── data/
```

### Lokale Entwicklung
```bash
git clone https://github.com/Krinco1/HA_Addon_EVCC-Smartload
cd evcc-smartload
python3 -m venv venv
source venv/bin/activate
python rootfs/app/main.py
```

### Neuen Provider
1. Erstelle `vehicles/mycar_provider.py`
2. Implementiere `VehicleProvider` Interface
3. Registriere in `__init__.py`

---

## 📄 Lizenz

MIT License

---

## 🙏 Credits

- evcc
- Home Assistant
- hyundai-kia-connect-api
- renault-api

---

<div align="center">

**Made with ❤️ for the HA Community**

⭐ Star this repo if EVCC-Smartload helps you!

</div>
