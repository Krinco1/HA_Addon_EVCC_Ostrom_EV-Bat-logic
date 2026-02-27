# SmartLoad v6 — Intelligentes Energiemanagement

## What This Is

Ein Home Assistant Add-on, das als ganzheitliches Energiemanagementsystem Hausbatterie, PV-Anlage und bis zu 3 Elektrofahrzeuge (1 Wallbox) kostenoptimal steuert. Ein prädiktiver 24-48h LP-Planer (HiGHS/scipy) erstellt jeden 15-Minuten-Zyklus einen Rolling-Horizon Lade-/Entladeplan. Ein dynamischer Akku-Puffer passt den Mindest-SoC situationsabhängig an. Ein Residual-RL-Agent lernt Korrekturen zum Planer aus Erfahrung. Dashboard zeigt Gantt-Zeitstrahl, deutsche Entscheidungsbegründungen und Plan-vs-Ist-Vergleich. Telegram-Integration für Sofort-Ladung und proaktive Abfahrtszeitabfrage.

## Core Value

Das System trifft zu jedem Zeitpunkt die wirtschaftlich beste Energieentscheidung unter Berücksichtigung aller verfügbaren Informationen (Preise, PV-Prognose, Verbrauch, EV-Bedarf, Akku-Puffer) — und der Nutzer versteht warum.

## Requirements

### Validated

- ✓ evcc-Integration für Batterie- und EV-Steuerung — existing
- ✓ Vehicle Provider: Kia/Hyundai API-Polling — existing
- ✓ Vehicle Provider: Renault/Dacia API-Polling — existing
- ✓ Vehicle Provider: Manueller SoC-Eintrag — existing
- ✓ Vehicle Provider: evcc-native Daten — existing
- ✓ Vehicle Provider: Custom HTTP API — existing
- ✓ Telegram-Bot für Fahrer-Interaktion — existing
- ✓ Web-Dashboard mit Entscheidungslog — existing
- ✓ InfluxDB-Integration für historische Daten — existing
- ✓ Home Assistant Add-on Packaging (Docker, Multi-Arch) — existing
- ✓ Charge Sequencer für Multi-EV auf 1 Wallbox — existing
- ✓ Quiet Hours Konfiguration — existing
- ✓ Thread-safe State Infrastructure (StateStore + SSE) — v1.0
- ✓ Config-Validierung beim Start mit klarer Fehlermeldung — v1.0
- ✓ Vehicle SoC korrekt und aktuell (Connection-Event Refresh) — v1.0
- ✓ Charge Sequencer sofortige Transition bei Fahrzeugwechsel — v1.0
- ✓ RL Bootstrap Speicherbegrenzung und Fortschrittsanzeige — v1.0
- ✓ Prädiktiver 24-48h Energieplaner (LP-Optimizer ersetzt statische Schwellenwerte) — v1.0
- ✓ Ganzheitliche Optimierung: PV + Preis + Verbrauch + EV-Bedarf + Akku-Puffer — v1.0
- ✓ Dynamischer Hausakku-Puffer (Mindest-SoC situationsabhängig) — v1.0
- ✓ Verbrauchsprognose aus InfluxDB/HA-Historie — v1.0
- ✓ PV-Ertragsprognose via evcc Solar-Tariff API — v1.0
- ✓ Transparentes Dashboard: Gantt-Zeitstrahl des 24-48h Plans — v1.0
- ✓ Dashboard: Deutsche Entscheidungs-Erklärungen (WARUM) — v1.0
- ✓ Dashboard: RL vs Planer Vergleichsdaten — v1.0
- ✓ Dashboard: Plan-vs-Ist historischer Vergleich — v1.0
- ✓ Boost Charge Override via Dashboard und Telegram — v1.0
- ✓ Proaktive Abfahrtszeitabfrage via Telegram — v1.0
- ✓ Urgency-basierte Multi-EV Priorisierung — v1.0
- ✓ Residual RL-Agent (Delta-Korrekturen zum Planer) — v1.0
- ✓ Saisonales Lernen (48-Zellen Lookup mit LP-Feedback) — v1.0
- ✓ Lernende Reaktionszeiten (EMA-Tracker) — v1.0
- ✓ Forecast Reliability Tracking mit Konfidenz-Faktoren — v1.0
- ✓ Deploy: Version 6.0.0, Config Schema, Repository Metadata — v1.0
- ✓ CI/CD: GitHub Actions Dockerfile Build Validation — v1.0
- ✓ Release Documentation: CHANGELOG + README aktualisiert — v1.0
- ✓ Vehicle SoC Polling: API-Provider (Kia Connect, Renault) liefern zuverlässig Daten auch ohne Wallbox-Verbindung — v1.1
- ✓ "Poll Now" Button im Dashboard für manuellen SoC-Abruf jedes Fahrzeugs — v1.1
- ✓ evcc Lademodus-Steuerung: SmartLoad setzt aktiv PV/Min+PV/Schnell je nach optimalem Plan — v1.1
- ✓ Override-Handling: evcc-manuelle Overrides gelten bis Vorgang abgeschlossen, SmartLoad passt Plan an — v1.1
- ✓ Batterie-Arbitrage: Hausakku als Zuspeiser beim EV-Schnellladen wenn wirtschaftlich sinnvoll (Reserve + Nachlade-Preise ok) — v1.1

### Active

#### v2.0 — Dashboard Redesign & evcc Integration (geplant)
- Dashboard Design an evcc Web-UI angleichen (Farben, Schriften, Layout)
- evcc Web-UI als iframe-Tab einbetten (optional per Schalter)

### Out of Scope

