# Roadmap: SmartLoad v6

## Milestones

- ✅ **v1.0 MVP** — Phases 1-8.1 (shipped 2026-02-24)
- ✅ **v1.1 Smart EV Charging & evcc Control** — Phases 9-12 (shipped 2026-02-27)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-8.1) — SHIPPED 2026-02-24</summary>

- [x] Phase 1: State Infrastructure (2/2 plans) — completed 2026-02-22
- [x] Phase 2: Vehicle Reliability (2/2 plans) — completed 2026-02-22
- [x] Phase 3: Data Foundation (3/3 plans) — completed 2026-02-22
- [x] Phase 4: Predictive Planner (3/3 plans) — completed 2026-02-22
- [x] Phase 4.1: Deploy Configuration (1/1 plan) — completed 2026-02-22
- [x] Phase 4.2: CI/CD Pipeline (1/1 plan) — completed 2026-02-23
- [x] Phase 4.3: Release Documentation (1/1 plan) — completed 2026-02-23
- [x] Phase 5: Dynamic Buffer (2/2 plans) — completed 2026-02-23
- [x] Phase 6: Decision Transparency (3/3 plans) — completed 2026-02-23
- [x] Phase 7: Driver Interaction (3/3 plans) — completed 2026-02-23
- [x] Phase 8: Residual RL and Learning (5/5 plans) — completed 2026-02-23
- [x] Phase 8.1: Seasonal Feedback + Phase 5 Verification (1/1 plan) — completed 2026-02-24

