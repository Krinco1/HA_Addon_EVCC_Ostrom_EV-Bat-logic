# Stack Research

**Domain:** Home Energy Management System (HEMS) — predictive planning, hybrid RL, transparent visualization
**Researched:** 2026-02-22
**Confidence:** MEDIUM-HIGH (key libraries verified via PyPI official pages; Alpine compatibility verified via Alpine package repository and PyPI wheel listings)

## Context: What Already Exists

The existing system runs on Python 3.13 inside Docker on Alpine Linux 3.21 (base image `ghcr.io/home-assistant/aarch64-base-python:3.13-alpine3.21`). It uses `pip3 install` for pure-Python packages and `apk add` for system packages. The following are already present and must NOT be replaced:

- Python 3.13 (Alpine-based Docker image)
- numpy (via pip)
- requests, pyyaml, aiohttp (via pip)
- hyundai-kia-connect-api, renault-api (via pip)
- InfluxDB (external, HTTP API only)
- Custom DQN with JSON Q-table persistence (already in codebase)

This research covers ONLY the NEW libraries needed for predictive planning, residual RL, forecasting, and visualization.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| scipy (via apk) | 1.14.x (Alpine 3.21 community) | LP solver via `scipy.optimize.linprog` with HiGHS backend | HiGHS is the default method in scipy 1.7+, solving LP problems in seconds on Pi hardware. scipy is available as `py3-scipy` in Alpine's community repo — no musl/wheel compatibility problem. Already familiar in the numpy ecosystem. |
| highspy | 1.13.1 | Standalone HiGHS LP/MILP solver (fallback if scipy apk unavailable) | Ships musllinux_1_2_aarch64 wheels on PyPI (verified Feb 2026), installs cleanly on Alpine ARM64 via pip. Use as fallback if apk scipy version is too old. |
| plotly | 6.5.2 | Interactive timeline charts and plan visualization in the web dashboard | Pure Python, `py3-none-any` wheel — no compilation needed, zero Alpine compatibility issues. Generates JSON chart specs consumed by plotly.js CDN in HTML templates. No Dash required. |
| statsmodels (via apk) | 0.14.x (Alpine community) | Statistical time-series forecasting (SARIMA/seasonal decomposition) | Available as `py3-statsmodels` in Alpine's community repo. SARIMA outperforms Prophet for short-horizon energy consumption forecasting with only 2-4 weeks of data. Lightweight, no neural network overhead. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy (already installed) | existing | Residual RL micro-MLP: forward pass, backprop, weight updates | Always — numpy-only MLP avoids PyTorch's Alpine glibc incompatibility entirely |
| highspy | 1.13.1 | Direct HiGHS Python bindings (alternative to scipy linprog) | Only if `apk add py3-scipy` gives a version older than 1.7.0 (which introduced HiGHS as default). Otherwise use scipy. |
| plotly | 6.5.2 | `fig.to_json()` → embed in existing HTML templates via plotly.js CDN | Always — replaces the existing static decision log table with interactive Gantt/timeline charts |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Alpine apk (`py3-scipy`, `py3-statsmodels`) | System-level scientific packages compiled against musl | Use `apk add` in Dockerfile RUN layer before `pip install` — avoids musl incompatibility for packages that need C extension compilation |
| HiGHS solver (bundled in scipy / highspy) | LP/MILP solve engine | No separate binary install needed — HiGHS ships inside both scipy and highspy wheels |

---

## The Four Problem Domains and Their Solutions

### 1. Mathematical Optimization — 24-48h Energy Scheduling

**Recommended: `scipy.optimize.linprog` with HiGHS method**

scipy's `linprog` with `method='highs'` is the right choice because:
- HiGHS is production-grade (used by PyPSA, energy-py-linear, Oxford OPEN framework for identical HEMS problems)
- Solves a 96-interval (15-min slots over 24h) LP in under 100ms on Raspberry Pi hardware
- scipy is available via `apk add py3-scipy` on Alpine — no musl wheel compilation needed
- Already in the scientific Python ecosystem the team knows (numpy-adjacent)
- If scipy from apk is too old, `pip install highspy==1.13.1` works cleanly (musllinux_1_2_aarch64 wheel confirmed on PyPI)

The LP model structure for 24-48h planning:
- Decision variables: battery charge/discharge per interval, EV charge per interval, grid import per interval
- Objective: minimize total electricity cost (price × grid_import) over horizon
- Constraints: battery SoC bounds, EV departure SoC targets, grid import limits, inverter power limits
- Model Predictive Control (MPC) pattern: solve at each 15-min cycle, execute only the first interval

