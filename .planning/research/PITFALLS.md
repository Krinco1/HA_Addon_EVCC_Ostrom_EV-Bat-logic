# Pitfalls Research

**Domain:** Home Energy Management System — Predictive Planning + Hybrid RL
**Researched:** 2026-02-22
**Confidence:** MEDIUM (research verified across multiple sources; some RL-specific findings are MEDIUM due to academic/practitioner gap)

---

## Critical Pitfalls

### Pitfall 1: Open-Loop Planner — Building a Static Day-Ahead Schedule Instead of Rolling Horizon

**What goes wrong:**
The planner computes a 24-48h schedule once per decision cycle and executes it without feedback. By hour 6, the real world (cloud came in, EV arrived early, consumption spike) has diverged from the plan, but the system keeps executing the stale schedule. This is the single most common failure in MPC/predictive energy management deployments.

**Why it happens:**
Rolling horizon adds complexity — you need to re-solve the optimization every cycle with updated state. A static day-ahead solve is simpler to implement and "looks done" in simulation where inputs are perfectly known.

**How to avoid:**
Implement true receding-horizon control: every decision cycle (15 min) re-optimizes the full horizon using the latest observed state (real battery SoC, real vehicle SoC, latest price/PV forecast). The plan is always computed forward from *now*, not from where you thought you'd be at this time. Never cache a plan for more than one cycle.

**Warning signs:**
- Planner computes "charge EV from 14:00-16:00" but EV arrived at 13:00 and nothing changes
- Battery reaches unexpected SoC (higher or lower than plan predicted) and optimizer doesn't notice
- Dashboard shows a timeline that was computed hours ago

**Phase to address:**
Predictive Planner implementation phase. Must be validated with a simulation harness that introduces deliberate mid-plan disturbances (early EV departure, cloud cover) and verifies the plan updates on the next cycle.

---

### Pitfall 2: Reward Function Captures Cost But Not Constraints — RL Learns Unsafe Behavior

**What goes wrong:**
The RL agent maximizes cumulative reward (minimize cost). Without explicit penalty terms, it discovers that discharging the house battery to 5% SoC during an expensive price spike is rewarded. Real-world consequence: battery over-discharged, no reserve for evening outage, battery degradation accelerates. In a residual/hybrid setup, the RL *correction* can push the optimizer toward constraint-violating actions even if the optimizer itself is safe.

**Why it happens:**
RL has no intrinsic concept of hard constraints. Reward shaping that focuses only on economic cost misses operational safety. The existing DQN agent in SmartLoad is already in shadow mode — this pitfall becomes live when RL corrections start affecting real decisions.

**How to avoid:**
Encode hard constraints as large negative rewards (penalty rewards), not soft suggestions. Specifically:
- Battery SoC below `battery_min_soc`: large fixed penalty per timestep (not just reduced future value)
- EV misses departure with required SoC: large one-time penalty
- Grid draw above configured limit: large penalty

Additionally, clip RL corrections: the residual output should be bounded to ±20% of the optimizer's planned action. This is the "tube constraint" from residual RL literature — it preserves the base planner's safety properties while allowing RL to refine economics.

**Warning signs:**
- RL agent in shadow mode consistently recommends battery SoC thresholds lower than configured minimum
- Q-values for actions that violate constraints are positive (they should be dominated by penalty)
- Training reward increases while real-world costs seem fine, but battery is cycling deeper than expected

**Phase to address:**
Hybrid RL integration phase. Before enabling live RL corrections, run a constraint-violation audit on the shadow agent's recommended actions over 30+ days of history.

---

### Pitfall 3: Catastrophic Forgetting During Seasonal Transitions

**What goes wrong:**
The RL agent learns summer behavior (long days, high PV, cheap noon, charge EVs at midday). When autumn starts, PV production drops and noon is no longer cheap relative to the day. The agent retrains on autumn data, rapidly overwriting summer knowledge. Then a brief sunny week in November arrives and the agent performs poorly because it has forgotten summer patterns.

