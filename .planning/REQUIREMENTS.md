# Requirements: SmartLoad v6

**Defined:** 2026-02-27
**Core Value:** Das System trifft zu jedem Zeitpunkt die wirtschaftlich beste Energieentscheidung unter Berücksichtigung aller verfügbaren Informationen — und der Nutzer versteht warum.

## v1.1 Requirements

Requirements for milestone v1.1: Smart EV Charging & evcc Control.

### Vehicle SoC Polling

- [x] **SOC-01**: KiaProvider liefert zuverlässig SoC-Daten auch wenn Fahrzeug nicht an der Wallbox ist (force_refresh statt cached_state, 60-Min Default-Intervall)
- [x] **SOC-02**: RenaultProvider nutzt persistente Session mit Token-Caching ohne die reguläre MY Renault App zu blockieren (gleicher User-Account, Session-Koexistenz)
- [ ] **SOC-03**: "Poll Now" Button im Dashboard löst sofortigen SoC-Abruf pro Fahrzeug aus (mit Rate-Limiting, Cooldown-Anzeige)
- [ ] **SOC-04**: Dashboard zeigt Datenalter und Datenquelle (API/Wallbox/Manuell) pro Fahrzeug an

### evcc Mode Control

- [ ] **MODE-01**: SmartLoad setzt aktiv den evcc-Lademodus (pv/minpv/now) passend zum LP-Plan über die bestehende set_loadpoint_mode() API
- [ ] **MODE-02**: Smart Mode Selection: Modus wird basierend auf Preis-Perzentil und Abfahrts-Urgency gewählt (günstig=now, moderat=minpv, teuer=pv, dringend=now)
- [ ] **MODE-03**: Override-Erkennung: manuelle evcc-Modusänderungen werden erkannt durch Vergleich des zuletzt gesetzten Modus mit dem aktuellen evcc-State (kein Extra-API-Call)
- [ ] **MODE-04**: Override-Respektierung: manuelle Overrides gelten bis Ladevorgang abgeschlossen (Auto absteckt) oder Ziel-SoC erreicht, SmartLoad passt Gesamtplan an um Override auszugleichen
- [ ] **MODE-05**: Override-Status wird transparent im Dashboard angezeigt ("evcc Mode gesperrt durch manuelle Änderung — SmartLoad gleicht nach Abschluss aus")

### Battery Arbitrage

- [ ] **ARB-01**: Hausakku entlädt als Zuspeiser beim EV-Schnellladen (Mode "now") wenn wirtschaftlich sinnvoll (gespeicherter Strom günstiger als aktueller Netzpreis abzgl. Effizienz)
- [ ] **ARB-02**: LP-Vorausschau-Guard: Entladung nur wenn LP keine günstigeren Netzstunden in den nächsten 6h zeigt (kein Entladen jetzt wenn in 2h billiger nachgeladen werden kann)
- [ ] **ARB-03**: Reserve-Schutz: Entladung respektiert max(battery_to_ev_floor_soc, dynamic_buffer_min_soc) als absolute Untergrenze
- [ ] **ARB-04**: DynamicBufferCalc und Arbitrage koordinieren bufferSoc-Werte ohne Konflikt (kein gegenseitiges Überschreiben)

## v2.0 Requirements

Deferred to next major milestone. Tracked but not in current roadmap.

### Dashboard Redesign

- **UI-01**: Dashboard Design an evcc Web-UI angleichen (Farbschema, Schriften, Layout-Stil)
- **UI-02**: evcc Web-UI als iframe-Tab einbetten (optional per Konfigurationsschalter)
- **UI-03**: Prüfung evcc App (github.com/evcc-io/app) Integration

## Out of Scope

| Feature | Reason |
|---------|--------|
| Force-refresh bei jedem Scheduled Poll | Kia 12V-Batterie-Drain Risiko (~200 API calls/day Limit), nur bei Poll Now und Connection Events |
| MQTT/Webhook für evcc Mode Changes | Kein Webhook in evcc verfügbar, MQTT würde neue Dependency einführen — Polling reicht (1 Cycle Latenz) |
| Batterie-Entladung unabhängig vom Preis | Wirtschaftlich unsinnig bei günstigen Netzpreisen (85% Round-Trip Effizienz) |
| Multi-Loadpoint Mode Control | Hardware: 1 Wallbox im Setup, generalisierte Multi-Loadpoint Logik unnötig für v1.1 |
| evcc vehicleSoc für nicht-angeschlossene Fahrzeuge | evcc hat keine Daten für nicht-angeschlossene Fahrzeuge, API-Provider sind die einzige Quelle |
| ORA Vehicle Provider | Separates Projekt, eigener Provider wird später geschrieben |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SOC-01 | Phase 9 | Complete |
| SOC-02 | Phase 9 | Complete |
| SOC-03 | Phase 10 | Pending |
| SOC-04 | Phase 10 | Pending |
| MODE-01 | Phase 11 | Pending |
| MODE-02 | Phase 11 | Pending |
| MODE-03 | Phase 11 | Pending |
| MODE-04 | Phase 11 | Pending |
| MODE-05 | Phase 11 | Pending |
| ARB-01 | Phase 12 | Pending |
| ARB-02 | Phase 12 | Pending |
| ARB-03 | Phase 12 | Pending |
| ARB-04 | Phase 12 | Pending |

**Coverage:**
- v1.1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

---
*Requirements defined: 2026-02-27*
*Last updated: 2026-02-27 after roadmap creation (v1.1 phases 9-12)*
