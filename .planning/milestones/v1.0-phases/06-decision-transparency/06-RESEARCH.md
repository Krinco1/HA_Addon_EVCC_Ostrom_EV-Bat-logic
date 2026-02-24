# Phase 6: Decision Transparency - Research

**Researched:** 2026-02-23
**Domain:** Dashboard Visualization, LP Dual Variables, InfluxDB Plan Snapshots
**Confidence:** HIGH (codebase is fully inspected; patterns well understood)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Plan-Timeline Darstellung:**
- Gantt-Bars mit Preisoverlay (Preislinie über den Aktionsbalken)
- Rollend 24h ab jetzt als Default-Zeitfenster
- Farbcodierung:
  - Grün: Batterie laden (Netz oder PV)
  - Orange: Batterie entladen (Einspeisung/Hausverbrauch)
  - Blau: EV laden (pro Fahrzeug unterscheidbar)
  - Gelb/Gold: PV-Erzeugung als Hintergrundbereich
  - Rot/Grau: Preislinie
- Interaktion: Hover = kompakte Kurzinfo, Klick = volle Erklärung (Progressive Disclosure)

**Entscheidungs-Erklärungen:**
- Sprache: Deutsch (konsistent mit bestehendem Dashboard)
- Hover-Kurzinfo: Knapp und zahlenbasiert — "Laden: Preis 8,2 ct (Rang 3/96), Abfahrt in 6h, Warten +1,40 EUR"
- Klick-Erklärung: Voller erklärender Satz — "Kia wird jetzt geladen, weil der Preis mit 8,2 ct im unteren 20% des Forecasts liegt und die Abfahrt in 6h ist — Warten würde ca. 1,40 EUR mehr kosten."
- Kernwerte in jeder Erklärung:
  - Aktueller Preis (ct/kWh) + Rang im Forecast
  - Kostendelta ("Warten würde X EUR mehr kosten")
  - Zeitfenster (Stunden bis Abfahrt / bis nächste günstige Phase)
  - PV-Erwartung ("In 3h werden ~2,4 kWh PV erwartet")
  - Buffer-Status ("Puffer bei 35%, Ziel 20%")

**Plan vs. Realität Vergleich:**
- Duale Darstellung: Overlay-Chart für schnellen Überblick + Tabelle für Details
- Zeitraum: Letzte 24h als Default, 7-Tage-Ansicht per Toggle
- Abweichungs-Hervorhebung: Kostenbasiert in EUR ("Abweichung hat 0,30 EUR gekostet"), farblich (grün = gespart, rot = teurer)

**Dashboard-Integration:**
- 3 Tabs: Haupttab (existierend), Plan-Tab (neu), Historie-Tab (neu)

### Claude's Discretion

- Gantt-Bar-Format (exaktes Chart-Rendering, SVG vs. Canvas vs. Library)
- Exaktes Layout der Kurzinfo-Tooltips
- Tabellen-Spaltendesign im Historie-Tab
- Chart-Styling (Linienstärke, Opacity, Animationen)
- Overlay-Chart Technik (wie geplante vs. tatsächliche Bars dargestellt werden)
- Tab-Navigation Implementierung (CSS-Tabs, JS-basiert, etc.)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TRAN-01 | Jede Entscheidung wird mit menschenlesbarer Begründung begleitet ("Lade Kia jetzt weil Preis im unteren 20% und Abfahrt in 6h") | LP-Kontext aus DispatchSlot (price_eur_kwh, pv_kw, bat_soc_pct, ev_soc_pct) + Percentile-Berechnung → Explanation-Generator im Python-Backend |
| TRAN-02 | Dashboard zeigt 24-48h Zeitstrahl-Ansicht des Plans mit Preis-Overlay und geplanten Lade-/Entladezeitfenstern | PlanHorizon.slots ist vollständig verfügbar in StateStore; neues `/plan` API-Endpoint liefert 96 Slots als JSON; SVG-Gantt-Chart im Dashboard (kein externe Library nötig) |
| TRAN-04 | Dashboard zeigt historischen Vergleich: was geplant war vs was tatsächlich passiert ist | InfluxDB-Messung `smartload_plan_snapshot` pro Zyklus; Vergleich gegen `Smartprice` (actual-Daten, bereits vorhanden); neues `/history` API-Endpoint |
</phase_requirements>