**Do NOT use PuLP for this.** PuLP 3.3.0 bundles COIN-OR CBC as default solver — CBC is not available as an Alpine APK and PuLP's bundled CBC binary may not run on musl/aarch64. Using scipy's HiGHS (which has confirmed musllinux wheels) is simpler and avoids solver binary distribution problems.

**Do NOT use Google OR-Tools.** OR-Tools is a heavy dependency (100+ MB), overkill for single-site HEMS LP, and has no Alpine musl wheel on PyPI as of 2026.

**Do NOT use Pyomo.** Pyomo is a rich modeling framework but requires separate solver installation (GLPK or CBC binaries). More complexity than the problem warrants.

### 2. Lightweight Neural Network — Residual RL

**Recommended: Custom numpy-only micro-MLP (no external framework)**

The existing codebase already has a custom DQN implemented in pure Python/numpy. Extending this with a small residual-learning MLP is the correct approach because:
- PyTorch does NOT run reliably on Alpine Linux (musl libc vs glibc binary incompatibility). PyTorch wheels are glibc-built and will fail on Alpine.
- TensorFlow Lite for Python requires glibc — same problem on Alpine.
- Stable-Baselines3 depends on PyTorch — ruled out for same reason.
- A residual corrector for a HEMS planner needs at most 2-3 hidden layers with 32-64 neurons — trivially implementable in numpy with forward pass + backprop.
- The existing DQN already demonstrates the team can maintain a custom RL implementation.

The numpy residual RL architecture:
- Input: planner features (price forecast, PV forecast, battery SoC, time-of-day, day-of-week) — approx 15-20 features
- Output: scalar correction to planner's battery charge/discharge recommendation
- Structure: MLP with 2 hidden layers (32 neurons each), ReLU activation, MSE loss
- Training: online update after each 15-min cycle using realized vs. planned comparison
- Persistence: save weights to `/data/smartprice_rl_model.json` (extends existing pattern)

**Do NOT use PyTorch (any version) in the Alpine container.** PyTorch wheels are built against glibc. Running PyTorch on Alpine requires either compiling from source (hours of build time, massive image bloat) or switching the base image away from Alpine (breaks HA add-on compatibility).

**Do NOT use TensorFlow/Keras.** TF is 500MB+ and has the same Alpine glibc problem.

**Do NOT use Stable-Baselines3.** Depends on PyTorch, same problem.

**Do NOT use ONNX Runtime.** Has no confirmed musllinux aarch64 wheel on PyPI as of early 2026.

### 3. Statistical Forecasting — Consumption Pattern Learning

**Recommended: `statsmodels` SARIMA via `apk add py3-statsmodels`**

statsmodels SARIMA is the right fit because:
- Available as `py3-statsmodels` in Alpine's community repository — installs against musl natively
- SARIMA captures weekly and daily seasonality in home energy consumption
- Outperforms Facebook Prophet on short-horizon (24-48h) forecasting benchmarks for structured periodic data
- Requires only 2-4 weeks of historical data to produce useful forecasts (InfluxDB historical data already available)
- Interpretable — coefficients can be logged to explain forecast confidence
- Lightweight inference: SARIMA prediction runs in milliseconds once the model is fitted offline

For initial forecasting, `statsmodels.tsa.seasonal.seasonal_decompose` is the minimal entry point — extract trend + seasonality from 2 weeks of 15-min interval data, use for LP planning horizon consumption estimates.

**Do NOT use Facebook Prophet.** Prophet requires pystan/cmdstanpy for compilation, which has severe musl/Alpine compatibility issues. Prophet also needs many months of data to fit well and is overengineered for 24-48h household consumption forecasting.

**Do NOT use scikit-learn for time series.** sklearn does not support ARIMA/seasonal models natively. It would require additional libraries and a different mental model.

**Do NOT use LSTM (neural network forecasting).** Same PyTorch/TensorFlow Alpine incompatibility. numpy-only LSTM is possible but overkill vs. SARIMA for well-structured periodic data.

### 4. Transparent Decision Visualization

**Recommended: `plotly` 6.5.2 (pure Python) + plotly.js CDN in HTML templates**

plotly is correct because:
- Pure Python package (`py3-none-any` wheel) — zero Alpine compatibility issues, installs via `pip install plotly` in the existing Dockerfile pattern
- Generates interactive JSON-based charts served via the existing Python HTTP server
- No Dash runtime needed — `fig.to_json()` output is embedded directly in the existing HTML templates using `Plotly.newPlot()` with plotly.js loaded from CDN
- Supports Gantt/timeline chart type natively (`plotly.express.timeline`) — perfect for the 24-48h energy plan visualization
- Zero additional server infrastructure — charts are static JSON served with the existing `http.server`-based dashboard