- ORA Vehicle Provider — separates Projekt, eigener Provider wird später geschrieben
- Mobile App — Web-Dashboard + Telegram decken alle Use Cases ab
- Multi-Wallbox-Support — aktuell 1 Wallbox im Setup
- Cloud-basierte KI (ChatGPT/Claude API für Echtzeit-Entscheidungen) — zu langsam, zu teuer, Abhängigkeit
- V2G / Vehicle-to-Home — Hardware (bidirektionaler Lader) nicht verfügbar
- Appliance Scheduling — HA Native Automations sind besser geeignet
- Per-Minute Decision Cycles — erhöht API-Last, Stromtarife sind stündlich

## Context

**Shipped v1.0 (2026-02-24):**
~15,700 LOC (12,700 Python + 2,400 JS + 600 HTML).
Tech stack: Python, scipy/HiGHS LP solver, InfluxDB, evcc REST API, Telegram Bot API.
Architecture: StateStore (RLock + SSE) → DataCollector → HorizonPlanner (96-slot LP) → Controller → evcc.
Forecasters: ConsumptionForecaster (tiered InfluxDB aggregation), PVForecaster (evcc solar tariff).
Learning: ResidualRLAgent (49-action delta space), SeasonalLearner (48-cell), ForecastReliabilityTracker, ReactionTimingTracker.
Dashboard: 4 tabs (Status, Plan/Gantt, Historie, Lernen) with SSE live updates.

**Hardware-Setup:**
- 1 Wallbox, 3 EVs (Kia, Renault, ORA)
- PV-Anlage (Daten über evcc)
- Hausbatterie (Kapazität konfigurierbar)
- Dynamischer Stromtarif (Preisdaten über evcc)
- Home Assistant als Host-System

**Shipped v1.1 (2026-02-27):**
Vehicle SoC Polling fix (Kia/Renault), Poll Now Button, evcc Mode Control mit Override Detection, LP-Gated Battery Arbitrage. 42 neue Unit Tests.

**Known Issues / Tech Debt:**
- Dead code: `rl_bootstrap_max_records` config field + `bootstrap_from_influxdb()` method (retired by Phase 8-03)
- Orphaned `/departure-times` REST endpoint with no frontend consumer
- RL agent in shadow mode — 30-day observation period before advisory mode
- DynamicBufferCalc in observation mode — 14-day observation before live buffer changes
- Visual verification pending for SVG charts, Gantt tooltips, Lernen tab widgets

## Constraints

- **Runtime**: Docker-Container auf HA (auch Raspberry Pi) — scipy/HiGHS LP solver, kein großes ML Framework
- **Datenquelle**: evcc ist die einzige Quelle für Preise, PV und Batterie-Status
- **Latenz**: Entscheidungszyklus alle 15 Min (konfigurierbar) — LP solver löst in <1s
- **Fahrer-Interaktion**: Telegram ist der einzige Kanal für Fahrer-Kommunikation
- **Abwärtskompatibilität**: Bestehende vehicles.yaml und drivers.yaml Konfiguration erhalten
- **Architektur**: Python-only, keine zusätzlichen Datenbanken über InfluxDB hinaus

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Statische Schwellenwerte durch prädiktiven LP-Planer ersetzen | Schwellenwerte können die Preislage nicht kontextabhängig bewerten | ✓ Good — HiGHS LP löst 96-Slot Joint Dispatch in <1s |
| Hybrid-RL (Residual Learning) statt reines RL oder reine Formeln | RL lernt Korrekturen zum Planer — leichter zu trainieren, transparenter | ✓ Good — 49-Action Delta Space (+/-20ct), shadow mode safety |
| Hausakku-Puffer dynamisch statt fester Mindest-SoC | Puffer-Bedarf hängt von Situation ab (Wetter, Tageszeit, Verbrauch) | ✓ Good — Formula mit 10% Floor, observation mode |
| Transparenz als Kernfeature | Nutzer muss Entscheidungen verstehen um System zu vertrauen | ✓ Good — German explanations, Gantt chart, Plan-vs-Ist |
| Kein Cloud-LLM für Echtzeit-Entscheidungen | Latenz, Kosten, Abhängigkeit | ✓ Good — scipy/HiGHS löst lokal in Millisekunden |
| evcc als zentrale Datenquelle beibehalten | Vereinfacht Architektur, evcc abstrahiert PV und Stromtarif | ✓ Good — API stabil, Solar-Tariff für PV-Forecast |
| GHCR Pre-Built Images → Dockerfile Local Build | HA Supervisor zog Pre-Built statt lokal zu bauen | ✓ Good — Standard HA Add-on Modell, CI als Test-Only |
| 50% Dampening + 0.05 EUR/kWh Cap auf Seasonal Corrections | Konservativ starten, Aggressivität später erhöhen | ⚠️ Revisit — nach 3+ Monaten Datensammlung evaluieren |
| RL 30-day Shadow Mode Pflicht | Safety: Constraint Audit vor Advisory Mode | — Pending — Shadow läuft seit Deployment |

| SmartLoad führt evcc-Lademodi, manuelle evcc-Overrides werden respektiert | Override gilt bis Vorgang abgeschlossen/unterbrochen, SmartLoad gleicht danach aus | ✓ Good — 7-gate arbitrage, override lifecycle |
| v1.1 Funktional, v2.0 UI-Redesign Split | Erst funktionale Verbesserungen (Polling, Steuerung, Arbitrage), dann UI-Overhaul (evcc Design + iframe) | ✓ Good — v1.1 shipped, v2.0 next |

---
*Last updated: 2026-02-27 after v1.1 milestone complete*