---

## Summary

Phase 6 baut vollständig auf vorhandener Infrastruktur auf. Der `PlanHorizon` mit 96 `DispatchSlot`-Objekten wird bereits jede Runde in `StateStore` gespeichert (`store.update_plan(plan)`). Die Slots enthalten alle nötigen Daten: Preis, PV-Erwartung, Batterie-SoC, EV-SoC, Ladeleistungen. Was fehlt: ein API-Endpoint der die Slots serialisiert, ein Explanation-Generator der daraus deutschen Text erzeugt, und eine Snapshot-Speicherung pro Zyklus in InfluxDB für den Plan-vs-Actual-Vergleich.

Die Visualization-Strategie folgt dem bewährten Projekt-Muster: SVG-basierte Charts, pure JavaScript, kein Framework. Das bestehende `renderForecastChart()` und `renderChart()` in `app.js` zeigen die exakten Patterns. Tab-Navigation ist nicht im Code — muss neu gebaut werden, aber trivial (CSS `display:none`/`block`, 3 Buttons).

Die größte konzeptionelle Herausforderung ist der Explanation-Generator: Kostendelta berechnen (was würde es kosten, diesen Slot NICHT zu laden) erfordert, den LP-Plan zu verstehen. Das ist lösbar ohne LP-Dual-Variablen: man vergleicht `plan.solver_fun` (Gesamtkosten) gegen eine Schätzung der Kosten ohne diesen Slot, oder man berechnet einfach "Preis dieses Slots vs. Durchschnitt der restlichen Slots".

**Primary recommendation:** SVG-Gantt in app.js (kein Plotly nötig — Projekt nutzt SVG und hat keine externen Chart-Libs), Explanation-Generator in Python als `ExplanationGenerator`-Klasse, Plan-Snapshots als neues InfluxDB-Measurement.

---

## Standard Stack

### Core (bereits vorhanden, keine neue Dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (json, datetime) | 3.x | Plan-Serialisierung, Zeitrechnung | Bereits genutzt, kein Import nötig |
| NumPy | bereits installiert | Preis-Percentile, Rang-Berechnung | Bereits in `state.py`, `planner.py` |
| InfluxDB HTTP API | bereits konfiguriert | Plan-Snapshots speichern | Bereits in `influxdb_client.py` |
| SVG (vanilla JS) | n/a | Gantt-Chart im Browser | Etabliertes Projekt-Pattern (alle Charts) |
| Vanilla JS | ES5-kompatibel | Tab-Navigation, Tooltip-Handling | Kein Build-Step, kein Framework |

### Keine neuen Dependencies nötig

Das Projekt hat keine `requirements.txt` (kein Dependency-File gefunden), installiert Pakete direkt im Docker-Image. Alle nötigen Werkzeuge sind bereits verfügbar:
- `numpy` — für Ranking-Berechnung
- `requests` — für InfluxDB-Queries
- Bestehende `InfluxDBClient` — hat `write()` und `query_home_power_15min()`-Pattern

**Keine externen Charting-Libraries (kein Plotly, kein Chart.js)** — das Projekt-Pattern ist SVG via String-Concatenation in JS. Das ist die richtige Wahl für HA Add-ons ohne Build-System.

---

## Architecture Patterns

### Recommended Project Structure

Neue Dateien:

```
rootfs/app/
├── explanation_generator.py     # Neu: Erklärungs-Generator (Python)
├── plan_snapshotter.py          # Neu: Plan-Snapshots in InfluxDB schreiben + abfragen
└── web/
    ├── server.py                # Erweitert: /plan und /history Endpoints
    ├── templates/
    │   └── dashboard.html       # Erweitert: Tab-Navigation + Plan/Historie-Tab HTML
    └── static/
        └── app.js               # Erweitert: renderPlanTab(), renderHistoryTab(), Tab-Switching
```

