"""
HTTP API server for EVCC-Smartload — v5.0

New in v5:
  - Constructor accepts optional sequencer, driver_mgr, notifier
  - GET /sequencer  — charge schedule + request status + quiet hours
  - GET /drivers    — driver/Telegram config overview (no secrets)
  - POST /sequencer/request — manually add a charge request
  - POST /sequencer/cancel  — cancel a charge request
  - Existing endpoints fully backward-compatible
"""

import json
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional

from config import Config
from logging_util import log
from state import Action, ManualSocStore, SystemState, calc_solar_surplus_kwh
from version import VERSION

from web.template_engine import render as render_template


STATIC_DIR = Path(__file__).parent / "static"


class WebServer:
    """Wraps the HTTP server and provides state-update hooks."""

    def __init__(self, cfg: Config, optimizer, rl_agent, comparator,
                 event_detector, collector, vehicle_monitor, rl_devices,
                 manual_store: ManualSocStore, decision_log=None,
                 # v5 optional
                 sequencer=None, driver_mgr=None, notifier=None):
        self.cfg = cfg
        self.lp = optimizer
        self.rl = rl_agent
        self.comparator = comparator
        self.events = event_detector
        self.collector = collector
        self.vehicle_monitor = vehicle_monitor
        self.rl_devices = rl_devices
        self.manual_store = manual_store
        self.decision_log = decision_log
        # v5
        self.sequencer = sequencer
        self.driver_mgr = driver_mgr
        self.notifier = notifier

        self._last_state: Optional[SystemState] = None
        self._last_lp_action: Optional[Action] = None
        self._last_rl_action: Optional[Action] = None
        self._last_solar_forecast: List[Dict] = []

    def update_state(self, state: SystemState, lp_action: Action, rl_action: Action,
                     solar_forecast: List[Dict] = None):
        self._last_state = state
        self._last_lp_action = lp_action
        self._last_rl_action = rl_action
        if solar_forecast is not None:
            self._last_solar_forecast = solar_forecast

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def start(self):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def _json(self, data, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data, indent=2, default=str).encode())

            def _html(self, html, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode())

            def do_GET(self):
                path = self.path.split("?")[0]

                if path == "/":
                    self._html(render_template("dashboard.html", {"version": VERSION}))
                elif path == "/health":
                    self._json({"status": "ok", "version": VERSION})
                elif path == "/status":
                    self._json(srv._api_status())
                elif path == "/slots":
                    tariffs = srv.collector.evcc.get_tariff_grid()
                    self._json(srv._api_slots(tariffs, srv._last_solar_forecast))
                elif path == "/vehicles":
                    self._json(srv._api_vehicles())
                elif path == "/rl-devices":
                    self._json(srv._api_rl_devices())
                elif path == "/config":
                    self._json(srv._api_config())
                elif path == "/summary":
                    self._json(srv._api_summary())
                elif path == "/comparisons":
                    self._json({"recent": srv.comparator.comparisons[-50:],
                                "summary": srv.comparator.get_status()})
                elif path == "/strategy":
                    self._json(srv._api_strategy())
                elif path == "/decisions":
                    if srv.decision_log:
                        self._json({
                            "entries": srv.decision_log.get_recent(40),
                            "cycle": srv.decision_log.get_last_cycle_summary(),
                        })
                    else:
                        self._json({"entries": [], "cycle": {}})
                elif path == "/chart-data":
                    tariffs = srv.collector.evcc.get_tariff_grid()
                    self._json(srv._api_chart_data(tariffs, srv._last_solar_forecast))
                # v5 endpoints
                elif path == "/sequencer":
                    self._json(srv._api_sequencer())
                elif path == "/drivers":
                    self._json(srv._api_drivers())
                elif path == "/docs":
                    self._html(srv._docs_index())
                elif path.startswith("/docs/"):
                    self._html(srv._docs_page(path))
                elif path.startswith("/static/"):
                    srv._serve_static(self, path)
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                path = self.path
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}

                if path == "/vehicles/manual-soc":
                    name = body.get("vehicle", "")
                    soc = body.get("soc")
                    if not name or soc is None:
                        self._json({"error": "vehicle and soc required"}, 400)
                        return
                    try:
                        soc = float(soc)
                        if not 0 <= soc <= 100:
                            raise ValueError
                    except (ValueError, TypeError):
                        self._json({"error": "soc must be 0-100"}, 400)
                        return
                    srv.manual_store.set(name, soc)
                    srv.vehicle_monitor.trigger_refresh(name)
                    self._json({"ok": True, "vehicle": name, "soc": soc})

                elif path == "/rl-override":
                    device = body.get("device", "")
                    mode = body.get("mode")
                    if not device:
                        self._json({"error": "device required"}, 400)
                        return
                    result = srv.rl_devices.set_override(device, mode)
                    self._json(result)

                elif path == "/vehicles/refresh":
                    name = body.get("vehicle")
                    srv.vehicle_monitor.trigger_refresh(name)
                    self._json({"ok": True})

                # v5: sequencer manual request
                elif path == "/sequencer/request":
                    if srv.sequencer is None:
                        self._json({"error": "sequencer disabled"}, 503)
                        return
                    vehicle = body.get("vehicle", "")
                    target_soc = body.get("target_soc")
                    if not vehicle or target_soc is None:
                        self._json({"error": "vehicle and target_soc required"}, 400)
                        return
                    vehicles = srv.vehicle_monitor.get_all_vehicles()
                    v = vehicles.get(vehicle)
                    if not v:
                        self._json({"error": f"vehicle '{vehicle}' not found"}, 404)
                        return
                    req = srv.sequencer.add_request(
                        vehicle=vehicle,
                        driver=body.get("driver", "manual"),
                        target_soc=int(target_soc),
                        current_soc=v.get_effective_soc(),
                        capacity_kwh=v.capacity_kwh,
                        charge_power_kw=getattr(v, "charge_power_kw", None) or 11.0,
                    )
                    self._json({"ok": True, "request": {
                        "vehicle": req.vehicle_name,
                        "target_soc": req.target_soc,
                        "need_kwh": req.need_kwh,
                        "hours_needed": req.hours_needed,
                    }})

                elif path == "/sequencer/cancel":
                    if srv.sequencer is None:
                        self._json({"error": "sequencer disabled"}, 503)
                        return
                    vehicle = body.get("vehicle", "")
                    if not vehicle:
                        self._json({"error": "vehicle required"}, 400)
                        return
                    srv.sequencer.remove_request(vehicle)
                    self._json({"ok": True, "vehicle": vehicle})

                else:
                    self._json({"error": "not found"}, 404)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

        def _run():
            server = HTTPServer(("0.0.0.0", self.cfg.api_port), Handler)
            log("info", f"API server running on port {self.cfg.api_port}")
            server.serve_forever()

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Static
    # ------------------------------------------------------------------

    def _serve_static(self, handler, path: str):
        filename = path.replace("/static/", "", 1)
        filepath = STATIC_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            handler._json({"error": "not found"}, 404)
            return
        mime = "text/css" if filename.endswith(".css") else \
               "application/javascript" if filename.endswith(".js") else "text/plain"
        handler.send_response(200)
        handler.send_header("Content-Type", mime)
        handler.send_header("Cache-Control", "public, max-age=60")
        handler.end_headers()
        handler.wfile.write(filepath.read_bytes())

    # ------------------------------------------------------------------
    # JSON API builders
    # ------------------------------------------------------------------

    def _api_status(self) -> dict:
        state = self._last_state
        comparison = self.comparator.get_status()
        maturity = self._rl_maturity(comparison)
        lp = self._last_lp_action
        p = state.price_percentiles if state else {}
        return {
            "timestamp": datetime.now().isoformat(),
            "version": VERSION,
            "rl_maturity": maturity,
            "current": {
                "battery_soc": state.battery_soc,
                "battery_w": state.battery_power,
                "ev_connected": state.ev_connected,
                "ev_name": state.ev_name,
                "ev_soc": state.ev_soc,
                "ev_capacity_kwh": state.ev_capacity_kwh,
                "price_ct": round(state.current_price * 100, 1),
                "pv_w": state.pv_power,
                "home_w": state.home_power,
                "grid_w": state.grid_power,
                # v5: percentile context
                "price_p20_ct": round(p.get(20, state.current_price) * 100, 1),
                "price_p60_ct": round(p.get(60, state.current_price) * 100, 1),
                "price_spread_ct": round(state.price_spread * 100, 1),
                "hours_cheap_remaining": state.hours_cheap_remaining,
                "solar_forecast_kwh": round(state.solar_forecast_total_kwh, 1),
            } if state else None,
            "active_limits": {
                "battery_ct": round(lp.battery_limit_eur * 100, 1) if lp and lp.battery_limit_eur else None,
                "ev_ct": round(lp.ev_limit_eur * 100, 1) if lp and lp.ev_limit_eur else None,
                "battery_action": lp.battery_action if lp else None,
                "ev_action": lp.ev_action if lp else None,
            },
            "rl": {
                "enabled": self.cfg.rl_enabled,
                "epsilon": round(self.rl.epsilon, 4),
                "total_steps": self.rl.total_steps,
                "memory_size": len(self.rl.memory),
                "q_table_states": len(self.rl.q_table),
                "comparisons": comparison.get("comparisons", 0),
                "win_rate": round(comparison.get("win_rate", 0) * 100, 1),
                "ready": comparison.get("rl_ready", False),
                "n_actions": self.rl.N_ACTIONS,
                "state_size": self.rl.STATE_SIZE,
            },
            "costs": {
                "optimizer_total_eur": round(comparison.get("lp_total_cost", 0), 2),
                "rl_simulated_eur": round(comparison.get("rl_total_cost", 0), 2),
            },
            "config": self._api_config(),
            # v5
            "sequencer_enabled": self.sequencer is not None,
            "telegram_enabled": self.driver_mgr.telegram_enabled if self.driver_mgr else False,
        }

    def _api_vehicles(self) -> dict:
        vehicles = self.vehicle_monitor.get_all_vehicles()
        needs = self.vehicle_monitor.predict_charge_need()
        return {
            "timestamp": datetime.now().isoformat(),
            "vehicles": {
                name: {
                    "soc": v.get_effective_soc(),
                    "raw_soc": v.soc,
                    "manual_soc": v.manual_soc,
                    "capacity_kwh": v.capacity_kwh,
                    "range_km": v.range_km,
                    "connected": v.connected_to_wallbox,
                    "charging": v.charging,
                    "charge_needed_kwh": needs.get(name, 0),
                    "data_source": v.data_source,
                    "last_update": v.last_update.isoformat() if v.last_update else None,
                    "last_poll": v.last_poll.isoformat() if v.last_poll else None,
                    "poll_age": v.get_poll_age_string(),
                    "data_age": v.get_data_age_string(),
                    "is_stale": v.is_data_stale(),
                }
                for name, v in vehicles.items()
            },
            "total_charge_needed_kwh": sum(needs.values()),
        }

    def _api_slots(self, tariffs: List[Dict], solar_forecast: List[Dict] = None) -> dict:
        return _calculate_charge_slots(
            tariffs=tariffs,
            cfg=self.cfg,
            last_state=self._last_state,
            vehicles=self.vehicle_monitor.get_all_vehicles(),
            solar_forecast=solar_forecast,
        )

    def _api_rl_devices(self) -> dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "devices": self.rl_devices.get_all_devices(),
            "global_config": {
                "auto_switch_enabled": self.cfg.rl_auto_switch,
                "ready_threshold": self.cfg.rl_ready_threshold,
                "fallback_threshold": self.cfg.rl_fallback_threshold,
                "min_comparisons": self.cfg.rl_ready_min_comparisons,
            },
        }

    def _api_config(self) -> dict:
        return {
            "battery_max_ct": self.cfg.battery_max_price_ct,
            "ev_max_ct": self.cfg.ev_max_price_ct,
            "ev_deadline": f"{self.cfg.ev_charge_deadline_hour}:00",
            "decision_interval_minutes": self.cfg.decision_interval_minutes,
            "battery_charge_eff": self.cfg.battery_charge_efficiency,
            "battery_discharge_eff": self.cfg.battery_discharge_efficiency,
            "bat_to_ev_min_ct": self.cfg.battery_to_ev_min_profit_ct,
            "bat_to_ev_dynamic": self.cfg.battery_to_ev_dynamic_limit,
            "bat_to_ev_floor": self.cfg.battery_to_ev_floor_soc,
            # v5
            "quiet_hours_enabled": self.cfg.quiet_hours_enabled,
            "quiet_hours_start": self.cfg.quiet_hours_start,
            "quiet_hours_end": self.cfg.quiet_hours_end,
            "sequencer_enabled": self.cfg.sequencer_enabled,
        }

    def _api_summary(self) -> dict:
        comp = self.comparator.get_status()
        m = self._rl_maturity(comp)
        s = self._last_state
        lp = self._last_lp_action
        return {
            "rl_ready": comp.get("rl_ready", False),
            "rl_maturity_percent": m["percent"],
            "battery_soc": s.battery_soc if s else None,
            "ev_soc": s.ev_soc if s else None,
            "current_price_ct": round(s.current_price * 100, 1) if s else None,
            "battery_limit_ct": round(lp.battery_limit_eur * 100, 1) if lp and lp.battery_limit_eur else None,
        }

    def _api_sequencer(self) -> dict:
        """v5: Charge sequencer status."""
        if self.sequencer is None:
            return {"enabled": False}
        now = datetime.now(timezone.utc)
        return {
            "enabled": True,
            "timestamp": now.isoformat(),
            "requests": self.sequencer.get_requests_summary(),
            "schedule": self.sequencer.get_schedule_summary(),
            "quiet_hours": self.sequencer.get_quiet_hours_status(now),
            "notifications_pending": self.notifier.get_pending() if self.notifier else {},
        }

    def _api_drivers(self) -> dict:
        """v5: Driver/Telegram config (no secrets)."""
        if self.driver_mgr is None:
            return {"enabled": False, "drivers": []}
        return {
            "enabled": True,
            **self.driver_mgr.to_api_dict(),
        }

    def _rl_maturity(self, comp: dict) -> dict:
        n = comp.get("comparisons", 0)
        wr = comp.get("win_rate", 0)
        ready = comp.get("rl_ready", False)
        mn = self.cfg.rl_ready_min_comparisons
        th = self.cfg.rl_ready_threshold

        if ready:
            return {"status": "🎉 READY", "percent": 100,
                    "message": f"Win-Rate: {wr*100:.0f}%", "color": "green"}
        cp = min(100, n / mn * 100)
        wp = min(100, wr / th * 100) if th else 0
        pct = round(cp * 0.4 + wp * 0.6, 1)
        if n < 10:
            return {"status": "🌱 Lernphase", "percent": pct,
                    "message": f"Sammle Erfahrungen ({n}/{mn})", "color": "orange"}
        if n < mn * 0.5:
            return {"status": "📈 Fortschritt", "percent": pct,
                    "message": f"{n} Vergleiche, Win-Rate: {wr*100:.0f}%", "color": "blue"}
        if wr < th * 0.8:
            return {"status": "🔧 Optimierung", "percent": pct,
                    "message": f"Win-Rate {wr*100:.0f}% (Ziel: {th*100:.0f}%)", "color": "yellow"}
        return {"status": "⏳ Fast bereit", "percent": pct,
                "message": f"Noch {mn - n} Vergleiche", "color": "lightgreen"}

    def _api_strategy(self) -> dict:
        s = self._last_state
        lp = self._last_lp_action
        rl = self._last_rl_action
        if not s or not lp:
            return {"text": "Warte auf erste Daten...", "actions": []}

        price = s.current_price * 100
        p20 = s.price_percentiles.get(20, s.current_price) * 100
        p60 = s.price_percentiles.get(60, s.current_price) * 100
        actions = []
        texts = []

        bat_limit = lp.battery_limit_eur * 100 if lp.battery_limit_eur else None
        bat_names = {0: "hält", 1: "lädt (P20)", 2: "lädt (P40)", 3: "lädt (P60)",
                     4: "lädt (Max)", 5: "lädt (PV)", 6: "entlädt"}
        bat_label = bat_names.get(lp.battery_action, "?")

        if lp.battery_action in (1, 2, 3, 4):
            texts.append(f"🔋 Batterie {bat_label} (Preis {price:.1f}ct ≤ {bat_limit:.1f}ct)")
            actions.append({"device": "battery", "action": "charge", "reason": "price_below_threshold"})
        elif lp.battery_action == 6:
            texts.append(f"🔋 Batterie entlädt (Preis {price:.1f}ct > P60={p60:.1f}ct)")
            actions.append({"device": "battery", "action": "discharge", "reason": "price_high"})
        elif lp.battery_action == 5:
            texts.append(f"🔋 Batterie lädt nur Solar-Überschuss")
            actions.append({"device": "battery", "action": "pv_charge", "reason": "surplus"})
        else:
            texts.append(f"🔋 Batterie hält SoC bei {s.battery_soc:.0f}%")
            actions.append({"device": "battery", "action": "hold", "reason": "optimal"})

        if s.ev_connected:
            ev_limit = lp.ev_limit_eur * 100 if lp.ev_limit_eur else None
            ev_names = {0: "wartet", 1: "lädt (P30)", 2: "lädt (P60)", 3: "lädt (Max)", 4: "lädt (PV)"}
            ev_label = ev_names.get(lp.ev_action, "?")
            if lp.ev_action > 0:
                texts.append(f"🔌 {s.ev_name or 'EV'} {ev_label} @ {ev_limit:.1f}ct")
                actions.append({"device": "ev", "action": "charge", "reason": "price_below_threshold"})
            else:
                texts.append(f"🔌 {s.ev_name or 'EV'} wartet")
                actions.append({"device": "ev", "action": "wait", "reason": "price_too_high"})

        pv_surplus = max(0, s.pv_power - s.home_power)
        if s.pv_power > 500:
            texts.append(f"☀️ PV: {s.pv_power/1000:.1f} kW → {pv_surplus/1000:.1f} kW Überschuss")
        else:
            texts.append(f"🌙 Kein Solar – Preis {price:.1f}ct (P20={p20:.1f} P60={p60:.1f})")

        bat_mode_info = self.rl_devices.get_device_status("battery") if self.rl_devices else {}
        mode = bat_mode_info.get("current_mode", "lp")
        texts.append(f"{'🤖 RL' if mode == 'rl' else '📐 LP'} steuert Batterie")

        return {"text": " · ".join(texts[:2]), "details": texts, "actions": actions}

    def _api_chart_data(self, tariffs: List[Dict], solar_forecast: List[Dict] = None) -> dict:
        now = datetime.now(timezone.utc)
        prices = []
        for t in tariffs:
            try:
                s = t.get("start", "")
                val = float(t.get("value", 0)) * 100
                if s.endswith("Z"):
                    start = datetime.fromisoformat(s.replace("Z", "+00:00"))
                elif "+" in s:
                    start = datetime.fromisoformat(s)
                else:
                    start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
                hour = start.replace(minute=0, second=0, microsecond=0)
                if now - timedelta(hours=6) <= hour <= now + timedelta(hours=36):
                    prices.append({
                        "hour": hour.astimezone().strftime("%H:%M"),
                        "hour_utc": hour.isoformat(),
                        "price_ct": round(val, 2),
                        "is_now": hour <= now < hour + timedelta(hours=1),
                    })
            except Exception:
                continue

        solar_by_hour = {}
        if solar_forecast:
            raw_vals = [float(t.get("value", 0)) for t in solar_forecast
                        if float(t.get("value", 0)) > 0]
            unit_factor = 0.001 if raw_vals and sorted(raw_vals)[len(raw_vals) // 2] > 100 else 1.0
            for t in solar_forecast:
                try:
                    s = t.get("start", "")
                    val = float(t.get("value", 0)) * unit_factor
                    if s.endswith("Z"):
                        start = datetime.fromisoformat(s.replace("Z", "+00:00"))
                    elif "+" in s:
                        start = datetime.fromisoformat(s)
                    else:
                        start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
                    hour = start.replace(minute=0, second=0, microsecond=0)
                    hour_key = hour.astimezone().strftime("%H:%M")
                    solar_by_hour[hour_key] = max(solar_by_hour.get(hour_key, 0), val)
                except Exception:
                    continue

        for p in prices:
            p["solar_kw"] = round(solar_by_hour.get(p["hour"], 0), 2)

        # v5: add percentile lines to chart data
        state = self._last_state
        p20_ct = state.price_percentiles.get(20, 0) * 100 if state else 0
        p60_ct = state.price_percentiles.get(60, 0) * 100 if state else 0

        pv_now = state.pv_power / 1000 if state else 0
        home_now = state.home_power / 1000 if state else 0
        grid_now = state.grid_power / 1000 if state else 0
        bat_power = state.battery_power / 1000 if state else 0
        total_solar_kwh = sum(solar_by_hour.values())

        return {
            "prices": prices,
            "has_solar_forecast": len(solar_by_hour) > 0,
            "solar_total_kwh": round(total_solar_kwh, 1),
            "pv_now_kw": round(pv_now, 2),
            "home_now_kw": round(home_now, 2),
            "grid_now_kw": round(grid_now, 2),
            "battery_power_kw": round(bat_power, 2),
            "pv_surplus_kw": round(max(0, pv_now - home_now), 2),
            "current_price_ct": round(state.current_price * 100, 1) if state else None,
            "battery_max_ct": self.cfg.battery_max_price_ct,
            "ev_max_ct": self.cfg.ev_max_price_ct,
            # v5
            "p20_ct": round(p20_ct, 1),
            "p60_ct": round(p60_ct, 1),
        }

    # ------------------------------------------------------------------
    # Documentation
    # ------------------------------------------------------------------

    def _docs_index(self) -> str:
        return f"""<!DOCTYPE html><html><head><title>Docs – EVCC-Smartload</title><meta charset="utf-8">
<style>body{{font-family:-apple-system,sans-serif;margin:40px;background:#1a1a2e;color:#eee;}}
.c{{max-width:900px;margin:0 auto;}}h1{{color:#00d4ff;}}
.card{{background:#16213e;padding:20px;margin:20px 0;border-radius:8px;cursor:pointer;}}
.card:hover{{background:#1e2d50;}}.card h2{{margin-top:0;color:#00ff88;}}a{{color:#00d4ff;text-decoration:none;}}
</style></head><body><div class="c">
<h1>📚 EVCC-Smartload v{VERSION} Dokumentation</h1>
<a href="/docs/readme"><div class="card"><h2>📖 README</h2><p>Installation, Konfiguration, Features, API, FAQ</p></div></a>
<a href="/docs/changelog"><div class="card"><h2>📝 Changelog</h2><p>Was ist neu? Breaking Changes, neue Features</p></div></a>
<a href="/docs/api"><div class="card"><h2>🔌 API Referenz</h2><p>Alle Endpunkte mit Beispielen</p></div></a>
<p style="text-align:center;margin-top:30px;"><a href="/">← Dashboard</a></p>
</div></body></html>"""

    def _docs_page(self, path: str) -> str:
        if path == "/docs/api":
            return self._api_docs()
        name = path.replace("/docs/", "")
        filemap = {"readme": "README.md", "changelog": "CHANGELOG.md"}
        return self._render_md(filemap.get(name, "README.md"))

    def _render_md(self, filename: str) -> str:
        try:
            for p in [Path("/app") / filename, Path(__file__).parent.parent.parent / filename]:
                if p.exists():
                    content = p.read_text(encoding="utf-8")
                    break
            else:
                content = f"# Fehler\nDokument nicht gefunden: {filename}"
        except Exception as e:
            content = f"# Fehler\n{e}"
        h = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        h = re.sub(r"^# (.+)$", r"<h1>\1</h1>", h, flags=re.M)
        h = re.sub(r"^## (.+)$", r"<h2>\1</h2>", h, flags=re.M)
        h = re.sub(r"^### (.+)$", r"<h3>\1</h3>", h, flags=re.M)
        h = re.sub(r"```(\w+)?\n(.*?)\n```", r"<pre><code>\2</code></pre>", h, flags=re.S)
        h = re.sub(r"`([^`]+)`", r"<code>\1</code>", h)
        h = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', h)
        h = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", h)
        h = re.sub(r"\*([^\*]+)\*", r"<em>\1</em>", h)
        h = "<p>" + h.replace("\n\n", "</p><p>") + "</p>"
        return f"""<!DOCTYPE html><html><head><title>{filename}</title><meta charset="utf-8">
<style>body{{font-family:-apple-system,sans-serif;margin:20px;background:#1a1a2e;color:#eee;line-height:1.6;}}
.c{{max-width:900px;margin:0 auto;}}h1{{color:#00d4ff;border-bottom:2px solid #00d4ff;padding-bottom:10px;}}
h2{{color:#00ff88;margin-top:30px;}}h3{{color:#ffaa00;}}
code{{background:#0f3460;padding:2px 6px;border-radius:3px;color:#00ff88;}}
pre{{background:#0f3460;padding:15px;border-radius:8px;overflow-x:auto;}}pre code{{background:none;padding:0;}}
a{{color:#00d4ff;}}</style></head><body><div class="c">{h}
<p style="text-align:center;margin-top:30px;"><a href="/docs">← Dokumentation</a> | <a href="/">Dashboard</a></p>
</div></body></html>"""

    def _api_docs(self) -> str:
        return f"""<!DOCTYPE html><html><head><title>API – EVCC-Smartload</title><meta charset="utf-8">
<style>body{{font-family:-apple-system,sans-serif;margin:20px;background:#1a1a2e;color:#eee;}}
.c{{max-width:1000px;margin:0 auto;}}h1{{color:#00d4ff;}}
.ep{{background:#16213e;padding:20px;margin:20px 0;border-radius:8px;}}
.m{{display:inline-block;padding:4px 12px;border-radius:4px;font-weight:bold;color:#000;}}
.get{{background:#00ff88;}}.post{{background:#00d4ff;}}
.path{{font-family:monospace;color:#ffaa00;font-size:1.1em;}}
pre{{background:#0f3460;padding:15px;border-radius:6px;}}code{{color:#00ff88;}}
</style></head><body><div class="c">
<h1>🔌 EVCC-Smartload API v{VERSION}</h1>
<p>Basis-URL: <code>http://homeassistant:{self.cfg.api_port}</code></p>
<div class="ep"><span class="m get">GET</span> <span class="path">/status</span><p>Vollständiger System-Status inkl. RL, Percentile, Sequencer-Status</p></div>
<div class="ep"><span class="m get">GET</span> <span class="path">/vehicles</span><p>Alle Fahrzeuge mit SoC, Quelle, manuelle Overrides</p></div>
<div class="ep"><span class="m get">GET</span> <span class="path">/slots</span><p>Ladeslots für alle Geräte</p></div>
<div class="ep"><span class="m get">GET</span> <span class="path">/sequencer</span><p>v5: Lade-Zeitplan, Anfragen, Ruhezeit-Status</p></div>
<div class="ep"><span class="m get">GET</span> <span class="path">/drivers</span><p>v5: Fahrer-Konfiguration (keine Secrets)</p></div>
<div class="ep"><span class="m get">GET</span> <span class="path">/rl-devices</span><p>RL Device Control pro Gerät</p></div>
<div class="ep"><span class="m post">POST</span> <span class="path">/vehicles/manual-soc</span>
<pre><code>{{"vehicle": "ORA_03", "soc": 45}}</code></pre></div>
<div class="ep"><span class="m post">POST</span> <span class="path">/sequencer/request</span>
<p>v5: Manuell Ladewunsch eintragen</p>
<pre><code>{{"vehicle": "KIA_EV9", "target_soc": 80}}</code></pre></div>
<div class="ep"><span class="m post">POST</span> <span class="path">/sequencer/cancel</span>
<pre><code>{{"vehicle": "KIA_EV9"}}</code></pre></div>
<div class="ep"><span class="m post">POST</span> <span class="path">/rl-override</span>
<pre><code>{{"device": "battery", "mode": "manual_lp"}}</code></pre></div>
<p style="text-align:center;margin-top:50px;"><a href="/docs" style="color:#00d4ff;">← Dokumentation</a></p>
</div></body></html>"""


# =============================================================================
# Charge-slot calculation (stateless helper — unchanged from v4)
# =============================================================================

def _calculate_charge_slots(tariffs, cfg, last_state, vehicles, solar_forecast=None) -> dict:
    now = datetime.now(timezone.utc)
    buckets: Dict[datetime, List[float]] = defaultdict(list)
    for t in tariffs:
        try:
            s = t.get("start", "")
            val = float(t.get("value", 0))
            if s.endswith("Z"):
                start = datetime.fromisoformat(s.replace("Z", "+00:00"))
            elif "+" in s:
                start = datetime.fromisoformat(s)
            else:
                start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            hour = start.replace(minute=0, second=0, microsecond=0)
            if hour >= now - timedelta(hours=1):
                buckets[hour].append(val)
        except Exception:
            continue
    hourly = sorted([(h, sum(v)/len(v)) for h, v in buckets.items()])
    if not hourly:
        return {"error": "Keine Preisdaten verfügbar"}

    deadline_hour = cfg.ev_charge_deadline_hour
    if now.hour < deadline_hour:
        ev_deadline = now.replace(hour=deadline_hour, minute=0, second=0, microsecond=0)
    else:
        ev_deadline = (now + timedelta(days=1)).replace(hour=deadline_hour, minute=0, second=0, microsecond=0)

    bat_soc = last_state.battery_soc if last_state else 50
    pv_now_kw = (last_state.pv_power / 1000) if last_state else 0
    home_now_kw = (last_state.home_power / 1000) if last_state else 1.5

    solar_hourly_kw = {}
    if solar_forecast:
        raw_vals = [float(t.get("value", 0)) for t in solar_forecast if float(t.get("value", 0)) > 0]
        unit_factor = 0.001 if raw_vals and sorted(raw_vals)[len(raw_vals) // 2] > 100 else 1.0
        parsed_entries = []
        for t in solar_forecast:
            try:
                s = t.get("start", "")
                val = float(t.get("value", 0))
                if val <= 0:
                    continue
                if s.endswith("Z"):
                    start = datetime.fromisoformat(s.replace("Z", "+00:00"))
                elif "+" in s:
                    start = datetime.fromisoformat(s)
                else:
                    start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
                hour = start.replace(minute=0, second=0, microsecond=0)
                if hour >= now:
                    parsed_entries.append((hour, val * unit_factor))
            except Exception:
                continue
        for hour, val_kw in parsed_entries:
            solar_hourly_kw[hour] = max(solar_hourly_kw.get(hour, 0), val_kw)

    if solar_hourly_kw:
        pv_energy_forecast_kwh = min(50.0, sum(max(0, kw - home_now_kw) for kw in solar_hourly_kw.values()))
        forecast_source = "evcc"
    else:
        pv_surplus_kw = max(0, pv_now_kw - home_now_kw)
        local_hour = now.astimezone().hour if now.tzinfo else now.hour
        pv_hours_remaining = max(0, 19 - max(local_hour, 7))
        pv_energy_forecast_kwh = pv_surplus_kw * 0.6 * pv_hours_remaining if pv_now_kw > 0.5 else 0
        forecast_source = "estimate"

    pv_surplus_now_kw = max(0, pv_now_kw - home_now_kw)

    result = {
        "timestamp": now.isoformat(),
        "deadline": ev_deadline.strftime("%H:%M"),
        "hours_until_deadline": round((ev_deadline - now).total_seconds() / 3600, 1),
        "energy_balance": {
            "pv_now_kw": round(pv_now_kw, 2),
            "home_now_kw": round(home_now_kw, 2),
            "pv_surplus_kw": round(pv_surplus_now_kw, 2),
            "pv_forecast_kwh": round(pv_energy_forecast_kwh, 1),
            "forecast_source": forecast_source,
            "solar_hours": len(solar_hourly_kw),
        },
        "battery": _device_slots(
            "Hausbatterie", cfg.battery_capacity_kwh, bat_soc,
            cfg.battery_max_soc, cfg.battery_charge_power_kw,
            cfg.battery_max_price_ct, hourly, None, "🔋",
            pv_offset_kwh=min(pv_energy_forecast_kwh * 0.3, 5),
        ),
        "vehicles": {},
    }

    pv_for_vehicles = max(0, pv_energy_forecast_kwh * 0.7)
    n_charging = sum(1 for v in vehicles.values() if v.get_effective_soc() < cfg.ev_target_soc)
    pv_per_vehicle = min(pv_for_vehicles / max(1, n_charging), 100)

    for name, v in vehicles.items():
        needs_charge = v.get_effective_soc() < cfg.ev_target_soc
        result["vehicles"][name] = _device_slots(
            name, v.capacity_kwh, v.get_effective_soc(), cfg.ev_target_soc,
            11, cfg.ev_max_price_ct, hourly, ev_deadline,
            "🔌" if v.connected_to_wallbox else "🚗",
            v.last_update.isoformat() if v.last_update else None,
            pv_offset_kwh=pv_per_vehicle if needs_charge else 0,
        )
        result["vehicles"][name]["last_poll"] = v.last_poll.isoformat() if v.last_poll else None
        result["vehicles"][name]["poll_age"] = v.get_poll_age_string()
        result["vehicles"][name]["data_age"] = v.get_data_age_string()
        result["vehicles"][name]["is_stale"] = v.is_data_stale() and not v.connected_to_wallbox
        result["vehicles"][name]["data_source"] = v.data_source
        result["vehicles"][name]["connected"] = v.connected_to_wallbox
        result["vehicles"][name]["charging"] = v.charging

    # Battery-to-EV
    total_ev_need = sum(
        max(0, (cfg.ev_target_soc - v.get_effective_soc()) / 100 * v.capacity_kwh)
        for v in vehicles.values()
        if v.get_effective_soc() > 0 or v.connected_to_wallbox or v.data_source == "direct_api"
    )
    bat_available_kwh = max(0, (bat_soc - cfg.battery_min_soc) / 100 * cfg.battery_capacity_kwh)
    round_trip_eff = cfg.battery_charge_efficiency * cfg.battery_discharge_efficiency
    if hourly:
        all_prices_ct = sorted([p * 100 for _, p in hourly])
        cheap_n = max(1, len(all_prices_ct) // 3)
        avg_charge_price_ct = sum(all_prices_ct[:cheap_n]) / cheap_n
    else:
        avg_charge_price_ct = cfg.battery_max_price_ct
    bat_to_ev_cost_ct = avg_charge_price_ct / round_trip_eff
    current_price_ct = (last_state.current_price * 100) if last_state else 30.0
    upcoming_prices = [p * 100 for _, p in hourly[:6]] if hourly else [current_price_ct]
    avg_upcoming_ct = sum(upcoming_prices) / len(upcoming_prices) if upcoming_prices else current_price_ct
    savings_vs_grid_ct = current_price_ct - bat_to_ev_cost_ct
    is_profitable = savings_vs_grid_ct >= cfg.battery_to_ev_min_profit_ct
    bat_for_ev_kwh = min(bat_available_kwh, total_ev_need) if is_profitable else 0

    result["battery_to_ev"] = {
        "available_kwh": round(bat_available_kwh, 1),
        "ev_need_kwh": round(total_ev_need, 1),
        "usable_kwh": round(bat_for_ev_kwh, 1),
        "bat_cost_ct": round(bat_to_ev_cost_ct, 1),
        "grid_price_ct": round(current_price_ct, 1),
        "avg_upcoming_ct": round(avg_upcoming_ct, 1),
        "savings_ct_per_kwh": round(savings_vs_grid_ct, 1),
        "round_trip_efficiency": round(round_trip_eff * 100, 1),
        "is_profitable": is_profitable,
        "min_profit_ct": cfg.battery_to_ev_min_profit_ct,
        "dynamic_limit_enabled": cfg.battery_to_ev_dynamic_limit,
        "recommendation": (
            f"🔋→🚗 Batterie-Entladung lohnt sich! Spare ~{savings_vs_grid_ct:.0f}ct/kWh "
            f"({bat_for_ev_kwh:.0f} kWh verfügbar)"
            if is_profitable and bat_for_ev_kwh > 1 else
            f"⚡ Netzstrom günstiger ({current_price_ct:.0f}ct) als Batterie ({bat_to_ev_cost_ct:.0f}ct inkl. Verluste)"
            if total_ev_need > 1 else
            "✅ Kein EV-Ladebedarf"
        ),
    }

    if cfg.battery_to_ev_dynamic_limit and total_ev_need > 0.5:
        bat_cap = cfg.battery_capacity_kwh
        floor = cfg.battery_to_ev_floor_soc
        home_kw = (last_state.home_power / 1000) if last_state and last_state.home_power else 1.0
        solar_surplus_kwh = calc_solar_surplus_kwh(solar_forecast, home_kw)
        solar_refill_pct = min(90, (solar_surplus_kwh / bat_cap) * 100) if bat_cap > 0 else 0
        cheap_hours = sum(1 for _, p in hourly if p * 100 <= cfg.battery_max_price_ct)
        grid_refill_kwh = cheap_hours * cfg.battery_charge_power_kw * cfg.battery_charge_efficiency
        grid_refill_pct = min(90, (grid_refill_kwh / bat_cap) * 100) if bat_cap > 0 else 0
        total_refill_pct = min(80, solar_refill_pct + grid_refill_pct)
        safe_discharge = total_refill_pct * 0.8
        dynamic_floor = max(floor, int(bat_soc - safe_discharge))
        ev_need_pct_raw = (total_ev_need / (bat_cap * round_trip_eff)) * 100 if bat_cap > 0 else 0
        ev_need_pct = min(ev_need_pct_raw, 100)
        buffer_soc = max(floor, int(bat_soc - ev_need_pct), dynamic_floor)
        priority_soc = max(cfg.battery_min_soc, floor - 5)
        result["battery_to_ev"]["dynamic_limits"] = {
            "buffer_soc": buffer_soc, "priority_soc": priority_soc,
            "buffer_start_soc": min(90, buffer_soc + 10), "floor_soc": floor,
            "solar_refill_pct": round(solar_refill_pct, 1),
            "grid_refill_pct": round(grid_refill_pct, 1),
            "total_refill_pct": round(total_refill_pct, 1),
            "ev_need_pct": round(ev_need_pct, 1),
            "cheap_hours": cheap_hours, "solar_surplus_kwh": round(solar_surplus_kwh, 1),
        }

    return result


def _device_slots(name, capacity, soc, target, power_kw, max_price_ct,
                  hourly, deadline, icon, last_update=None, pv_offset_kwh=0) -> dict:
    gross_need = max(0, (target - soc) / 100 * capacity)
    net_need = max(0, gross_need - pv_offset_kwh)
    hours_needed = int(net_need / power_kw * 1.2) + 1 if net_need > 1 else 0
    base = {"name": name, "icon": icon, "current_soc": soc, "target_soc": target,
            "capacity_kwh": capacity, "need_kwh": round(net_need, 1),
            "gross_need_kwh": round(gross_need, 1), "pv_offset_kwh": round(pv_offset_kwh, 1),
            "hours_needed": hours_needed, "last_update": last_update}
    if hours_needed == 0:
        return {**base, "status": "✅ Vollständig geladen", "slots": [],
                "total_cost_eur": 0, "avg_price_ct": 0}
    if deadline:
        eligible = [(h, p) for h, p in hourly if h < deadline and p <= max_price_ct / 100]
    else:
        eligible = [(h, p) for h, p in hourly[:24] if p <= max_price_ct / 100]
    if not eligible:
        return {**base, "status": f"⚠️ Keine Stunden unter {max_price_ct}ct", "slots": [],
                "total_cost_eur": 0, "avg_price_ct": 0}
    chosen = sorted(sorted(eligible, key=lambda x: x[1])[:hours_needed], key=lambda x: x[0])
    kwh_per = min(net_need, hours_needed * power_kw) / len(chosen) if chosen else 0
    total_cost = sum(kwh_per * p for _, p in chosen)
    avg_price = sum(p for _, p in chosen) / len(chosen) * 100
    now = datetime.now(timezone.utc)
    slots = [{
        "hour": h.strftime("%H:%M"), "hour_end": (h + timedelta(hours=1)).strftime("%H:%M"),
        "price_ct": round(p * 100, 1), "power_kw": power_kw,
        "energy_kwh": round(kwh_per, 1), "cost_eur": round(kwh_per * p, 2),
        "is_now": h.hour == now.hour and h.date() == now.date(),
    } for h, p in chosen]
    pv_text = f" (inkl. ~{pv_offset_kwh:.0f}kWh PV)" if pv_offset_kwh > 0.5 else ""
    status = f"✅ {len(chosen)} Stunden geplant{pv_text}" if len(chosen) >= hours_needed else f"⚠️ Nur {len(chosen)}/{hours_needed} Stunden"
    return {**base, "status": status, "slots": slots,
            "total_cost_eur": round(total_cost, 2), "avg_price_ct": round(avg_price, 1),
            "threshold_ct": round(max(p for _, p in chosen) * 100, 1)}