In the existing SmartLoad system, the DQN agent's Q-table grows based on visited states. Summer and winter visit completely different regions of state space. A continual learning failure happens when frequent retraining on recent data erases infrequently-visited-but-valid states.

**Why it happens:**
Standard Q-learning (and neural network approaches) exhibit catastrophic forgetting: gradient updates on new data overwrite weights/values for old patterns. Seasonal data is episodic and non-stationary, making this worse than standard RL environments.

**How to avoid:**
- Use an **experience replay buffer with seasonal stratification**: keep a rolling buffer that explicitly retains samples from all four seasons, not just the most recent N samples. When sampling a training batch, sample proportionally across seasons.
- Implement **concept drift detection** (DDM or KSWIN): monitor forecast accuracy metrics. When drift is detected, increase the learning rate temporarily and sample more heavily from recent data. When drift stabilizes, reduce learning rate and resume balanced sampling.
- Never train exclusively on the last N days. Always include older seasonal samples even if downweighted.

**Warning signs:**
- System performance degrades every autumn/spring (transition periods)
- Q-table state visits become heavily concentrated in recent time window
- Planner recommendations that were optimal in summer are now ignored by RL corrections in winter, and vice versa

**Phase to address:**
Seasonal learning / RL maintenance phase. Build the stratified replay buffer from day one — retrofitting it after training is underway requires resetting the replay buffer.

---

### Pitfall 4: RL Bootstrap Loads All History at Once — OOM on Raspberry Pi

**What goes wrong:**
Already documented in CONCERNS.md: `bootstrap_from_influxdb` loads 168 hours of data unbounded, causing 5-10 minute startup and potential OOM on Raspberry Pi. With the new predictive planner adding more state features (price forecast vector, consumption forecast, dynamic buffer level), each bootstrap sample becomes larger. If the new planner's state space increases from 31 to 50+ features, memory usage increases proportionally.

**Why it happens:**
Bulk loading is simple to implement. Streaming/batching requires handling partial states and managing incremental updates.

**How to avoid:**
- Cap bootstrap to 72 hours maximum
- Sample every Nth row from InfluxDB during bootstrap (reservoir sampling): `LIMIT 1000` with timestamp-based sampling
- Stream in batches of 500 samples, train incrementally, then discard the batch
- Add startup progress logging: `Bootstrapping RL: loaded 200/1000 samples...`
- Monitor memory usage during bootstrap; add a hard cap (e.g., max 256 MB during bootstrap phase)

**Warning signs:**
- Startup time increases with each new feature added to SystemState
- Docker memory limit exceeded alerts from HA supervisor during first run
- InfluxDB query for bootstrap has no LIMIT clause

**Phase to address:**
Foundation/bugfix phase — before adding new planner features that expand state space. Fix this before the new planner lands.

---

### Pitfall 5: Dynamic Battery Buffer Miscalibrated — System Over-Discharges When It Matters Most

**What goes wrong:**
The dynamic buffer logic lowers the minimum battery SoC on sunny mornings (correctly — no need to keep reserve when PV is coming). But the PV forecast is wrong (unexpected clouds), the buffer is already depleted, and evening grid prices are now expensive. The battery has no reserve, the house draws from grid at peak price, and the buffer wasn't there for the scenario it was designed for.

The inverse failure: buffer is too conservative on days when it doesn't need to be, so the battery never discharges below 40%, and the EV can't charge because the system won't draw down the battery to fund cheap-rate EV charging.

**Why it happens:**
Dynamic buffer calibration requires accurate conditional probability estimates: "given current PV forecast quality, what is the probability PV will underperform by >20%?" This is hard to get right initially.

