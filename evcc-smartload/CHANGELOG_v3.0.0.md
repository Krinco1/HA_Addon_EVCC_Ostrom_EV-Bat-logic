# EVCC-Smartload v3.0.0 - Major Release

**Release Date:** 2024-02-08  
**Type:** Major Version (Breaking Changes)

---

## 🎉 Highlights

### Pro-Device RL Control
Jedes Gerät (Batterie, Fahrzeuge) hat jetzt seinen eigenen RL-Agent mit:
- Separatem Tracking
- Individueller Win-Rate
- Auto-Switch wenn ready
- Manuellen Overrides

### Integrierte Dokumentation
- Vollständige Docs im Dashboard (`/docs`)
- README, Changelog, API Docs abrufbar
- Markdown-Viewer für einfache Navigation

### Dynamische Versionsverwaltung
- Version wird aus config.yaml geladen
- Automatische Anzeige in Logs und Dashboard

---

## 🚀 New Features

### RL Device Controller
- **SQLite-Datenbank** für persistente Device-Modes
- **Auto-Switch Logik**: Automatisch zu RL bei 80%+ Win-Rate
- **Auto-Fallback**: Zurück zu LP bei <70% Performance
- **Manual Overrides**: Permanente User-Kontrolle pro Gerät
- **Per-Device Tracking**: Separate Metriken für Battery, EVs

### API Endpoints
- `GET /rl-devices` - Status aller RL-Devices
- `POST /rl-override` - Manueller Mode-Switch
- `GET /docs` - Dokumentations-Index
- `GET /docs/readme` - README als HTML
- `GET /docs/changelog` - Dieser Changelog
- `GET /docs/api` - API Dokumentation

### Dashboard
- Docs-Link im Header
- Version dynamisch aus config.yaml
- RL Device Control Widgets (in Vorbereitung)

### Configuration
- `rl_auto_switch: bool` - Auto-Switch aktivieren
- `rl_fallback_threshold: float` - Fallback-Schwelle

---

## 🔧 Changes & Improvements

### Core
- **Main Loop**: Pro-Device Mode Selection implementiert
- **Comparator**: `compare_per_device()` Methode für separates Tracking
- **Version Loading**: `load_version()` aus YAML statt Hardcoded

### Dependencies
- **PyYAML** hinzugefügt für config.yaml Parsing

### Documentation
- **README.md**: Vollständig neu geschrieben (1200+ Zeilen)
- **IMPLEMENTATION_GUIDE.md**: Schritt-für-Schritt Anleitung
- **CHANGELOG_v3.0.0.md**: Dieses Dokument

---

## ⚠️ Breaking Changes

### Version Jump
- v2.6.8 → v3.0.0 wegen Major Features

### Configuration Schema
Neue erforderliche Parameter:
```yaml
rl_auto_switch: true
rl_fallback_threshold: 0.7
```

Bestehende Installationen müssen diese hinzufügen oder werden mit Defaults laufen.

### Database Schema
Neue SQLite-Datenbank:
- `/data/smartprice_device_control.db`

Wird automatisch erstellt beim ersten Start.

### API Changes
**Neue Endpoints:**
- `/rl-devices` statt einzelne Device-Abfragen
- `/docs/*` für Dokumentation

**Deprecated:** (noch funktional)
- Keine in diesem Release

---

## 🐛 Bug Fixes

### v2.6.8 Bugs
- **SoC Oscillation**: Bereits in v2.6.6 gefixt, dokumentiert
- **Timestamp Display**: Fahrzeug-SoC Alter wird jetzt angezeigt

### v3.0.0 Fixes
- **Config Loading**: Robusteres YAML Parsing
- **Error Handling**: Besseres Handling für fehlende Devices
- **API Response**: Konsistentere Error-Messages

---

## 📊 Migration Guide

### Von v2.6.x → v3.0.0

**Automatisch:**
1. SQLite-Datenbank wird erstellt
2. Alle Devices starten mit LP Mode
3. RL beginnt Training pro Device

**Manuell (optional):**
1. Config erweitern mit neuen Parametern
2. RL-Modi pro Device konfigurieren via API

