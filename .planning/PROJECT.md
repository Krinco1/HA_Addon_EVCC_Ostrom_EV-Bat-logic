# SmartLoad v6 — Intelligentes Energiemanagement

## What This Is

Ein Home Assistant Add-on, das als ganzheitliches Energiemanagementsystem Hausbatterie, PV-Anlage und bis zu 3 Elektrofahrzeuge (1 Wallbox) kostenoptimal steuert. Statt statischer Preisschwellen erstellt ein prädiktiver Planer 24-48h Lade-/Entladepläne unter Berücksichtigung aller Faktoren — und ein Hybrid-RL-Agent verbessert diese Pläne kontinuierlich aus Erfahrung. Alle Entscheidungen werden transparent für den Nutzer dargestellt.

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

### Active

- [ ] Prädiktiver 24-48h Energieplaner (ersetzt statische Schwellenwerte)
- [ ] Ganzheitliche Optimierung: PV + Preis + Verbrauch + EV-Bedarf + Akku-Puffer
- [ ] Dynamischer Hausakku-Puffer (Mindest-SoC situationsabhängig)
- [ ] Hybrid-RL: Residual-Learning das Planer-Korrekturen lernt
- [ ] Saisonales Lernen (Jahreszeiten, sich ändernde Verbrauchsmuster)
- [ ] Lernende Reaktionszeiten (wann sofort reagieren, wann abwarten)
- [ ] Transparentes Dashboard: Zeitstrahl-Ansicht des 24-48h Plans
- [ ] Dashboard: Detail-Ansicht mit Entscheidungs-Erklärungen (WARUM)
- [ ] Telegram-Integration in Planungslogik (EV-Bedarf via Fahrer-Abfrage)
- [ ] Vehicle-Polling Bugfixes (SoC veraltet/falsch im Dashboard)
- [ ] Charge Sequencer Verbesserung (sofortige Transition bei Fahrzeugwechsel)
- [ ] Verbrauchsprognose (Hochrechnung Hausverbrauch für Planung)
- [ ] Statische Euro-Ladegrenzen durch dynamische Planung ersetzen
- [ ] Konfiguration bleibt für Anwender beherrschbar und übersichtlich

### Out of Scope

- ORA Vehicle Provider — separates Projekt, eigener Provider wird später geschrieben
- Mobile App — Web-Dashboard reicht, Telegram für Interaktion
- Multi-Wallbox-Support — aktuell 1 Wallbox im Setup
- Cloud-basierte KI (ChatGPT/Claude API für Echtzeit-Entscheidungen) — zu langsam, zu teuer, Abhängigkeit

## Context

**Bestehendes System (v5):**
Das Add-on existiert bereits mit funktionierender evcc-Anbindung, Vehicle-Providern, Charge Sequencer und Telegram-Integration. Der Kern-Optimizer arbeitet derzeit regelbasiert mit Perzentil-Schwellen (P20/P30/P40/P60/P80) und einem DQN-basierten RL-Agent im Shadow-Modus. Die statischen Euro-Ladegrenzen (ev_max_price_ct, battery_max_price_ct) bestimmen aktuell, ob Netzladen erlaubt ist — unabhängig von der tatsächlichen Preislage.

**Bekannte Probleme:**
- Vehicle-Polling zeigt veralteten/falschen SoC im Dashboard
- Stale-Detection für Wallbox-verbundene Fahrzeuge unzuverlässig
- Charge Sequencer reagiert nicht sofort bei Fahrzeugwechsel (bis 15 Min Verzögerung)
- RL-Agent Bootstrap lädt zu viele Daten, langsamer Start
- Web-Server nicht thread-safe, Race Conditions bei State-Updates
- Keine Config-Validierung beim Start

**Hardware-Setup:**
- 1 Wallbox, 3 EVs (Kia, Renault, ORA)
- PV-Anlage (Daten über evcc)
- Hausbatterie (Kapazität konfigurierbar)
- Dynamischer Stromtarif (Preisdaten über evcc)
- Home Assistant als Host-System

**Datenquellen (alle via evcc):**
- Strompreise: Grid-Tariff Forecast via evcc REST API
- PV-Prognose: Solar-Tariff via evcc REST API
- Batterie-Status: evcc /api/state
- Wallbox/Loadpoint-Status: evcc /api/state
- Vehicle SoC: Eigene Provider (Kia, Renault, evcc, Custom, Manual)

## Constraints

- **Runtime**: Docker-Container auf HA (auch Raspberry Pi) — RL-Modell muss leichtgewichtig sein (kleines NN, kein großes Framework)
- **Datenquelle**: evcc ist die einzige Quelle für Preise, PV und Batterie-Status — Planer muss mit evcc-API-Datenformat arbeiten
- **Latenz**: Entscheidungszyklus alle 15 Min (konfigurierbar) — Planer muss innerhalb von Sekunden rechnen
- **Fahrer-Interaktion**: Telegram ist der einzige Kanal für Fahrer-Kommunikation — kein HA-Frontend für Fahrer
- **Abwärtskompatibilität**: Bestehende vehicles.yaml und drivers.yaml Konfiguration soll erhalten bleiben
- **Architektur**: Python-only, keine zusätzlichen Datenbanken über InfluxDB hinaus

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Statische Schwellenwerte durch prädiktiven Planer ersetzen | Schwellenwerte können die Preislage nicht kontextabhängig bewerten | — Pending |
| Hybrid-RL (Residual Learning) statt reines RL oder reine Formeln | RL lernt Korrekturen zum Planer — leichter zu trainieren, transparenter als End-to-End RL | — Pending |
| Hausakku-Puffer dynamisch statt fester Mindest-SoC | Puffer-Bedarf hängt von Situation ab (Wetter, Tageszeit, erwarteter Verbrauch) | — Pending |
| Transparenz als Kernfeature | Nutzer muss Entscheidungen verstehen um System zu vertrauen und korrekt zu konfigurieren | — Pending |
| Kein Cloud-LLM für Echtzeit-Entscheidungen | Latenz, Kosten, Abhängigkeit — numerische Optimierung braucht keine Sprachmodelle | — Pending |
| evcc als zentrale Datenquelle beibehalten | Vereinfacht Architektur, evcc abstrahiert bereits PV-Wechselrichter und Stromtarif-APIs | — Pending |

---
*Last updated: 2026-02-22 after initialization*