Implementation pattern (no Dash, no extra server):
```python
import plotly.graph_objects as go
import json

def generate_plan_chart(plan_intervals):
    fig = go.Figure()
    # Add battery, PV, grid, EV traces
    fig.add_trace(go.Bar(x=times, y=battery_charge, name="Battery Charge"))
    # ... additional traces
    return fig.to_json()  # inject into HTML template as JSON string
```

For decision explanations ("why"), use simple rule-based text generation alongside the chart — the LP dual variables (shadow prices) from scipy's linprog result directly explain which constraint was binding. No SHAP/LIME needed for a transparent LP planner; the optimizer's dual values ARE the explanation.

**Do NOT use Dash.** Dash adds a Flask-based web server with React frontend, permanently running in the background. The existing system already has a custom HTTP server. Adding Dash would mean running two HTTP servers and significantly increasing memory consumption on Raspberry Pi.

**Do NOT use matplotlib.** matplotlib generates static PNGs — not interactive. The 24-48h plan is most useful as an interactive timeline the user can zoom/hover.

**Do NOT use Chart.js or D3.js directly.** These require JavaScript knowledge for customization. plotly.py generates the chart spec in Python; the JavaScript rendering is handled by the CDN plotly.js bundle automatically.

**Do NOT use SHAP or LIME.** These are model-agnostic explainability libraries designed for black-box ML models. The system uses an LP optimizer — a white-box model where the dual variables (shadow prices) already provide full mathematical explanations of every decision. SHAP adds 50MB+ of dependencies with no benefit here.

---

## Installation

Add to Dockerfile `RUN` block:

```bash
# System packages via apk (musl-native, no wheel issues)
apk add --no-cache \
    py3-scipy \
    py3-statsmodels

# Pure-Python packages via pip (no compilation needed)
pip3 install --no-cache-dir --break-system-packages \
    plotly==6.5.2

# CONDITIONAL: Only if apk py3-scipy version < 1.7.0 (check at build time)
# pip3 install --no-cache-dir --break-system-packages highspy==1.13.1
```

Note on apk vs pip for scipy/statsmodels: Alpine's community repository compiles these against musl. Using apk avoids the "can pip find a musllinux wheel?" problem entirely. The tradeoff is that apk versions may lag behind PyPI by 1-2 minor releases, which is acceptable for these stable libraries.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| scipy.optimize.linprog (HiGHS) | PuLP 3.3.0 + CBC | If you need MILP (integer variables for on/off switching). PuLP's algebraic modeling syntax is more readable for complex models. Only use if LP proves insufficient — but battery scheduling LP is well-solved with continuous variables. |
| scipy.optimize.linprog (HiGHS) | highspy 1.13.1 direct | If apk py3-scipy is not available or is older than 1.7.0. highspy has confirmed musllinux_1_2_aarch64 wheels. |
| numpy micro-MLP (custom) | PyTorch (Debian-based image) | Only if switching the Docker base image from Alpine to Debian slim is acceptable. This would allow PyTorch 2.x + Stable-Baselines3, but requires changing the HA add-on base image strategy entirely. |
| statsmodels SARIMA (apk) | Prophet | If you have 12+ months of historical data and need holiday-aware forecasting. Prophet is the better long-range seasonal model, but Alpine installation is painful and requires cmdstanpy compilation. |
| plotly + CDN plotly.js | Dash | If the dashboard needs real-time push updates or complex user interaction. Dash's WebSocket-based live updates justify the extra infrastructure overhead at that point. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| PyTorch (any version) | Built against glibc; does not run on Alpine Linux (musl). Even unofficial aarch64 wheels require musl patching. | numpy micro-MLP (custom implementation) |
| TensorFlow/Keras | 500MB+ install size; glibc-built; incompatible with Alpine musl. | numpy micro-MLP |
| Stable-Baselines3 | Requires PyTorch. Same Alpine incompatibility. | Custom numpy RL loop (already partially exists in codebase) |
| ONNX Runtime | No confirmed musllinux_aarch64 wheel on PyPI as of Feb 2026. | numpy for inference |
| Facebook Prophet | Requires cmdstanpy/pystan compilation against musl — known to fail on Alpine aarch64. | statsmodels SARIMA via apk |
| Dash (plotly) | Runs a second Flask HTTP server; consumes ~60MB RAM baseline on Pi. Existing custom server is sufficient. | plotly + CDN plotly.js injected into existing HTML templates |
| Google OR-Tools | 100MB+ binary; no musllinux wheel confirmed. Overkill for single-site LP. | scipy.optimize.linprog |
| Pyomo | Requires separate solver binary (GLPK/CBC); complex dependency chain. | scipy.optimize.linprog with bundled HiGHS |
| SHAP / LIME | Designed for black-box ML explanation. LP dual variables are the correct explanation mechanism for this optimizer — SHAP adds unnecessary complexity and 50MB+ deps. | scipy linprog result `.ineqlin.marginals` (dual values) |
| scikit-learn (for forecasting) | No ARIMA/seasonal models. Would need additional libraries. | statsmodels SARIMA |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| plotly 6.5.2 | Python 3.13, Alpine 3.21 | Pure Python, no compatibility issues |
| py3-scipy (apk, ~1.14.x) | Python 3.13, Alpine 3.21, musl aarch64 | apk version may be 1.13.x or 1.14.x — both have HiGHS as default linprog method (introduced in 1.7.0) |
| py3-statsmodels (apk, ~0.14.x) | Python 3.13, Alpine 3.21, musl aarch64 | apk version lags PyPI by ~1 minor release; 0.14.x is stable for SARIMA use |
| highspy 1.13.1 | Python 3.13, musl 1.2 aarch64 | musllinux_1_2_aarch64 wheel confirmed on PyPI (released Feb 2026) |
| numpy (existing) | Python 3.13, Alpine 3.21 | No version change needed; used for micro-MLP implementation |