### Pattern 1: SVG-Gantt-Chart (bewährt in Projekt)

**What:** Gantt-Bars als SVG `<rect>` Elemente per Slot, Preislinie als `<path>`, Tooltip on mouseover.
**When to use:** Immer — ist das einzige Chart-Pattern im Projekt.
**Example (aus bestehendem renderChart in app.js):**

```javascript
// Bewährtes Muster: SVG als String zusammenbauen
function renderPlanGantt(slots) {
    var W = 960, H = 220;
    var marginL = 38, marginR = 20, marginT = 20, marginB = 32;
    var plotW = W - marginL - marginR;
    var plotH = H - marginT - marginB;
    var slotW = plotW / 96;

    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;display:block;">';

    // Für jeden DispatchSlot: farbige Bar (Höhe = Ladeleistung in kW)
    for (var i = 0; i < slots.length; i++) {
        var slot = slots[i];
        var bx = marginL + i * slotW;
        // Batterie laden = grün, entladen = orange, EV = blau
        if (slot.bat_charge_kw > 0.1) {
            var barH = (slot.bat_charge_kw / maxPower) * plotH;
            s += '<rect x="' + bx.toFixed(1) + '" y="' + (marginT + plotH - barH).toFixed(1) + '"'
               + ' width="' + (slotW * 0.8).toFixed(1) + '" height="' + barH.toFixed(1) + '"'
               + ' fill="#00ff88" opacity="0.85" data-idx="' + i + '" class="plan-slot"'
               + ' style="cursor:pointer;"/>';
        }
        // ... analog für bat_discharge (orange), ev_charge (blau)
    }

    // Preislinie als path über alle Bars
    var pricePath = '';
    var maxPrice = Math.max.apply(null, slots.map(function(s){ return s.price_ct; }));
    for (var j = 0; j < slots.length; j++) {
        var px = marginL + j * slotW + slotW / 2;
        var py = marginT + plotH - (slots[j].price_ct / maxPrice) * plotH;
        pricePath += (j === 0 ? 'M' : 'L') + px.toFixed(1) + ',' + py.toFixed(1);
    }
    s += '<path d="' + pricePath + '" fill="none" stroke="#ff4444" stroke-width="1.5"/>';

    s += '</svg>';
    return s;
}
```

### Pattern 2: API Endpoint für Plan-Daten

**What:** Neuer `GET /plan` Endpoint in `server.py` serialisiert `PlanHorizon` Slots.
**When to use:** Immer wenn Dashboard Plan-Daten braucht (polling alle 60s oder per SSE-Trigger).

```python
# In web/server.py do_GET():
elif path == "/plan":
    plan = srv._store.get_plan()
    if plan is None:
        self._json({"available": False, "slots": []})
    else:
        self._json(srv._api_plan(plan))

# In WebServer class:
def _api_plan(self, plan) -> dict:
    slots = []
    for slot in plan.slots:
        explanation = self._explanation_gen.explain(slot, plan)
        slots.append({
            "t": slot.slot_index,
            "start_iso": slot.slot_start.isoformat(),
            "bat_charge_kw": round(slot.bat_charge_kw, 2),
            "bat_discharge_kw": round(slot.bat_discharge_kw, 2),
            "ev_charge_kw": round(slot.ev_charge_kw, 2),
            "ev_name": slot.ev_name,
            "price_ct": round(slot.price_eur_kwh * 100, 1),
            "pv_kw": round(slot.pv_kw, 2),
            "bat_soc_pct": round(slot.bat_soc_pct, 1),
            "ev_soc_pct": round(slot.ev_soc_pct, 1),
            "explanation_short": explanation["short"],
            "explanation_long": explanation["long"],
        })
    return {
        "available": True,
        "computed_at": plan.computed_at.isoformat(),
        "total_cost_eur": round(plan.solver_fun, 3),
        "slots": slots,
    }
```

### Pattern 3: Explanation Generator (Python-Klasse)