**How to avoid:**
- Start with conservative defaults: dynamic buffer should only *lower* the minimum from the static value when forecast confidence is HIGH (clear sky, low cloud probability)
- Add a "forecast confidence" signal: use the spread of the price forecast (if available from evcc) and cloud cover probability as confidence inputs
- Log every instance where buffer was lowered and whether PV subsequently underperformed; use this to tune the confidence threshold over time
- Hard floor: dynamic buffer must never go below 10% regardless of forecast confidence

**Warning signs:**
- Battery repeatedly hits near-zero SoC on days with unexpected cloud cover
- User reports system charged EV at expensive rates when battery was low
- Buffer lowering events correlate with forecast errors (trackable via InfluxDB)

**Phase to address:**
Dynamic buffer implementation phase. The buffer adjustment logic must be gated on forecast confidence from day one, not added as a refinement later.

---

### Pitfall 6: Multi-EV Scheduler Starves Low-Priority Vehicle During Human Overrides

**What goes wrong:**
Driver A overrides charge priority via Telegram ("charge my car now — I need to leave in 2 hours"). The sequencer grants this. Driver B's car was scheduled next in queue. Driver A's session runs over (car stays plugged in after reaching target SoC). Driver B's car never starts. No notification is sent to Driver B because the sequencer thinks it's waiting for Driver A to finish, which it technically is — but Driver A's car is full and staying plugged in.

The existing sequencer already has the documented bug of 15-minute transition delays. Combined with override handling, a low-priority EV can be starved for hours.

**Why it happens:**
Override handling is typically implemented as "bump this vehicle to front of queue" without considering the downstream impact on waiting vehicles. The sequencer has no concept of starvation prevention (maximum wait time).

**How to avoid:**
- Implement **starvation threshold**: if a vehicle has been waiting in queue for more than `starvation_minutes` (default: 60), escalate it to higher priority and notify the waiting driver via Telegram
- **Override expiry**: a human override should have a maximum duration (e.g., 90 minutes). After expiry, the sequencer reverts to planned order. Driver is notified with remaining time.
- **Wallbox vacancy detection**: if the currently-charging vehicle reaches target SoC but stays plugged in for more than 15 minutes, trigger an immediate transition check rather than waiting for the next decision cycle
- Track "queue wait time" per vehicle in sequencer state and expose it on the dashboard

**Warning signs:**
- Vehicle has been in "waiting" state for >1 hour with no charging start
- No Telegram notification was sent to waiting driver about expected charge start time
- Override was granted but no override expiry logic exists in the code

