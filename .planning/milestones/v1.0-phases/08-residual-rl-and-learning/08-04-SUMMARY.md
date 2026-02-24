---
phase: 08-residual-rl-and-learning
plan: "04"
subsystem: web-dashboard
tags: [dashboard, rl, learning, german-ui, api-endpoints]
dependency_graph:
  requires: [08-03]
  provides: [lernen-tab, rl-learning-endpoint, rl-audit-endpoint]
  affects: [web/server.py, web/templates/dashboard.html, web/static/app.js]
tech_stack:
  added: []
  patterns:
    - lazy-load tab pattern (switchTab triggers fetch, matching Phase 6 Plan/Historie tabs)
    - None-guard API endpoints (getattr + is not None checks prevent crash when learners absent)
    - German decimal comma formatting (replace('.', ',') for all EUR values)
key_files:
  created: []
  modified:
    - evcc-smartload/rootfs/app/web/server.py
    - evcc-smartload/rootfs/app/web/templates/dashboard.html
    - evcc-smartload/rootfs/app/web/static/app.js
decisions:
  - "ausstehend displayed for None metrics (win_rate_7d, avg_daily_savings_eur) when insufficient data — not 0 or NaN"
  - "Lernen tab uses lazy-load pattern: fetchAndRenderLernen() called on switchTab('lernen') activation"
  - "SSE update refreshes Lernen tab only when tab is visible (display !== 'none' guard)"
  - "audit.checks dict accessed by key per check type (min_soc, departure_target, delta_clip, win_rate)"
  - "Confidence bar colors: green >= 0.8, amber >= 0.5, red < 0.5"
metrics:
  duration: 3 min
  completed: 2026-02-23
  tasks_completed: 2
  files_modified: 3
---

# Phase 8 Plan 04: Dashboard Lernen Tab with RL Performance Metrics Summary

GET /rl-learning and /rl-audit endpoints added to server.py; fourth "Lernen" dashboard tab added with shadow mode countdown, Gewinnrate/Tagesersparnis/Kumulierte Ersparnis metrics, Sicherheitsprüfung checklist, and Prognose-Qualität confidence bars — all in German.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add GET /rl-learning and /rl-audit endpoints to server.py | a76533c | server.py |
| 2 | Add Lernen tab to dashboard and rendering logic | 1d310cf | dashboard.html, app.js |

## Outcome

### Task 1: API Endpoints

- `_api_rl_learning()` returns complete RL learning status: mode, shadow_days_elapsed, shadow_days_remaining, win_rate_7d, avg_daily_savings_eur, cumulative_savings_eur, audit, seasonal_cells_populated, forecast_confidence
- `_api_rl_audit()` returns detailed constraint audit or `{"available": False}` when agent unavailable
- Both endpoints use `getattr(self, attr, None)` pattern — never crash when learner components absent
- win_rate_7d returns `None` (not 0) when fewer than 10 comparisons exist (Pitfall 7 guard)
- `self.seasonal_learner`, `self.forecast_reliability`, `self.reaction_timing` declared as late attributes in `__init__`
- Routes added: `elif path == "/rl-learning"` and `elif path == "/rl-audit"` in `do_GET` handler

### Task 2: Dashboard Tab

- Fourth tab button "Lernen" added to `.tab-nav` in dashboard.html
- `<div id="tab-lernen" class="tab-content">` container with `lernenContent` div added
- CSS classes added for lernen-mode-badge, lernen-mode-shadow/advisory, lernen-metric, lernen-audit-*, lernen-confidence-*
- `fetchAndRenderLernen()` function fetches `/rl-learning` and populates lernenContent
- `_renderLernenWidget(data)` builds full widget HTML with:
  - Mode badge: "Beobachtung" (shadow) + days remaining, or "Beratung" (advisory)
  - Gewinnrate (7 Tage), Tagesersparnis (Ø), Kumulierte Ersparnis metrics with "ausstehend" for null values
  - "ca." prefix for savings estimates (consistent with Phase 6 convention)
  - Sicherheitsprüfung checklist: 4 checks (SoC-Mindestgrenze, Abfahrtsziel, Korrekturbereich, Positive Gewinnrate) with pass (✓)/fail (✗)/pending (—) icons
  - Prognose-Qualität confidence bars for PV, Verbrauch, Preis with color-coded fill
  - Saisonale Zellen count
- `switchTab()` updated to include 'lernen' in tabs array and call `fetchAndRenderLernen()`
- `applySSEUpdate()` refreshes Lernen tab if currently visible
- German decimal comma: `.replace('.', ',')` used for all EUR values
- Inline `switchTab` fallback in dashboard.html updated to include 'lernen'

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

```
PASS: server.py RL endpoints verified
PASS: Dashboard Lernen tab verified
ALL VERIFICATIONS PASSED
```

## Self-Check: PASSED

- [x] `evcc-smartload/rootfs/app/web/server.py` — modified (endpoints added)
- [x] `evcc-smartload/rootfs/app/web/templates/dashboard.html` — modified (Lernen tab + CSS)
- [x] `evcc-smartload/rootfs/app/web/static/app.js` — modified (fetchAndRenderLernen + _renderLernenWidget + switchTab update)
- [x] Commit a76533c — `feat(08-04): add GET /rl-learning and /rl-audit endpoints to server.py`
- [x] Commit 1d310cf — `feat(08-04): add Lernen tab to dashboard with RL performance widget`