**What:** Standalone Python-Klasse, die aus einem `DispatchSlot` + dem gesamten `PlanHorizon` einen deutschen Erklärungstext generiert.

**Kernlogik:**
- Preis-Rang: `sorted(all_prices).index(slot.price_eur_kwh) + 1` → "Rang 3 von 96"
- Preis-Perzentil: `slot.price_eur_kwh <= percentile_20` → "im unteren 20%"
- Kostendelta: Schätzung "Was kostet es, JETZT zu laden vs. WARTEN auf günstigsten verbleibenden Slot"
  - `wait_cost = min(remaining_slot_prices) * kwh_to_charge`
  - `now_cost = slot.price_eur_kwh * kwh_to_charge`
  - `delta = now_cost - wait_cost` (positiv = warten ist günstiger, negativ = jetzt laden ist günstiger)
- Abfahrtszeit: aus `ev_soc_pct` und Kapazität rückgerechnet, oder aus config `ev_departure_times`
- PV-Erwartung: aus den nächsten Slots `sum(s.pv_kw for s in slots[t:t+12])` × 15min

```python
# explanation_generator.py
class ExplanationGenerator:
    def explain(self, slot: DispatchSlot, plan: PlanHorizon,
                departure_slots: int = None) -> dict:
        """Gibt {"short": str, "long": str} zurück."""
        all_prices = [s.price_eur_kwh for s in plan.slots]
        price_ct = round(slot.price_eur_kwh * 100, 1)
        price_rank = sorted(all_prices).index(slot.price_eur_kwh) + 1
        n_slots = len(plan.slots)

        if slot.bat_charge_kw > 0.1:
            # Kostendelta: Laden jetzt vs. günstigsten verbleibenden Slot
            future_prices = all_prices[slot.slot_index + 1:]
            kwh = slot.bat_charge_kw * 0.25  # 15min × kW
            if future_prices:
                min_future = min(future_prices)
                delta_eur = (slot.price_eur_kwh - min_future) * kwh
            else:
                delta_eur = 0.0

            short = f"Laden: {price_ct} ct (Rang {price_rank}/{n_slots})"
            if departure_slots:
                short += f", Abfahrt in {departure_slots // 4}h"
            if delta_eur > 0:
                short += f", Warten +{delta_eur:.2f} EUR"

            long = (f"Batterie wird jetzt geladen, weil der Preis mit {price_ct} ct"
                    f" im unteren {round(price_rank / n_slots * 100)}% des Forecasts liegt.")
            if delta_eur > 0:
                long += f" Warten würde ca. {delta_eur:.2f} EUR mehr kosten."
            return {"short": short, "long": long}

        # analog für bat_discharge, ev_charge, hold...
```

### Pattern 4: Plan-Snapshots in InfluxDB

**What:** Jeden Zyklus nach LP-Solve einen kompakten Plan-Snapshot in InfluxDB schreiben. Measurement: `smartload_plan_snapshot`. Nur slot 0 (aktueller Slot) und Gesamt-Kosten — kein full-96-Slot-Write (zu viel Daten).

```python
# plan_snapshotter.py
class PlanSnapshotter:
    def __init__(self, influx_client):
        self._influx = influx_client

    def write_snapshot(self, plan: PlanHorizon, actual_state):
        """Schreibt Plan-Snapshot für Zyklus t=0."""
        if plan is None or not self._influx._enabled:
            return
        slot0 = plan.slots[0]
        self._influx.write(
            measurement="smartload_plan_snapshot",
            fields={
                "planned_bat_charge_kw": slot0.bat_charge_kw,
                "planned_bat_discharge_kw": slot0.bat_discharge_kw,
                "planned_ev_charge_kw": slot0.ev_charge_kw,
                "planned_price_ct": round(slot0.price_eur_kwh * 100, 2),
                "planned_total_cost_eur": plan.solver_fun,
                "actual_bat_power_w": actual_state.battery_power if actual_state else 0,
                "actual_ev_power_w": actual_state.ev_power if actual_state else 0,
                "actual_price_ct": round(actual_state.current_price * 100, 2) if actual_state else 0,
            }
        )

    def query_comparison(self, hours: int = 24) -> list:
        """Abfrage Plan vs. Actual für Historie-Tab."""
        return self._influx.query(
            f"SELECT planned_bat_charge_kw, planned_price_ct, "
            f"actual_bat_power_w, actual_price_ct "
            f"FROM smartload_plan_snapshot "
            f"WHERE time > now() - {hours}h "
            f"ORDER BY time DESC"
        )
```