**Phase to address:**
Charge sequencer improvement phase. Fix this before exposing override via dashboard (expands the attack surface for starvation).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Bare `except Exception: pass` in RL agent save/load | Startup never fails | RL model corruption goes unnoticed for weeks; wrong decisions accumulate | Never — always log and surface errors |
| Q-table with all features as key (tuple discretization) | Simple implementation | State space explosion after adding planner features; Q-table grows unbounded | Only in proof-of-concept; must switch to function approximation or selective feature set before production RL |
| SQLite connection per method call in comparator | Simple to write | Database lock contention during rapid decision loops | Acceptable while comparator is only used for analytics; unacceptable if used in critical decision path |
| Static discretization bins hardcoded in rl_agent.py | Works with current state | New features added by planner silently break the Q-table (wrong bin counts) | Never — bins must be data-driven or validated with assertions on every startup |
| Decision cycle blocks on web server state update | Simple synchronous code | Web server hang cascades to delayed charging decisions | Never in production — async queue is required |
| No config validation on startup | Fast iteration during development | Invalid config (e.g., `battery_min_soc > battery_max_soc`) causes cryptic runtime crash | Never in a user-facing Home Assistant add-on |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| evcc REST API for price forecast | Assume forecast always covers 24h | evcc sometimes returns partial forecasts (6h or 12h). Planner must handle truncated forecasts gracefully: use what's available, flag reduced confidence on the rest |
| evcc REST API for PV forecast | Treat solar tariff forecast as actual PV generation forecast | The solar tariff is a *price* signal, not kWh production. PV generation must be estimated separately (from historical irradiance patterns) or sourced from a dedicated PV forecast API |
| Kia/Renault vehicle APIs | Poll aggressively to keep SoC fresh | These APIs enforce rate limits: 5-10 requests before 429/lockout. Implement exponential backoff + jitter. Cache the last successful response for 2-3 polling cycles if poll fails |
| evcc websocket for wallbox state | Treat websocket and REST as equivalent | Websocket events arrive out-of-order under load; REST is authoritative for planning. Use websocket for UI updates, REST for decision inputs |
| InfluxDB historical data for bootstrap | Query all data without time filter | Bootstrap must use `WHERE time > now() - 72h LIMIT 1000` — unbounded query causes OOM on Raspberry Pi |
| Telegram driver interaction | Send Telegram message and assume driver responded | Drivers may ignore messages. Planner must have a timeout (default: 30 minutes) after which it uses the last known departure/SoC information rather than waiting indefinitely |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Planner re-solves full 24h optimization on every dashboard refresh | Dashboard open = 3-4 full optimizer runs/minute; CPU pegged | Pre-compute plan once per decision cycle; serve cached plan to dashboard | Immediately on any system that doesn't have a dedicated CPU (Raspberry Pi 4) |
| Rolling price forecast stored as per-hour dict, re-parsed on each request | `/chart-data` latency increases as forecast length grows | Parse once at ingestion, store as typed list; serve pre-parsed structure | When forecast extends beyond 36 hours |
| RL Q-table serialized as pickle on every decision cycle | Decision loop slows to 30+ seconds after 6 months of operation | Serialize Q-table only on clean shutdown or every N cycles (not every cycle); use atomic write (temp file + rename) | After Q-table exceeds ~50K states (estimated 6-12 months of operation) |
| Vehicle polling blocks main thread during API timeout | Decision cycle freezes for 10-15s while waiting for Kia API timeout | Run all vehicle polling in isolated threads with hard timeout; main loop must never block on vehicle API | On first network issue with any vehicle provider |
| Optimization solver with no time limit | If price/PV forecast has 48h at 15-min resolution (192 time steps), solver can take minutes on constrained hardware | Add solver time limit (`timeout=5s`); if limit hit, fall back to greedy rule-based decision and log the event | On any hardware slower than Raspberry Pi 4 |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Telegram bot token in `drivers.yaml` plain text | Container filesystem compromise exposes token; token can be used to read/send messages to all registered drivers | Reference via HA secrets: `!secret telegram_token` in YAML; never log token values |
| API endpoints unauthenticated (`/status`, `/vehicles`, `/sequencer`) | Any device on local network can read battery SoC, vehicle data, pricing strategy | Add optional `X-API-Key` header; POST/mutation endpoints must require auth; document that port 8099 must not be exposed to WAN |
| InfluxDB credentials in `options.json` | HA config volume compromise exposes database | Enable `influxdb_ssl: true` by default; support environment-variable credential injection |
| Manual SoC override endpoint with no rate limiting | Rapid automated POST requests can flood the system or manipulate EV charge targets | Rate limit `/vehicles/manual-soc` to 10 requests/minute per source IP |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Showing the full 48h plan as a dense timeline with all decision factors | User sees 192 data points, 5 overlapping lines — gives up on understanding the plan | Progressive disclosure: show next 6h by default, allow zoom to 24h or 48h; highlight only inflection points (cheapest window, solar peak, EV charge slot) |
| Displaying RL confidence/shadow-mode output alongside planner output with no explanation | User doesn't know which number to trust; creates anxiety about system correctness | Show RL output only in an expert/debug view behind a toggle; main view shows "Planner says: charge EV 14:00-16:00" without surfacing RL internals |
| Alert for every planner re-optimization | User gets Telegram messages every 15 minutes; turns off notifications entirely | Only notify on *decision changes*: if plan changes significantly from previous cycle (EV charge window moved by >30 min, battery strategy changed), send one notification |
| "Battery buffer: 25%" with no explanation of why | User thinks the system has a bug or is misconfigured | Show contextual tooltip: "Buffer raised to 25% because tomorrow morning has low PV forecast confidence. This protects against overnight grid use." |
| Reporting savings in kWh instead of euros | Users don't intuitively map kWh to money; can't evaluate if the system is worth it | Report savings in euros per day/week/month alongside kWh; show "vs. dumb charging" comparison |
| Dashboard refresh rate too high (real-time updates every second) | Rapid layout shifts confuse users; mobile browsers drain battery | Update dashboard every 30-60 seconds; show "Last updated: 30s ago" instead of live counters |