### Konfiguration aktualisieren

**Minimal (empfohlen):**
```yaml
rl_auto_switch: true
rl_fallback_threshold: 0.7
```

**Optimal:**
```yaml
rl_auto_switch: true          # Auto-Switch aktivieren
rl_fallback_threshold: 0.7    # Fallback bei schlechter Performance
rl_ready_threshold: 0.8       # 80% für "Ready"
rl_ready_min_comparisons: 200 # Mindestens 200 Vergleiche
```

### Daten-Migration

**Bestehende RL-Modelle:**
- ✅ Werden automatisch geladen
- ✅ Training läuft weiter
- ✅ Pro-Device Tracking startet neu

**Vergleichs-Daten:**
- ✅ Bleiben erhalten
- ✅ Werden in Pro-Device System integriert

---

## 🎯 Performance Expectations

### Training Timeline
- **Woche 1-2**: RL lernt von LP, ~50-60% Win-Rate
- **Woche 3-4**: RL entwickelt eigene Strategien, ~75-80%
- **Woche 4+**: "RL READY" für erste Geräte (Batterie meist zuerst)
- **Woche 6-8**: Alle Geräte auf RL umgestellt (bei guter Performance)

### Expected Win-Rates
- **Battery**: 85-90% (stabilstes Gerät)
- **EVs**: 75-85% (mehr Variabilität)

### Cost Savings
- **Battery 30kWh**: €10-30/Monat
- **EV 100kWh**: €20-50/Monat
- **Gesamt**: €50-150/Monat bei optimalen Bedingungen

---

## 🔮 Roadmap

### v3.1 (Q1 2024)
- [ ] Dashboard RL Device Control Widgets (vollständig)
- [ ] InfluxDB Metrics für Pro-Device Performance
- [ ] Grafana Dashboard Template
- [ ] Web-UI für Vehicle Provider Configuration

### v3.2 (Q2 2024)
- [ ] Multi-RL Agents (separate Networks pro Device)
- [ ] Advanced Reward Shaping
- [ ] Predictive Price Modeling
- [ ] Integration mit anderen HA-Sensoren

### v4.0 (Q3 2024)
- [ ] LLM Meta-Controller (optional)
- [ ] Automated Parameter Tuning
- [ ] Community Model Sharing
- [ ] Cloud Training (optional)

---

## 📚 Documentation

### Updated Docs
- **README.md**: Vollständig neu
- **IMPLEMENTATION_GUIDE.md**: Developer Guide
- **API Docs**: Im Dashboard unter `/docs/api`

### New Guides
- **Pro-Device RL**: Wie funktioniert es?
- **Manual Override**: Wann und wie nutzen?
- **Troubleshooting**: Häufige Probleme v3.0

---

## 🙏 Credits

### Contributors
- Nico: Core Development & Konzeption
- Claude (Anthropic): Implementation Assistance

### Dependencies
- evcc - Electric Vehicle Charge Controller
- Home Assistant - Home Automation Platform
- hyundai-kia-connect-api - KIA/Hyundai Integration
- renault-api - Renault Vehicle Integration
- PyYAML - Configuration Parsing

---

## 📝 Notes

### Known Issues
- Dashboard RL Control Widgets noch nicht vollständig implementiert
- Manuelle Override via API, Dashboard-UI folgt in v3.0.1

### Workaround
```bash
# Manual Override via API:
curl -X POST http://homeassistant:8099/rl-override \
  -H 'Content-Type: application/json' \
  -d '{"device": "battery", "mode": "manual_rl"}'
```

---

## 🔗 Links

- **GitHub**: https://github.com/Krinco1/HA_Addon_EVCC-Smartload
- **Issues**: https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues
- **Discussions**: https://github.com/Krinco1/HA_Addon_EVCC-Smartload/discussions
- **Documentation**: http://homeassistant:8099/docs

---

<div align="center">

**Made with ❤️ for the Home Assistant Community**

⭐ Star us on GitHub if EVCC-Smartload helps you save money!

</div>
