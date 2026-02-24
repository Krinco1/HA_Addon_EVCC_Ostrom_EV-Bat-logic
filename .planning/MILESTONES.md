# Milestones

## v1.0 MVP (Shipped: 2026-02-24)

**Phases completed:** 12 phases, 27 plans
**Files modified:** 65 | **LOC:** ~15,700 (Python + JS + HTML)
**Timeline:** 31 days (2026-01-24 → 2026-02-24) | **Commits:** 240
**Git range:** 2936b9e → e43cdcc

**Delivered:** SmartLoad v6 — predictive 24-48h energy management system with LP optimizer, dynamic battery buffer, decision transparency dashboard, driver interaction via Telegram, and residual RL learning.

**Key accomplishments:**
1. Thread-safe state infrastructure — RLock-guarded StateStore with SSE push eliminates race conditions
2. 24-48h predictive LP planner — HiGHS LP optimizer replaces static euro price limits with joint battery + EV dispatch
3. Data-driven forecasting — Consumption from InfluxDB/HA history and PV from evcc solar tariff feed the planner
4. Dynamic battery buffer — Minimum SoC adapts to PV confidence, price spread, and time of day
5. Decision transparency — Gantt-chart timeline, German per-slot explanations, planned-vs-actual history
6. Driver interaction and learning — Boost override, Telegram departure queries, urgency-based multi-EV, residual RL with seasonal learning

**Known Tech Debt:**
- Dead code: `rl_bootstrap_max_records` config field + `bootstrap_from_influxdb()` (retired by Phase 8-03)
- Orphaned `/departure-times` REST endpoint (no frontend consumer)
- Visual verification pending for SVG charts, Gantt tooltips, Lernen tab widgets
- See `milestones/v1.0-MILESTONE-AUDIT.md` for full details

**Archives:**
- `milestones/v1.0-ROADMAP.md`
- `milestones/v1.0-REQUIREMENTS.md`
- `milestones/v1.0-MILESTONE-AUDIT.md`

---