Full details: `milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Smart EV Charging & evcc Control (Phases 9-12) — SHIPPED 2026-02-27</summary>

- [x] Phase 9: Vehicle SoC Provider Fix (2/2 plans) — completed 2026-02-27
- [x] Phase 10: Poll Now Button + SoC Dashboard (2/2 plans) — completed 2026-02-27
- [x] Phase 11: evcc Mode Control + Override Detection (2/2 plans) — completed 2026-02-27
- [x] Phase 12: LP-Gated Battery Arbitrage (2/2 plans) — completed 2026-02-27

Full details: `milestones/v1.1-ROADMAP.md`

</details>

## Phase Details

### Phase 9: Vehicle SoC Provider Fix

**Goal**: Kia and Renault vehicles report accurate, current SoC at every LP decision cycle — regardless of whether the vehicle is physically connected to the wallbox

**Depends on**: Nothing (data quality foundation, independent)

**Requirements**: SOC-01, SOC-02

**Success Criteria** (what must be TRUE):
  1. Dashboard shows a non-stale Kia SoC after the vehicle has been away from home for over 1 hour — the value updates on the scheduled 60-minute background poll without requiring a manual action
  2. Renault SoC polling completes without re-authenticating on every cycle — only a single Gigya JWT exchange occurs at startup and on expiry; logs show token reuse between polls
  3. When Kia API returns a 429 rate-limit error, the provider backs off for 2 hours and logs the reason — no further API calls are made during the backoff window
  4. When Renault API returns a 401, the provider re-authenticates once and retries — the next scheduled poll succeeds without manual intervention
  5. The `/vehicles` API response includes `last_poll`, `last_successful_poll`, and `data_source` ("cache" | "live") fields for each vehicle

**Plans**: TBD

---

### Phase 10: Poll Now Button + SoC Dashboard

**Goal**: The user can trigger an immediate SoC refresh for any vehicle from the dashboard and always knows how old the displayed data is and where it came from

**Depends on**: Phase 9 (providers must be reliable before exposing the button)

**Requirements**: SOC-03, SOC-04

**Success Criteria** (what must be TRUE):
  1. Clicking "Poll Now" for a vehicle triggers an async SoC fetch — the dashboard shows a spinner immediately and updates with the new SoC value within 30 seconds without any page reload
  2. Clicking "Poll Now" again within 5 minutes of the last poll shows a throttle message ("Throttled — retry in 4m 22s") — no API call is made to the vehicle manufacturer cloud
  3. Each vehicle row in the dashboard displays the timestamp of the last successful poll and a color-coded freshness indicator (green < 1h, yellow 1-4h, red > 4h)
  4. Each vehicle row shows the data source label ("API", "Wallbox", or "Manuell") so the user understands how the displayed SoC was obtained

**Plans**: TBD

---

### Phase 11: evcc Mode Control + Override Detection

**Goal**: SmartLoad actively controls the evcc charge mode (pv / minpv / now) according to the LP plan, and manual user changes in the evcc UI are detected and respected until the charging session ends — without SmartLoad fighting the user

**Depends on**: Phase 9 (accurate SoC feeds the mode selection logic)

**Requirements**: MODE-01, MODE-02, MODE-03, MODE-04, MODE-05

**Success Criteria** (what must be TRUE):
  1. When an EV connects and the current electricity price is below the configured threshold, SmartLoad sets evcc mode to "now" within the next decision cycle — logs show the price, threshold, and resulting mode decision
  2. After SmartLoad sets a mode, a user manually changes it in the evcc UI — SmartLoad does not overwrite the manual change on the next cycle; it logs "Override erkannt — SmartLoad pausiert EV-Modus-Steuerung"
  3. After the override session ends (EV disconnects or target SoC reached), SmartLoad resumes mode control on the next cycle and the LP plan accounts for any charge that occurred during the override
  4. On startup, SmartLoad reads the current evcc mode and adopts it as baseline — no mode command is sent on the first decision cycle; logs confirm "Startup: evcc mode adopted as baseline"
  5. The dashboard Status tab shows a banner "EV Override aktiv — SmartLoad ubernimmt nach Abkopplung" when an override is active, and the banner disappears once the override session ends

**Plans**: TBD

---

### Phase 12: LP-Gated Battery Arbitrage

**Goal**: The house battery co-discharges to supplement EV fast charging when the stored energy is cheaper than the current grid price, the LP plan authorizes discharge, and the battery will recover before it is needed again — never draining the battery at the wrong moment

**Depends on**: Phase 11 (arbitrage reads active evcc mode; mode control must be production-stable first)

**Requirements**: ARB-01, ARB-02, ARB-03, ARB-04

**Success Criteria** (what must be TRUE):
  1. When an EV is fast-charging ("now" mode) and the stored battery energy is cheaper than the current grid price (accounting for 85% round-trip efficiency), and the LP plan authorizes discharge, the house battery begins co-discharging — dashboard shows "Batterie speist EV (spare X ct/kWh)"
  2. When the LP plan shows a cheaper grid pricing window within the next 6 hours, battery-to-EV discharge does not activate even if the current spot price would otherwise justify it — the LP lookahead guard prevents premature discharge
  3. Battery-to-EV discharge stops and does not activate when the battery SoC is at or below max(battery_to_ev_floor_soc, dynamic_buffer_min_soc) — the reserve floor is never breached
  4. Battery-to-EV discharge and LP-planned grid discharge never activate simultaneously — mutual exclusion is enforced and logged when both would otherwise trigger in the same cycle
  5. DynamicBufferCalc and the arbitrage logic read the same buffer SoC floor value — no silent overwrites; any buffer SoC change is reflected in both systems within the same decision cycle

**Plans**: TBD

---

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. State Infrastructure | v1.0 | 2/2 | Complete | 2026-02-22 |
| 2. Vehicle Reliability | v1.0 | 2/2 | Complete | 2026-02-22 |
| 3. Data Foundation | v1.0 | 3/3 | Complete | 2026-02-22 |
| 4. Predictive Planner | v1.0 | 3/3 | Complete | 2026-02-22 |
| 4.1 Deploy Configuration | v1.0 | 1/1 | Complete | 2026-02-22 |
| 4.2 CI/CD Pipeline | v1.0 | 1/1 | Complete | 2026-02-23 |
| 4.3 Release Documentation | v1.0 | 1/1 | Complete | 2026-02-23 |
| 5. Dynamic Buffer | v1.0 | 2/2 | Complete | 2026-02-23 |
| 6. Decision Transparency | v1.0 | 3/3 | Complete | 2026-02-23 |
| 7. Driver Interaction | v1.0 | 3/3 | Complete | 2026-02-23 |
| 8. Residual RL and Learning | v1.0 | 5/5 | Complete | 2026-02-23 |
| 8.1 Seasonal Feedback | v1.0 | 1/1 | Complete | 2026-02-24 |
| 9. Vehicle SoC Provider Fix | 2/2 | Complete    | 2026-02-27 | — |
| 10. Poll Now Button + SoC Dashboard | 2/2 | Complete    | 2026-02-27 | — |
| 11. evcc Mode Control + Override Detection | v1.1 | 2/2 | Complete | 2026-02-27 |
| 12. LP-Gated Battery Arbitrage | v1.1 | 2/2 | Complete | 2026-02-27 |
