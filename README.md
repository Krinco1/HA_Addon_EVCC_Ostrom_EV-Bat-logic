# Home Assistant Add-on: EVCC-Smartload

![Version](https://img.shields.io/badge/version-4.3.7-blue.svg)
![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-green.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-green.svg)
![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-green.svg)

**KI-gestützte Energieoptimierung für Heimspeicher & Elektrofahrzeuge**

---

## About

EVCC-Smartload ist ein intelligentes Energiemanagementsystem für Home Assistant, das Heimspeicher und Elektrofahrzeuge basierend auf dynamischen Strompreisen, PV-Prognosen und Verbrauchsdaten optimiert.

### Features

- 🔋 Batterie-Optimierung mit dynamischen Preiskorridoren
- 🚗 Multi-Vehicle Support (KIA, Renault, Custom, Manual)
- 🤖 Hybrid LP + RL Optimierung mit Pro-Device Control
- 🔋→🚗 Batterie-Entladung für EV mit Profitabilitätsberechnung
- 🎯 Dynamische Entladegrenzen (bufferSoc/prioritySoc via evcc API)
- ☀️ Solar-Prognose als SVG-Linie im Preischart
- 📊 Live-Dashboard mit Auto-Refresh (Mobile-First)
- ⚡ Umfangreiche evcc API Integration
- 📈 Persistenter manueller SoC für Fahrzeuge ohne API
- 🏗️ Modulare Architektur (v4.3.7)

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

### 3. Konfiguration anpassen

Siehe die [ausführliche Dokumentation](evcc-smartload/README.md).

### 4. Add-on starten

Dashboard öffnen: `http://homeassistant:8099`

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues)

---

## License

MIT License

---

<div align="center">

**Made with ❤️ for the Home Assistant Community**

</div>