---

## "Looks Done But Isn't" Checklist

- [ ] **Predictive planner:** Often missing rolling-horizon re-optimization. Verify: introduce a deliberate mid-cycle price change in test and confirm the plan updates on the next 15-min cycle.
- [ ] **Dynamic battery buffer:** Often missing forecast-confidence gating. Verify: simulate a day with bad PV forecast and confirm buffer is NOT lowered when forecast confidence is low.
- [ ] **Hybrid RL corrections:** Often missing constraint bounds on residual output. Verify: check that the maximum possible RL correction cannot push battery below `battery_min_soc` or EV above `ev_max_soc`.
- [ ] **Charge sequencer override:** Often missing starvation prevention. Verify: put two EVs in queue, override the first, let it complete charging but stay plugged in — confirm second EV starts within `starvation_minutes` without manual intervention.
- [ ] **Seasonal model:** Often missing stratified replay buffer. Verify: check that the replay buffer contains samples from all seasons, not just the last 30 days.
- [ ] **RL bootstrap:** Often missing memory cap and progress logging. Verify: on a Raspberry Pi 4, first-run startup must complete in under 3 minutes with memory usage under 256 MB.
- [ ] **Telegram departure query:** Often missing timeout fallback. Verify: send a departure query, do not respond — confirm system uses last-known departure info after 30 minutes and proceeds.
- [ ] **Dashboard plan visualization:** Often missing "why" explanations. Verify: for every planned charge/discharge window, the dashboard shows at least one sentence explaining the primary reason (price, solar, EV departure).
- [ ] **Config validation:** Often missing bounds checking. Verify: set `battery_min_soc = 110` in config — system must refuse to start with a clear error, not crash 10 minutes into operation.
- [ ] **Thread safety in web server:** Often "fixed" by adding a lock but forgetting to hold it during multi-field reads. Verify: run the dashboard under concurrent load (multiple browser tabs refreshing) and check for None values in vehicle SoC API responses.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Open-loop stale plan | LOW | Add re-optimization call at start of each decision cycle; no data loss |
| RL constraint violation (battery over-discharged) | MEDIUM | Hard-code safety floor in evcc command layer independent of RL; battery recovers on next charge cycle |
| Catastrophic forgetting (seasonal transition) | MEDIUM | Reset Q-table to zero, re-bootstrap from InfluxDB with 90-day stratified sample; system reverts to rule-based for ~1 week while retraining |
| RL bootstrap OOM on Raspberry Pi | LOW | Reduce bootstrap window in config, restart add-on; no persistent data loss |
| Dynamic buffer over-discharges battery | MEDIUM | Raise static `battery_min_soc` in config as emergency brake; tune dynamic logic with increased forecast-confidence threshold |
| EV starvation from override | LOW | Driver sends Telegram override for starved vehicle; add starvation prevention before next release |
| Q-table corruption (silent exception on save) | HIGH | Q-table must be rebuilt from scratch via bootstrap; 1-2 weeks of suboptimal decisions during retraining |
| Config validation failure | LOW | User corrects config value; no state loss |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Open-loop static plan | Predictive Planner phase | Integration test: inject mid-cycle price change, confirm plan updates |
| RL unsafe actions / constraint violations | Hybrid RL integration phase | Shadow-mode audit: scan 30 days of shadow recommendations for constraint violations |
| Catastrophic forgetting | Seasonal learning phase | Build stratified replay buffer; verify buffer contains multi-season samples at month 3 |
| RL bootstrap OOM | Foundation/bugfix phase (first) | Measure startup time and peak memory on Raspberry Pi 4 before adding new features |
| Dynamic buffer miscalibration | Dynamic buffer phase | Simulate low-confidence forecast days; verify buffer is not lowered below static minimum |
| Multi-EV starvation / override chaos | Charge sequencer improvement phase | Manual test: two-vehicle queue with override on first vehicle |
| Q-table corruption (silent exceptions) | Foundation/bugfix phase (first) | Replace bare exception handlers; add health-check endpoint that validates Q-table integrity |
| Dashboard information overload | Dashboard phase | User test: ask a non-technical user to explain what the system will do in the next 4 hours |
| Seasonal concept drift | Seasonal learning phase | Monitor forecast error metrics across autumn/spring transitions in production |
| Thread-safety race condition in web server | Foundation/bugfix phase (first) | Concurrent load test: 5 simultaneous dashboard clients for 60 seconds, check for None/NaN in responses |

