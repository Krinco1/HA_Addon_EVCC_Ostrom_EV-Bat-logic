# EVCC-Smartload v3.0.0 - Installation Guide

## 📦 Release Package

Dieses Paket enthält:
- ✅ EVCC-Smartload v3.0.0 Complete Source
- ✅ Pro-Device RL Control System
- ✅ Integrated Documentation
- ✅ Ready for GitHub Release

---

## 🚀 Quick Install (Home Assistant)

### Method 1: Add-on Repository (Recommended)

1. **In Home Assistant:**
   - Einstellungen → Add-ons → Add-on Store
   - ⋮ (oben rechts) → Repositories
   - Repository URL hinzufügen:
     ```
     https://github.com/Krinco1/HA_Addon_EVCC-Smartload
     ```

2. **EVCC-Smartload installieren:**
   - Im Add-on Store nach "EVCC-Smartload" suchen
   - "EVCC-Smartload v3 - Hybrid Optimizer" auswählen
   - **Installieren** klicken

3. **Konfigurieren:**
   - Configuration Tab öffnen
   - Mindestens erforderlich:
     ```yaml
     evcc_url: "http://YOUR_EVCC_IP:7070"
     influxdb_host: "YOUR_INFLUXDB_IP"
     ```
   
4. **Starten:**
   - **Start** klicken
   - **Log** Tab: Startup beobachten
   - Dashboard: `http://homeassistant:8099`

---

### Method 2: Manual Installation (Advanced)

1. **Unpack this ZIP:**
   ```bash
   unzip smartprice_v3.0.0_release.zip
   cd smartprice_v3.0.0
   ```

2. **Copy to HA:**
   ```bash
   # SSH to Home Assistant
   mkdir -p /addons/smartprice
   cp -r * /addons/smartprice/
   ```

3. **Install via Local Add-ons:**
   - Einstellungen → Add-ons
   - Refresh
   - EVCC-Smartload sollte erscheinen

---

## ⚙️ Configuration

### Minimal Configuration

```yaml
# Connection
evcc_url: "http://192.168.1.66:7070"
evcc_password: ""

# InfluxDB
influxdb_host: "192.168.1.67"
influxdb_database: "smartprice"
influxdb_username: "smartprice"
influxdb_password: "smartprice"

# Battery
battery_capacity_kwh: 33.1
battery_max_price_ct: 25.0

# EV
ev_max_price_ct: 30.0
ev_target_soc: 80

# RL (New in v3.0)
rl_enabled: true
rl_auto_switch: true
rl_fallback_threshold: 0.7
```

### Vehicle Configuration

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

---

## 📊 Post-Installation

### 1. Verify Installation

```bash
# Check logs:
docker logs addon_smartprice -f

# Should show:
# [INFO] EVCC-Smartload v3.0.0 - Hybrid LP + Shadow RL
# [INFO] Pro-Device RL: Jedes Gerät hat eigenen Agent
# [DEBUG] RLDeviceController database initialized
```

### 2. Access Dashboard

```
http://homeassistant:8099
```

Features:
- Live Status
- RL Progress per Device
- Documentation Viewer (`/docs`)

### 3. Check API

```bash
# Device Status:
curl http://homeassistant:8099/rl-devices | jq

# Documentation:
http://homeassistant:8099/docs
```

---

## 🎯 First Steps

### Monitor Training (Week 1-2)

1. **Dashboard:** Check RL win-rate daily
2. **Logs:** Watch for auto-switch events
3. **API:** Query `/rl-devices` for details

### Auto-Switch (Week 3-4)

When battery reaches **80%+ win-rate** and **200+ comparisons**:

```
[INFO] 🎉 battery: Auto-Switch LP → RL (Win-Rate 87%)
```

Device automatically switches to RL mode!

### Manual Override (Optional)

```bash
# Force RL mode:
curl -X POST http://homeassistant:8099/rl-override \
  -H 'Content-Type: application/json' \
  -d '{"device": "battery", "mode": "manual_rl"}'

# Back to auto:
curl -X POST http://homeassistant:8099/rl-override \
  -H 'Content-Type: application/json' \
  -d '{"device": "battery", "mode": "auto"}'
```

---

## 🔧 Troubleshooting

### Issue: Version shows wrong

**Solution:**
```bash
# Check config.yaml:
docker exec addon_smartprice cat /etc/smartprice/config.yaml | grep version

# Should show: version: "3.0.0"
```

### Issue: RL not training

**Solution:**
```bash
# Check logs for LP decisions:
docker logs addon_smartprice | grep "LP:"

# Check database:
docker exec addon_smartprice sqlite3 /data/smartprice_device_control.db \
  "SELECT * FROM device_control"
```

### Issue: Auto-switch not working

**Solution:**
```bash
# Check rl_auto_switch setting:
docker exec addon_smartprice cat /data/options.json | jq .rl_auto_switch

# Should be: true
```

---

## 📚 Documentation

### In-Dashboard
- **Overview:** http://homeassistant:8099/docs
- **README:** http://homeassistant:8099/docs/readme
- **API Docs:** http://homeassistant:8099/docs/api
- **Changelog:** http://homeassistant:8099/docs/changelog

### Files
- `README.md` - Complete user manual
- `CHANGELOG_v3.0.0.md` - Detailed changes
- `RELEASE_NOTES.md` - GitHub release summary

---

## 🔄 Migration from v2.6.x

### Automatic
- ✅ SQLite database created
- ✅ Devices start in LP mode
- ✅ RL training continues
- ✅ Old models loaded

### Manual (Optional)
1. Add new config parameters
2. Configure RL modes per device
3. Monitor auto-switch events

---

## 🆘 Support

### Issues
https://github.com/Krinco1/HA_Addon_EVCC-Smartload/issues

### Discussions
https://github.com/Krinco1/HA_Addon_EVCC-Smartload/discussions

### Logs
```bash
# Full logs:
docker logs addon_smartprice -f

# RL specific:
docker logs addon_smartprice -f | grep -E "RL|Device|Switch"

# Errors only:
docker logs addon_smartprice -f | grep ERROR
```

---

## 🎯 What's Next?

1. ✅ Install and configure
2. ✅ Monitor training (2-4 weeks)
3. ✅ Watch for auto-switch
4. ✅ Enjoy savings!

**Expected:** €50-150/month savings bei optimalen Bedingungen

---

<div align="center">

**Questions? Check `/docs` in dashboard or open a GitHub Issue!**

Made with ❤️ for the HA Community

</div>