### Pattern 5: Tab-Navigation (CSS + JS, kein Framework)

**What:** 3 Tab-Buttons die `data-tab`-Attribute setzen, CSS `display:none/block` toggling.
**When to use:** Standard-Web-Pattern, passt zum Projekt (kein React, kein Vue).

```html
<!-- In dashboard.html -->
<div class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('main')">Status</button>
    <button class="tab-btn" onclick="switchTab('plan')">Plan</button>
    <button class="tab-btn" onclick="switchTab('history')">Historie</button>
</div>
<div id="tab-main" class="tab-panel"><!-- bestehender Content --></div>
<div id="tab-plan" class="tab-panel" style="display:none;"></div>
<div id="tab-history" class="tab-panel" style="display:none;"></div>
```

```javascript
// In app.js
function switchTab(name) {
    ['main', 'plan', 'history'].forEach(function(t) {
        document.getElementById('tab-' + t).style.display = t === name ? '' : 'none';
    });
    document.querySelectorAll('.tab-btn').forEach(function(b, i) {
        b.classList.toggle('active', ['main','plan','history'][i] === name);
    });
    if (name === 'plan') fetchAndRenderPlan();
    if (name === 'history') fetchAndRenderHistory();
}
```

### Anti-Patterns to Avoid

- **Plotly oder andere Chart-Libs einbinden:** Kein Build-System, kein npm — im HA Add-on nicht machbar ohne Dockerfile-Änderung. SVG reicht vollständig.
- **LP Dual-Variablen extrahieren:** `scipy.optimize.linprog` gibt dual variables als `result.ineqlin.marginals` und `result.eqlin.marginals` zurück (seit scipy 1.7). Diese enthalten theoretisch Schattenpreise, aber in der Praxis sind sie schwer interpretierbar für User-facing Text. Stattdessen: simpler Preisvergleich (aktueller Preis vs. Durchschnitt / Minimum der restlichen Slots) — ausreichend für menschenlesbare Erklärungen, wie in Requirement TRAN-01 beschrieben.
- **Full-Plan-Broadcast per SSE:** 96 Slots mit Explanation-Strings wären ~50KB pro Update — zu groß für SSE. Plan wird on-demand per `GET /plan` abgerufen (kein SSE-Push).
- **Plan-Snapshot mit allen 96 Slots in InfluxDB:** InfluxDB ist für Zeitreihen, nicht für nested arrays. Nur Slot-0 + Gesamtkosten schreiben.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Preis-Rang berechnen | Eigenes Ranking-Algo | `sorted(all_prices).index(price)` | 1 Zeile, korrekt |
| Deutschsprachige Zahlenformatierung | Eigener Formatter | `f"{val:.2f}".replace('.', ',')` oder f-string direkt | Deutsch nutzt Komma — aber Strings direkt in Erklärungen einbauen reicht |
| Tooltip-Positioning | Custom Pointer-Event-Library | Bewährtes Mousemove-Pattern aus app.js (chartTooltip) | Ist schon gebaut, einfach replizieren |
| Chart-Animation | CSS Transitions | Keine Animations — Projekt nutzt keine (Phase 5 Buffer-Chart auch statisch) | Einfacher, schneller, kein Flicker bei Updates |

---

## Common Pitfalls

