# EVCC-Smartload - Hybrid Optimizer

Intelligentes Energiemanagement für Home Assistant — optimiert Hausbatterie und EV-Ladung anhand dynamischer Strompreise, Solar-Prognosen und Fahrer-Präferenzen.

## Konfiguration

### Grundeinstellungen (Add-on Optionen)

| Option | Beschreibung | Standard |
|---|---|---|
| `evcc_url` | URL des evcc-Servers | `http://evcc.local:7070` |
| `evcc_password` | evcc Passwort (optional) | leer |
| `battery_capacity_kwh` | Hausbatterie-Kapazität in kWh | `33.1` |
| `battery_max_price_ct` | Max. Preis für Batterieladung (ct/kWh) | `25.0` |
| `ev_max_price_ct` | Max. Preis für EV-Ladung (ct/kWh) | `30.0` |
| `ev_target_soc` | Standard-Ziel-SoC für EV (%) | `80` |
| `ev_charge_deadline_hour` | Deadline für EV-Ladung (Stunde) | `6` |

### InfluxDB

| Option | Beschreibung | Standard |
|---|---|---|
| `influxdb_host` | InfluxDB Server-Adresse | `influxdb.local` |
| `influxdb_port` | InfluxDB Port | `8086` |
| `influxdb_database` | Datenbankname | `smartload` |
| `influxdb_username` | Benutzername | leer |
| `influxdb_password` | Passwort | leer |
| `influxdb_ssl` | SSL/HTTPS verwenden | `false` |

### Reinforcement Learning

| Option | Beschreibung | Standard |
|---|---|---|
| `rl_enabled` | RL-Agent aktivieren | `true` |
| `rl_auto_switch` | Automatisch zu RL wechseln | `true` |
| `rl_ready_threshold` | Win-Rate-Schwelle für RL-Bereitschaft | `0.8` |
| `rl_fallback_threshold` | Rückfall-Schwelle zu LP | `0.7` |
| `rl_ready_min_comparisons` | Min. Vergleiche vor RL-Aktivierung | `200` |

### Quiet Hours

| Option | Beschreibung | Standard |
|---|---|---|
| `quiet_hours_enabled` | Kein EV-Wechsel nachts | `true` |
| `quiet_hours_start` | Beginn (Stunde) | `21` |
| `quiet_hours_end` | Ende (Stunde) | `6` |

## Fahrzeug-Konfiguration (vehicles.yaml)

Wird unter `/addon_configs/evcc_smartload/vehicles.yaml` angelegt.
Beim ersten Start wird eine Beispieldatei erzeugt.

```yaml
vehicles:
  - name: KIA_EV9
    type: kia
    username: "user@email.com"
    password: "geheim"
    pin: "1234"
    region: 2        # 1=EU, 2=DE, 3=US
    brand: kia       # kia, hyundai, genesis
    capacity_kwh: 99.8
    poll_interval_min: 60

  - name: my_Twingo
    type: renault
    username: "user@email.com"
    password: "geheim"
    locale: "de_DE"
    capacity_kwh: 22

  - name: ora_03
    type: evcc
    capacity_kwh: 63
```

## Telegram-Notifications (drivers.yaml, optional)

Unter `/addon_configs/evcc_smartload/drivers.yaml`:

```yaml
telegram_bot_token: "123456:ABC-DEF..."

drivers:
  - name: "Nico"
    vehicles: ["KIA_EV9"]
    telegram_chat_id: 123456789
```

Ohne `drivers.yaml` läuft das System ohne Notifications — wie in v4.

## Dashboard

Nach dem Start erreichbar unter **WEB UI** in der Add-on-Oberfläche oder direkt:
`http://homeassistant.local:8099`

## API-Endpunkte

| Methode | Endpoint | Beschreibung |
|---|---|---|
| GET | `/health` | Heartbeat |
| GET | `/status` | Vollständiger System-Status |
| GET | `/summary` | Kompakte Übersicht |
| GET | `/vehicles` | Alle Fahrzeuge mit SoC |
| GET | `/chart-data` | Preischart-Daten |
| GET | `/sequencer` | Lade-Zeitplan |
| GET | `/decisions` | Letzte Entscheidungen |
| GET | `/comparisons` | LP-vs-RL Statistiken |
| POST | `/vehicles/manual-soc` | Manuellen SoC setzen |
| GET | `/forecast` | 96-Slot Verbrauchs-/PV-Prognose mit Confidence |
| GET | `/events` | SSE-Stream für Live-Dashboard-Updates |
| POST | `/sequencer/request` | Lade-Anfrage stellen |
| POST | `/sequencer/cancel` | Lade-Anfrage abbrechen |
| POST | `/override/boost` | Sofort-Ladung erzwingen |
| POST | `/override/cancel` | Override abbrechen |