---

## Sources

- [Practical Challenges of MPC for Grid Applications — Lawrence Berkeley National Lab, 2024](https://eta-publications.lbl.gov/sites/default/files/2024-09/practical_challenges_of_model_predictive_control.pdf)
- [Reinforcement Learning in EV Energy Management — Frontiers in Future Transportation, 2025](https://www.frontiersin.org/journals/future-transportation/articles/10.3389/ffutr.2025.1555250/full)
- [Continual Learning for Energy Management Systems — ScienceDirect, 2025](https://www.sciencedirect.com/science/article/pii/S0306261925001886)
- [Reward Shaping-Based Actor-Critic DRL for Residential Energy Management — IEEE Xplore](https://ieeexplore.ieee.org/iel7/9424/4389054/09797851.pdf)
- [Safe RL in Power and Energy Systems — Engineering Applications of AI, 2025](https://dl.acm.org/doi/10.1016/j.engappai.2025.110091)
- [Overview of RL for Smart Home EMS — ScienceDirect, 2024](https://www.sciencedirect.com/science/article/abs/pii/S1364032124003745)
- [Concept Drift Monitoring for Industrial Load Forecasting — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2212827124012186)
- [Mitigating Concept Drift in Smart Grids — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2352484724008928)
- [Data-Backed Guide: SOC Window vs Cycle Life in Home Batteries — Anern Store](https://www.anernstore.com/blogs/diy-solar-guides/data-soc-window-cycle-life-home)
- [Optimize DoD for Battery ESS Cycle Life — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2352152X23025422)
- [Residual Reinforcement Learning — Emergent Mind](https://www.emergentmind.com/topics/residual-reinforcement-learning-rl)
- [Apprenticeship-RL for HEV Energy Management — ScienceDirect, 2023](https://www.sciencedirect.com/science/article/abs/pii/S0306261923005913)
- [Energy Dashboard UX Best Practices — UXPin, 2025](https://www.uxpin.com/studio/blog/dashboard-design-principles/)
- [Energy Management Dashboard Design — Aufait UX](https://www.aufaitux.com/blog/energy-management-dashboard-design/)
- [Multi-EV Scheduling via Stochastic Queueing — Nature Scientific Reports, 2025](https://www.nature.com/articles/s41598-025-04725-7)
- [MPC Rolling Horizon: Open-Loop Infeasibility — arXiv, 2025](https://arxiv.org/pdf/2502.02133)
- SmartLoad codebase CONCERNS.md (internal analysis, 2026-02-22)

---

*Pitfalls research for: Home Energy Management System — Predictive Planning + Hybrid RL (SmartLoad v6)*
*Researched: 2026-02-22*
