# EVCC-Smartload v3.0.0 - Pro-Device RL Control 🚀

**Major Release** with breakthrough Pro-Device RL Control System!

---

## 🎉 What's New?

### Pro-Device RL Control
Each device (battery, vehicles) now has its **own RL agent** with:
- ✅ Separate performance tracking
- ✅ Individual win-rate & cost savings
- ✅ **Auto-switch** to RL when ready (80%+ win-rate)
- ✅ **Auto-fallback** to LP if performance drops
- ✅ Manual overrides (permanent user control)

### Integrated Documentation
- 📚 Full docs accessible in dashboard (`/docs`)
- 📖 README, Changelog, API docs as HTML
- 🔍 Built-in Markdown viewer

### Dynamic Version Management
- Version loaded from `config.yaml`
- Automatic display in logs & dashboard

---

## 📦 Installation

### Home Assistant Add-on Store
1. Add repository: `https://github.com/Krinco1/HA_Addon_EVCC-Smartload`
2. Install "EVCC-Smartload v3"
3. Configure and start

### Configuration
```yaml
# New required parameters:
rl_auto_switch: true
rl_fallback_threshold: 0.7
```

---

## 🚀 Key Features

### Core System
- **Pro-Device Modes**: LP, RL, Auto per device
- **SQLite Persistence**: Device modes survive restarts
- **Performance Tracking**: Win-rate, cost savings per device
- **Smart Auto-Switch**: Automatic LP→RL when ready

### API (v3.0)
- `GET /rl-devices` - Device status & performance
- `POST /rl-override` - Manual mode control
- `GET /docs` - Integrated documentation

### Dashboard
- Dynamic version display
- Documentation viewer
- Device controls (coming in v3.0.1)

---

## ⚠️ Breaking Changes

### Version Jump
v2.6.x → v3.0.0 (major changes)

### New Config Parameters
```yaml
rl_auto_switch: true          # Enable auto-switch
rl_fallback_threshold: 0.7    # Fallback threshold
```

### New Database
- `/data/smartprice_device_control.db` (auto-created)

---

## 📊 Expected Performance

### Training Timeline
- Week 1-2: RL learns from LP (~60% win-rate)
- Week 3-4: RL develops strategies (~80%)
- Week 4+: "RL READY" for first devices
- Week 6-8: All devices on RL (if performing well)

### Cost Savings
- Battery 30kWh: €10-30/month
- EV 100kWh: €20-50/month
- **Total: €50-150/month** (optimal conditions)

---

## 📚 Documentation

### In-Dashboard
- 📖 `/docs` - Documentation index
- 📝 `/docs/readme` - Full user manual
- 🔌 `/docs/api` - API reference

### Files
- `README.md` - Comprehensive guide (1200+ lines!)
- `CHANGELOG_v3.0.0.md` - Detailed changes
- `IMPLEMENTATION_GUIDE.md` - Developer guide

---

## 🐛 Bug Fixes

- Improved config loading (robust YAML parsing)
- Better error handling for missing devices
- Consistent API error messages
- Timestamp display for vehicle SoC

---

## 🔮 What's Next?

### v3.0.1 (Coming Soon)
- Dashboard RL control widgets
- Visual mode toggles
- Real-time performance graphs

### v3.1 (Q1 2024)
- InfluxDB metrics per device
- Grafana dashboard template
- Web-UI for vehicle configuration

---

## 💡 Quick Start

### 1. Install & Configure
```yaml
rl_auto_switch: true
rl_fallback_threshold: 0.7
```

### 2. Monitor Training
```bash
# Check device status:
curl http://homeassistant:8099/rl-devices

# View docs:
http://homeassistant:8099/docs
```

### 3. Manual Override (if needed)
```bash
curl -X POST http://homeassistant:8099/rl-override \
  -H 'Content-Type: application/json' \
  -d '{"device": "battery", "mode": "manual_rl"}'
```

---

## 🙏 Credits

- **Nico**: Core development & concept
- **Community**: Testing & feedback
- **evcc**: Vehicle charge control
- **Home Assistant**: Platform

---

## 📝 Full Changelog

See [CHANGELOG_v3.0.0.md](CHANGELOG_v3.0.0.md) for complete details.

---

## 🔗 Links

- **Documentation**: http://homeassistant:8099/docs
- **Issues**: https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues
- **Discussions**: https://github.com/Krinco1/HA_Addon_EVCC-Smartload/discussions

---

<div align="center">

**⭐ Star this repo if EVCC-Smartload saves you money!**

Made with ❤️ for the Home Assistant Community

</div>