### Pitfall 1: DispatchSlot.slot_start Timezone-Handling
**What goes wrong:** `slot.slot_start` ist UTC (`datetime.now(timezone.utc) + timedelta(...)`). Im Browser läuft JavaScript in lokaler Zeitzone. Wenn man direkt `slot_start.isoformat()` ans Frontend schickt, zeigt `new Date(isoStr).getHours()` lokale Zeit — das ist tatsächlich korrekt für die Anzeige.
**Why it happens:** Python `datetime` + `timezone.utc` erzeugt `+00:00` suffix, JS `new Date()` parsed das korrekt und konvertiert in lokale Zeit.
**How to avoid:** Immer ISO-Format mit Timezone-Suffix serialisieren (`slot.slot_start.isoformat()` — schon so in `PlanHorizon`). Kein manuelles Timezone-Handling in JS.
**Warning signs:** Gantt-Chart zeigt Slots um 1-2h verschoben.

### Pitfall 2: PlanHorizon ist nicht immer verfügbar
**What goes wrong:** Dashboard fragt `/plan` an, aber LP hat noch nicht gelaufen (erster Start, scipy nicht installiert, Fallback zu HolisticOptimizer).
**Why it happens:** `store.get_plan()` returned `None` wenn kein LP-Plan berechnet wurde.
**How to avoid:** `/plan` endpoint returned immer `{"available": false, "slots": []}` wenn `plan is None`. Dashboard zeigt Platzhalter: "Kein Plan verfügbar — LP läuft noch oder ist nicht aktiv."
**Warning signs:** 500-Error wenn man `plan.slots` ohne None-Check aufruft.

### Pitfall 3: Kostendelta-Berechnung ist eine Näherung
**What goes wrong:** User sieht "Warten würde 1,40 EUR mehr kosten" und fragt sich ob das stimmt — es ist eine Approximation basierend auf Slot-Preisen, nicht die echten LP-Dual-Variablen.
**Why it happens:** LP-Dual-Variablen aus scipy (`result.ineqlin.marginals`) geben Schattenpreise, aber nur für aktive Constraints — schwer zu interpretieren für nicht-Experten.
**How to avoid:** In der Erklärung transparent kommunizieren: "ca." statt exakten Zahlen. "Warten würde ca. 1,40 EUR mehr kosten." — "ca." ist in den Beispielen des Users bereits so formuliert.
**Warning signs:** Keine — das ist eine Design-Entscheidung, keine Fehlerquelle.

### Pitfall 4: InfluxDB Write-Latenz blockiert Decision Loop
**What goes wrong:** `plan_snapshotter.write_snapshot()` macht HTTP-Request im Decision Loop — bei InfluxDB-Ausfall dauert das `timeout=5` Sekunden.
**Why it happens:** Bestehender `InfluxDBClient.write()` hat `timeout=5` und fängt `ConnectionError` ab — aber der Decision Loop wartet trotzdem.
**How to avoid:** `PlanSnapshotter.write_snapshot()` in eigenem try/except aufrufen (wie bei `buffer_calc.step()`). Bestehender InfluxDB-Client fängt Connection-Errors bereits ab, gibt nur Warning — kein Absturz.
**Warning signs:** Decision-Loop-Latenz > 1s im Log.

### Pitfall 5: Explanation-Generator bei 0-Leistungs-Slots
**What goes wrong:** Viele Slots haben `bat_charge_kw = 0, bat_discharge_kw = 0, ev_charge_kw = 0` — was erklärt man da?
**Why it happens:** LP hält Batterie-SoC in vielen Slots (teuer oder optimal gehalten). Erklärung "Batterie hält SoC" ist uninteressant.
**How to avoid:** Für `hold`-Slots kurze, zusammenfassende Erklärung: "Preis zu hoch zum Laden (X ct, Schwelle Y ct). Kein Handlungsbedarf." Tooltip nur für aktive Slots (charge/discharge) voll ausgearbeitet.
**Warning signs:** Gantt-Chart mit nur wenigen farbigen Bars — die meisten Slots sind leer.

