# Home Assistant Add-on: EVCC-Smartload

![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)
![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-green.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-green.svg)
![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-green.svg)

**KI-gestützte Energieoptimierung für Heimspeicher & Elektrofahrzeuge**

---

## About

EVCC-Smartload ist ein intelligentes Energiemanagementsystem für Home Assistant, das Heimspeicher und Elektrofahrzeuge basierend auf dynamischen Strompreisen optimiert.

### Features

- 🔋 Batterie-Optimierung mit dynamischen Preiskorridoren
- 🚗 Multi-Vehicle Support (KIA, Renault, Custom)
- 🤖 Hybrid LP + RL Optimierung mit Pro-Device Control
- 📊 Integrierte Dokumentation im Dashboard
- ⚡ evcc Integration
- 📈 Detailliertes Monitoring & API

---

## Installation

### 1. Repository hinzufügen

In Home Assistant:
- **Einstellungen** → **Add-ons** → **Add-on Store**
- Klicke auf **⋮** (drei Punkte oben rechts)
- Wähle **Repositories**
- Füge hinzu:
  ```
  https://github.com/Krinco1/HA_Addon_EVCC-Smartload
  ```

### 2. EVCC-Smartload installieren

- Suche nach "EVCC-Smartload" im Add-on Store
- Klicke auf "EVCC-Smartload - Hybrid Optimizer"
- Klicke auf **INSTALLIEREN**

### 3. Konfigurieren

Öffne den **Configuration** Tab und passe an:

```yaml
evcc_url: "http://192.168.1.66:7070"
influxdb_host: "192.168.1.67"
influxdb_database: "smartload"
battery_capacity_kwh: 33.1
battery_max_price_ct: 25.0
```

### 4. Starten

- Klicke auf **START**
- Öffne das Dashboard: `http://homeassistant:8099`

---

## Documentation

Nach Installation verfügbar unter:
- **Dashboard**: `http://homeassistant:8099`
- **Dokumentation**: `http://homeassistant:8099/docs`
- **API**: `http://homeassistant:8099/docs/api`

---

## Features v3.0.0

### 🎉 Pro-Device RL Control
Jedes Gerät (Batterie, Fahrzeuge) hat seinen eigenen RL-Agent:
- Separate Performance-Tracking
- Individuelle Win-Rate & Ersparnis
- Auto-Switch zu RL wenn ready
- Auto-Fallback zu LP bei schlechter Performance

### 📚 Integrierte Dokumentation
- Vollständige Docs im Dashboard (`/docs`)
- README, Changelog, API Docs
- Markdown-Viewer

### ⚡ API v3.0
- `GET /rl-devices` - Device Status
- `POST /rl-override` - Manual Mode Control
- `GET /docs` - Documentation Viewer

---

## Configuration

### Minimal
```yaml
evcc_url: "http://192.168.1.66:7070"
influxdb_host: "192.168.1.67"
battery_capacity_kwh: 33.1
battery_max_price_ct: 25.0
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
    }
  ]
```

### RL Control (v3.0)
```yaml
rl_enabled: true
rl_auto_switch: true           # Automatisch zu RL wechseln
rl_ready_threshold: 0.8        # 80% Win-Rate erforderlich
rl_fallback_threshold: 0.7     # Fallback bei < 70%
```

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/discussions)

---

## Changelog

### v3.0.0 (2024-02-08)

**Major Release:**
- 🎉 **NEW**: Pro-Device RL Control
- 🎉 **NEW**: Integrated Documentation Viewer
- 🎉 **NEW**: Auto-Switch & Auto-Fallback per Device
- 📚 Complete documentation rewrite
- 🔧 SQLite-based device mode persistence
- 🔌 New API endpoints for device control

**Breaking Changes:**
- Configuration requires new RL parameters
- Database schema updated (auto-migrated)

[Full Changelog](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/blob/main/evcc-smartload/CHANGELOG_v3.0.0.md)

---

## Architecture

```
LP Optimizer (Production)  ←→  RL Agent (Learning/Production)
         ↓                              ↓
    Controller  ←  Pro-Device Mode Selection  →  Controller
         ↓                                           ↓
      evcc API                                   evcc API
```

### Hybrid Approach
- **LP**: Mathematisch optimal, sofort einsatzbereit
- **RL**: Lernt aus Erfahrung, wird mit Zeit besser
- **Pro-Device**: Jedes Gerät hat eigenen Agent

---

## Performance Expectations

### Training Timeline
- **Woche 1-2**: RL lernt von LP (~60% win-rate)
- **Woche 3-4**: RL entwickelt Strategien (~80%)
- **Woche 4+**: "RL READY" für erste Geräte
- **Woche 6-8**: Alle Geräte auf RL (bei guter Performance)

### Expected Savings
- Battery 30kWh: €10-30/Monat
- EV 100kWh: €20-50/Monat
- **Total: €50-150/Monat** (bei optimalen Bedingungen)

---

## Development

### Repository Structure
```
HA_Addon_EVCC-Smartload/
├── repository.json           # HA Repository Config
├── README.md                 # This file
└── evcc-smartload/           # Add-on
    ├── config.yaml           # Add-on Config
    ├── Dockerfile
    ├── README.md             # Add-on Documentation
    ├── rootfs/
    │   └── app/
    │       └── main.py       # Main Application
    └── CHANGELOG_v3.0.0.md
```

### Local Development
```bash
git clone https://github.com/Krinco1/HA_Addon_EVCC-Smartload.git
cd HA_Addon_EVCC-Smartload/evcc-smartload
python3 rootfs/app/main.py
```

---

## License

MIT License

---

## Credits

- **evcc** - Electric Vehicle Charge Controller
- **Home Assistant** - Home Automation Platform
- **hyundai-kia-connect-api** - KIA Integration
- **renault-api** - Renault Integration

---

<div align="center">

**Made with ❤️ for the Home Assistant Community**

⭐ Star this repo if EVCC-Smartload helps you!

</div>