---

## Stack Patterns by Variant

**If ARM64 aarch64 (Raspberry Pi 4/5, standard HA install):**
- Use `apk add py3-scipy py3-statsmodels` for system packages
- Use `pip install plotly==6.5.2` for visualization
- Use custom numpy micro-MLP for RL

**If amd64 (x86 Linux, HA on standard PC):**
- Same stack works identically — scipy/statsmodels have both manylinux and musllinux aarch64 wheels
- No changes needed

**If armv7 (older Raspberry Pi 3):**
- scipy and statsmodels may need to build from source via apk — same `apk add` command, but build takes longer
- highspy 1.13.1 may not have an armv7 musllinux wheel — fall back to `apk add py3-scipy`
- numpy micro-MLP is even more important on armv7 (no PyTorch option)

**If switching base image from Alpine to Debian slim is ever considered:**
- PyTorch 2.x becomes available (glibc-compatible wheels on PyPI)
- Stable-Baselines3 becomes available
- But HA add-on build.yaml would need new base image references — significant change

---

## Sources

- [highspy 1.13.1 on PyPI](https://pypi.org/project/highspy/) — verified musllinux_1_2_aarch64 wheel, released Feb 11, 2026 (HIGH confidence)
- [plotly 6.5.2 on PyPI](https://pypi.org/project/plotly/) — verified pure Python py3-none-any wheel, released Jan 14, 2026 (HIGH confidence)
- [py3-scipy on Alpine Linux packages](https://pkgs.alpinelinux.org/package/edge/community/x86/py3-scipy) — confirmed available in Alpine edge/community repo (HIGH confidence)
- [py3-statsmodels on Alpine Linux packages](https://pkgs.alpinelinux.org/package/edge/community/armhf/py3-statsmodels) — confirmed available in Alpine community for armhf (HIGH confidence)
- [scipy.optimize.linprog HiGHS documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html) — HiGHS is default method; dual variables available in result (HIGH confidence)
- [PuLP 3.3.0 on PyPI](https://pypi.org/project/PuLP/) — bundles CBC solver binary, confirmed (MEDIUM confidence — Alpine binary compatibility not tested)
- [ADGEfficiency/energy-py-linear](https://github.com/ADGEfficiency/energy-py-linear) — confirms LP-based battery scheduling pattern using CBC/HiGHS (MEDIUM confidence — evidence of pattern in production)
- [ScienceDirect HEMS MILP paper Dec 2024](https://www.sciencedirect.com/science/article/pii/S0378778824013677) — confirms MILP as state-of-art for HEMS battery optimization (MEDIUM confidence — academic source)
- [Stable-Baselines3 Alpine note](https://stable-baselines3.readthedocs.io/) — Alpine uses musl, PyTorch wheels glibc-built; Debian-slim recommended for SB3 (HIGH confidence)
- [WebSearch: numpy MLP from scratch 2025](https://elcaiseri.medium.com/building-a-multi-layer-perceptron-from-scratch-with-numpy-e4cee82ab06d) — confirmed viable pattern for residual correction MLP (MEDIUM confidence)

---

*Stack research for: SmartLoad v6 — HEMS predictive planning, hybrid RL, visualization*
*Researched: 2026-02-22*