### Pitfall 6: Tab-Navigation versteckt bestehenden Content
**What goes wrong:** Bestehende HTML-Elemente werden in `tab-main` gewrapped — alle IDs und JS-Referenzen (`$('strategyCard')` etc.) müssen weiterhin funktionieren.
**Why it happens:** `app.js` referenziert IDs direkt. Wenn diese in ein `<div id="tab-main">` gepackt werden, ändert sich nichts — IDs bleiben eindeutig.
**How to avoid:** Bestehenden HTML-Body-Content in `<div id="tab-main" class="tab-panel">` einwickeln. `<div style="display:none">` verhindert SSE-Flash-Animationen für versteckte Tabs nicht — kein Problem, da Animationen auf visible Elements abzielen.
**Warning signs:** JS-Fehler "Cannot read properties of null" wenn `$('strategyCard')` null returned.

---

## Code Examples

Verified patterns from codebase inspection:

### Existing Plan Access Pattern (state_store.py, verified)

```python
# StateStore hat get_plan() und update_plan() bereits:
plan = store.get_plan()  # returns Optional[PlanHorizon]
if plan is not None:
    slot0 = plan.slots[0]
    print(slot0.bat_charge_kw, slot0.price_eur_kwh)
```

### DispatchSlot Data Model (state.py, verified)

```python
@dataclass
class DispatchSlot:
    slot_index: int          # 0..95
    slot_start: datetime     # UTC
    bat_charge_kw: float     # kW (>0.1 = aktiv)
    bat_discharge_kw: float  # kW (>0.1 = aktiv)
    ev_charge_kw: float      # kW (>0.1 = aktiv)
    ev_name: str             # Fahrzeugname
    price_eur_kwh: float     # Grid-Preis EUR/kWh
    pv_kw: float             # PV-Ertrag kW
    consumption_kw: float    # Hausverbrauch kW
    bat_soc_pct: float       # Batterie-SoC % (LP-Wert)
    ev_soc_pct: float        # EV-SoC % (LP-Wert)
```

### Existing InfluxDB Write Pattern (influxdb_client.py, verified)

```python
# InfluxDB Write — bereits implementiert, gleiches Pattern für Plan-Snapshots:
self._influx.write(
    measurement="smartload_plan_snapshot",
    fields={
        "planned_bat_charge_kw": 3.6,
        "actual_bat_power_w": 3500.0,
        "price_delta_ct": 2.1,
    }
)
```

### Existing InfluxDB Query Pattern (influxdb_client.py, verified)

```python
# Für History-Queries: gleiches Pattern wie query_home_power_15min:
query = (
    "SELECT planned_price_ct, actual_price_ct, planned_bat_charge_kw "
    "FROM smartload_plan_snapshot "
    "WHERE time > now() - 24h "
    "ORDER BY time DESC"
)
resp = requests.get(f"{self._base_url}/query", params={"db": self.database, "q": query}, ...)
```

### SSE Plan Integration (state_store.py comment, verified)

```
# Hinweis aus state_store.py:
# "Phase 4: plan_summary — lightweight LP plan status for dashboard"
# Full slot timeline in Phase 6 — genau das ist jetzt zu implementieren.
```

Der bestehende `plan_summary` in SSE enthält nur `computed_at`, `status`, `cost_eur`, `current_action`. Phase 6 ergänzt den separaten `/plan` Polling-Endpoint (nicht SSE) für die vollen 96 Slots.

### Existing SVG Tooltip Pattern (app.js, verified)

