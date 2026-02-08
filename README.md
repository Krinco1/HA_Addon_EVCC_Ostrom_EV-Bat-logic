# EVCC-Smartload v3.0.5 - Intelligent Energy Management

[![Version](https://img.shields.io/badge/version-3.0.5-blue.svg)](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/releases/tag/v3.0.5)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Addon-blue.svg)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**🎉 NEU: Pro-Device RL Control • Integrierte Dokumentation • v3.0.5 Major Release**

---

## 🚀 Was ist EVCC-Smartload?

**KI-gestützte Energieoptimierung für Heimspeicher & Elektrofahrzeuge**

EVCC-Smartload optimiert automatisch Ihren Heimspeicher und Elektrofahrzeuge basierend auf dynamischen Strompreisen. Das System kombiniert mathematische Optimierung (LP) mit Reinforcement Learning (RL) für maximale Effizienz.

### ✨ Hauptfeatures v3.0.5

- 🔋 **Batterie-Optimierung** mit dynamischen Preiskorridoren
- 🚗 **Multi-Vehicle Support** (KIA, Renault, Custom APIs)
- 🤖 **Hybrid LP + RL** mit Pro-Device Control (NEU!)
- 📊 **Integrierte Dokumentation** im Dashboard (NEU!)
- ⚡ **evcc Integration** für Wallbox-Steuerung
- 📈 **Detailliertes Monitoring** & REST API
- 🎯 **Auto-Switch** von LP zu RL wenn ready (NEU!)

---

## 📦 Installation

### Schritt 1: Repository hinzufügen

In Home Assistant:
1. **Einstellungen** → **Add-ons** → **Add-on Store**
2. Klicke **⋮** (oben rechts) → **Repositories**
3. Füge hinzu:
   ```
   https://github.com/Krinco1/HA_Addon_EVCC-Smartload
   ```

### Schritt 2: Add-on installieren

1. Suche "EVCC-Smartload" im Add-on Store
2. Klicke **INSTALLIEREN**
3. Warte 5-10 Minuten

### Schritt 3: Konfigurieren

Minimal-Konfiguration:
```yaml
evcc_url: "http://192.168.1.66:7070"
influxdb_host: "192.168.1.67"
battery_capacity_kwh: 33.1
battery_max_price_ct: 25.0
```

### Schritt 4: Starten

- Klicke **START**
- Dashboard öffnen: `http://homeassistant:8099`

---

## 🎯 Was ist neu in v3.0.5?

### Pro-Device RL Control
Jedes Gerät (Batterie, Fahrzeuge) hat jetzt seinen eigenen RL-Agent:
- ✅ Separate Performance-Tracking
- ✅ Individuelle Win-Rate & Ersparnis
- ✅ **Auto-Switch** zu RL bei 80%+ Win-Rate
- ✅ **Auto-Fallback** zu LP bei <70% Performance
- ✅ Manuelle Overrides via API

### Integrierte Dokumentation
- 📚 Vollständige Docs im Dashboard (`/docs`)
- 📖 README, Changelog, API Docs
- 🔍 Markdown-Viewer integriert

### API v3.0
- `GET /rl-devices` - Status aller Geräte
- `POST /rl-override` - Manual Mode Control
- `GET /docs` - Documentation Viewer
- `GET /docs/readme` - Full README
- `GET /docs/api` - API Reference

---

## 🏗️ Architektur

```
LP Optimizer (Production)  ←→  RL Agent (Learning)
         ↓                            ↓
    Pro-Device Mode Selection
         ↓                            ↓
    Controller  ←────────────→  Controller
         ↓                            ↓
      evcc API                    evcc API
```

### Hybrid-Ansatz
- **LP**: Mathematisch optimal, sofort einsatzbereit
- **RL**: Lernt aus Erfahrung, wird kontinuierlich besser
- **Pro-Device**: Jedes Gerät kann LP oder RL nutzen

---

## ⚙️ Konfiguration

### Basis
```yaml
# EVCC Connection
evcc_url: "http://192.168.1.66:7070"
evcc_password: ""

# InfluxDB
influxdb_host: "192.168.1.67"
influxdb_database: "smartload"
influxdb_username: "smartload"
influxdb_password: "smartload"

# Batterie
battery_capacity_kwh: 33.1
battery_max_price_ct: 25.0

# EV
ev_max_price_ct: 30.0
ev_target_soc: 80
```

### Mit Fahrzeugen
```yaml
vehicle_providers: |
  [
    {
      "evcc_name": "KIA_EV9",
      "type": "kia",
      "user": "email@example.com",
      "password": "password",
      "capacity_kwh": 99.8,
      "rl_mode": "auto"
    },
    {
      "evcc_name": "Twingo",
      "type": "renault",
      "user": "email@example.com",
      "password": "password",
      "capacity_kwh": 22,
      "rl_mode": "auto"
    }
  ]
```

### RL Control (v3.0)
```yaml
rl_enabled: true
rl_auto_switch: true           # Auto-Switch aktivieren
rl_ready_threshold: 0.8        # 80% Win-Rate erforderlich
rl_fallback_threshold: 0.7     # Fallback bei < 70%
rl_ready_min_comparisons: 200  # Mindestens 200 Vergleiche
```

---

## 📊 Performance Erwartungen

### Training Timeline
- **Woche 1-2**: RL lernt von LP (~60% win-rate)
- **Woche 3-4**: RL entwickelt Strategien (~80%)
- **Woche 4+**: "RL READY" für erste Geräte
- **Woche 6-8**: Alle Geräte auf RL (wenn gut performt)

### Erwartete Ersparnis
- Battery 30kWh: €10-30/Monat
- EV 100kWh: €20-50/Monat
- **Total: €50-150/Monat** (optimale Bedingungen)

---

## 🔌 API Endpoints

Nach Installation verfügbar unter `http://homeassistant:8099`:

### System
- `GET /health` - Health Check
- `GET /status` - Vollständiger System-Status
- `GET /summary` - Kurzübersicht

### Devices
- `GET /vehicles` - Alle Fahrzeuge
- `GET /slots` - Detaillierte Ladeslots
- `GET /rl-devices` - RL Device Status (v3.0)

### Control
- `POST /rl-override` - Manual RL Mode (v3.0)
- `POST /save` - Speichere RL Modell

### Documentation
- `GET /docs` - Documentation Index (v3.0)
- `GET /docs/readme` - README als HTML (v3.0)
- `GET /docs/api` - API Docs (v3.0)

---

## 📚 Dokumentation

### Im Dashboard
Nach Installation unter:
- **Dashboard**: `http://homeassistant:8099`
- **Docs**: `http://homeassistant:8099/docs`
- **API**: `http://homeassistant:8099/docs/api`

### Dateien
- [CHANGELOG](evcc-smartload/CHANGELOG_v3.0.5.md) - Was ist neu?
- [INSTALL](evcc-smartload/INSTALL.md) - Installation & Setup
- [README](evcc-smartload/README.md) - Vollständige Dokumentation

---

## 🆘 Support & Hilfe

### Issues
Probleme? Bugs gefunden?
→ [GitHub Issues](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues)

### Discussions
Fragen? Ideen? Feedback?
→ [GitHub Discussions](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/discussions)

### Logs
```bash
# Add-on Logs anzeigen:
ha addons logs addon_evcc_smartload

# Supervisor Logs:
ha supervisor logs
```

---

## 🔄 Updates

### Von v2.6.x → v3.0.5

**Automatisch:**
- SQLite-Datenbank wird erstellt
- Devices starten mit LP Mode
- RL Training läuft weiter

**Manuell (empfohlen):**
```yaml
# Neue Config-Parameter hinzufügen:
rl_auto_switch: true
rl_fallback_threshold: 0.7
```

---

## 🎯 Quick Start Guide

1. ✅ Repository hinzufügen (siehe oben)
2. ✅ Add-on installieren
3. ✅ Minimal-Config eintragen
4. ✅ Starten
5. ✅ Dashboard öffnen: `http://homeassistant:8099`
6. ✅ Dokumentation lesen: `http://homeassistant:8099/docs`
7. ⏰ 2-4 Wochen Training warten
8. 🎉 Auto-Switch zu RL!

---

## 💡 Tipps & Tricks

### Vehicle SoC Updates
- Aktualisiert alle 60 Minuten (configurable)
- Bei Verbindung sofort
- Timestamp im Dashboard

### RL Device Control
- Aktuell nur via API
- Dashboard-UI kommt in v3.0.1
- Manual Override: `curl -X POST .../rl-override`

### Dokumentation
- Immer aktuell im Dashboard
- Funktioniert offline (integriert)

---

## 📈 Changelog

### v3.0.5 (2024-02-08) - Major Release

**🎉 Neue Features:**
- Pro-Device RL Control System
- Integrierte Dokumentation im Dashboard
- Auto-Switch & Auto-Fallback
- Neue API Endpoints

**🔧 Verbesserungen:**
- SQLite-based Device Modes
- Separate Performance Tracking
- Dynamische Version Loading

**⚠️ Breaking Changes:**
- Neue Config-Parameter erforderlich
- Database Schema Update

[Vollständiges Changelog](evcc-smartload/CHANGELOG_v3.0.5.md)

---

## 🙏 Credits

- **evcc** - Electric Vehicle Charge Controller
- **Home Assistant** - Home Automation Platform
- **hyundai-kia-connect-api** - KIA Integration
- **renault-api** - Renault Integration

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with ❤️ for the Home Assistant Community**

**Version 3.0.5 • 2024-02-08**

⭐ Star this repo if EVCC-Smartload helps you save money!

[Issues](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues) • 
[Discussions](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/discussions) • 
[Documentation](http://homeassistant:8099/docs)

</div>