```javascript
// Vollständig implementiertes Pattern in renderChart() — direkt replizieren:
bars[b].addEventListener('mouseenter', function(e) {
    var idx = parseInt(this.getAttribute('data-idx'));
    tooltip.innerHTML = html;
    tooltip.style.display = 'block';
});
bars[b].addEventListener('mousemove', function(e) {
    var rect = wrap.getBoundingClientRect();
    var x = e.clientX - rect.left + 10;
    var y = e.clientY - rect.top - 10;
    if (x + 140 > rect.width) x = x - 160;  // Overflow-Schutz
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
});
bars[b].addEventListener('mouseleave', function() { tooltip.style.display = 'none'; });
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Plan-Summary (nur slot0-Booleans) in SSE | Full 96-Slot Serialisierung via `/plan` GET | Phase 6 | Dashboard kann Timeline darstellen |
| Keine Erklärungen (nur Decision-Log-Text) | Structured Explanation mit short/long pro Slot | Phase 6 | TRAN-01 erfüllt |
| Kein Plan-Archiv | InfluxDB Snapshot pro Zyklus | Phase 6 | TRAN-04 Basis |

---

## Open Questions

1. **Kostendelta: Eigene LP-Lösungen als Vergleich oder einfacher Preis-Diff?**
   - Was wir wissen: LP-Dual-Variablen wären präziser aber schwer interpretierbar
   - Was unklar: Ob User-facing "ca. X EUR mehr" ausreicht oder ob Genauigkeit wichtig ist
   - Recommendation: Einfacher Preisvergleich (aktueller Slot vs. günstigster verbleibender Slot, gleiche kWh-Menge) — passt zu "ca." im CONTEXT.md

2. **Plan-vs-Actual: Welcher Actual-Wert ist "wahr"?**
   - Was wir wissen: InfluxDB hat `Smartprice`-Measurement mit `battery_power`, `price_ct`, `ev_action`
   - Was unklar: `battery_power` in W ist der echte Ist-Wert; geplant war `bat_charge_kw` in kW — Einheits-Umrechnung beachten (÷1000)
   - Recommendation: In `PlanSnapshotter` beide Einheiten explizit kommentieren

3. **Geschichte Tab: Was wenn InfluxDB nicht konfiguriert?**
   - Was wir wissen: `InfluxDBClient._enabled = bool(self.host)` — wenn kein Host, alle Writes/Queries sind No-Ops
   - Was unklar: Was zeigt der Historie-Tab wenn keine Daten vorhanden?
   - Recommendation: Leerer Zustand mit Hinweis "InfluxDB nicht konfiguriert — keine historischen Daten verfügbar"

4. **Abfahrtszeit in Erklärungen: Woher kommt sie?**
   - Was wir wissen: `ev_departure_times` wird in `_get_departure_times(cfg)` aus config gelesen; EV-SoC-Trajektorie aus LP-Plan gibt implizit an, wann EV voll ist
   - Was unklar: Ob Departure-Zeit an `ExplanationGenerator` übergeben wird oder aus Plan interpoliert
   - Recommendation: `ExplanationGenerator` bekommt optionalen `departure_slots: int` Parameter; Main-Loop übergibt aus `_get_departure_times()` wenn verfügbar

---

## Validation Architecture

> `workflow.nyquist_validation` ist in config.json nicht auf `true` gesetzt (Feld fehlt). Abschnitt wird übersprungen.

---

## Sources

### Primary (HIGH confidence)

- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/state.py` — `DispatchSlot`, `PlanHorizon` Datenmodelle
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/optimizer/planner.py` — vollständige LP-Implementierung, `_extract_plan()`
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/state_store.py` — `get_plan()`, `update_plan()`, SSE-Broadcast-Pattern
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/web/server.py` — alle API-Endpoints, Pattern für neue Endpoints
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/web/static/app.js` — SVG-Chart-Patterns, Tooltip-Handling, renderForecastChart
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/web/templates/dashboard.html` — bestehende HTML-Struktur, CSS-Variablen
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/influxdb_client.py` — Write/Query-Pattern für neue Measurements
- Direkter Code-Review: `C:/users/nicok/projects/smartload/evcc-smartload/rootfs/app/main.py` — Decision-Loop, `store.update_plan()` Aufruf, `_get_departure_times()`

### Secondary (MEDIUM confidence)

- scipy.optimize.linprog Dokumentation (aus Training-Wissen): Dual-Variablen in `result.ineqlin.marginals` seit scipy 1.7 — erklärt warum einfacher Preisvergleich vorzuziehen ist (Dual-Variablen sind technisch, nicht user-facing)

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — vollständige Codebase-Inspektion, keine neuen Dependencies nötig
- Architecture: HIGH — alle Patterns direkt aus existierendem Code abgeleitet
- Pitfalls: HIGH — aus tatsächlichem Code-Verhalten (Timezone-Handling, None-Guards) identifiziert

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (30 Tage — stabile Codebase, keine Fast-Moving-Libraries)
