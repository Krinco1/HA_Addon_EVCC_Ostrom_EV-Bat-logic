# Requirements: SmartLoad v6

**Defined:** 2026-02-22
**Core Value:** Das System trifft zu jedem Zeitpunkt die wirtschaftlich beste Energieentscheidung unter Berücksichtigung aller verfügbaren Informationen — und der Nutzer versteht warum.

## v1 Requirements

Requirements for v6.0 release. Each maps to roadmap phases.

### Reliability

- [x] **RELI-01**: Vehicle SoC wird korrekt und aktuell angezeigt, auch wenn Fahrzeug an Wallbox angeschlossen ist
- [x] **RELI-02**: Charge Sequencer wechselt sofort zum nächsten Fahrzeug wenn aktuelles Fahrzeug fertig geladen ist (keine 15-Min-Verzögerung)
- [x] **RELI-03**: Web-Server State-Updates sind thread-safe — keine Race Conditions zwischen Decision-Loop, Web-Requests und Polling-Threads
- [x] **RELI-04**: Ungültige Konfiguration wird beim Start erkannt und mit klarer Fehlermeldung gemeldet
- [x] **RELI-05**: RL Bootstrap begrenzt Speicherverbrauch und zeigt Fortschritt an

### Prädiktive Planung

- [x] **PLAN-01**: System erstellt einen 24-48h Rolling-Horizon Energieplan der Batterie und EV gemeinsam optimiert
- [ ] **PLAN-02**: Statische Euro-Ladegrenzen (ev_max_price_ct, battery_max_price_ct) werden durch dynamische planbasierte Optimierung ersetzt
- [ ] **PLAN-03**: Hausakku-Mindest-SoC passt sich situationsabhängig an (Tageszeit, PV-Prognose, erwarteter Verbrauch, Preislage)
- [x] **PLAN-04**: Hausverbrauch wird aus HA-Datenbank/InfluxDB-Historie hochgerechnet und in Planung berücksichtigt
- [x] **PLAN-05**: PV-Ertragsprognose wird via evcc Solar-Tariff API bezogen und in den 24-48h Plan integriert

### Transparenz

- [ ] **TRAN-01**: Jede Entscheidung wird mit menschenlesbarer Begründung begleitet ("Lade Kia jetzt weil Preis im unteren 20% und Abfahrt in 6h")
- [ ] **TRAN-02**: Dashboard zeigt 24-48h Zeitstrahl-Ansicht des Plans mit Preis-Overlay und geplanten Lade-/Entladezeitfenstern
- [ ] **TRAN-03**: Dashboard zeigt RL vs Planer Vergleichsdaten (Win-Rate, Kostenvergleich)
- [ ] **TRAN-04**: Dashboard zeigt historischen Vergleich: was geplant war vs was tatsächlich passiert ist

### Fahrer-Interaktion

- [ ] **DRIV-01**: Nutzer kann über Dashboard und Telegram jederzeit eine Sofort-Ladung auslösen die den Plan überschreibt
- [ ] **DRIV-02**: System fragt Fahrer proaktiv via Telegram nach Abfahrtszeit wenn Fahrzeug angesteckt wird
- [ ] **DRIV-03**: Multi-EV Priorisierung basiert auf Fahrer-Kontext (Abfahrtszeit, Bedarf) statt nur SoC-Ranking

### Lernendes System

- [ ] **LERN-01**: RL-Agent lernt Korrekturen zum Planer (Residual Learning) statt eigenständige Entscheidungen
- [ ] **LERN-02**: System erkennt und adaptiert saisonale Muster (Verbrauch, PV-Ertrag, Preisverhalten über Jahreszeiten)
- [ ] **LERN-03**: System lernt angemessene Reaktionszeiten (wann Plan sofort anpassen vs Abweichung abwarten)
- [ ] **LERN-04**: System lernt die Zuverlässigkeit aller Prognosen (PV, Preis, Verbrauch) und korrigiert künftige Planungen mit Konfidenz-Faktoren

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Fahrer-Interaktion

- **DRIV-04**: Emergency Alert via Telegram wenn Fahrzeug nicht rechtzeitig voll wird (Deadline-Warnung)

### Infrastruktur

- **INFR-01**: Health-Check Endpoint validiert Erreichbarkeit aller Abhängigkeiten (evcc, InfluxDB, Vehicle APIs)
- **INFR-02**: API-Endpoints mit Authentifizierung schützen (X-API-Key Header)
- **INFR-03**: Request-Validierung auf POST-Endpoints mit Schema-Prüfung

## Out of Scope

| Feature | Reason |
|---------|--------|
| Cloud-LLM für Echtzeit-Entscheidungen | Latenz, Kosten, Abhängigkeit — numerische Optimierung braucht keine Sprachmodelle |
| V2G / Vehicle-to-Home | Hardware (bidirektionaler Lader) nicht verfügbar |
| Appliance Scheduling | HA Native Automations sind besser geeignet — nicht SmartLoads Domäne |
| Mobile App | Web-Dashboard + Telegram decken alle Use Cases ab |
| Multi-Wallbox Support | Aktuelles Hardware-Setup hat 1 Wallbox |
| ORA Vehicle Provider | Separates Projekt — eigener Provider wird später geschrieben |
| Per-Minute Decision Cycles | Erhöht API-Last, Stromtarife sind stündlich — 15-Min-Zyklus mit Event-Triggern reicht |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RELI-01 | Phase 2 | Complete |
| RELI-02 | Phase 2 | Complete |
| RELI-03 | Phase 1 | Complete — 01-01-PLAN.md |
| RELI-04 | Phase 1 | Complete — 01-02-PLAN.md |
| RELI-05 | Phase 2 | Complete — 02-02-PLAN.md |
| PLAN-01 | Phase 4 | Complete |
| PLAN-02 | Phase 4 | Pending |
| PLAN-03 | Phase 5 | Pending |
| PLAN-04 | Phase 3 | Complete |
| PLAN-05 | Phase 3 | Complete |
| TRAN-01 | Phase 6 | Pending |
| TRAN-02 | Phase 6 | Pending |
| TRAN-03 | Phase 8 | Pending |
| TRAN-04 | Phase 6 | Pending |
| DRIV-01 | Phase 7 | Pending |
| DRIV-02 | Phase 7 | Pending |
| DRIV-03 | Phase 7 | Pending |
| LERN-01 | Phase 8 | Pending |
| LERN-02 | Phase 8 | Pending |
| LERN-03 | Phase 8 | Pending |
| LERN-04 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-22 after roadmap creation — all 21 requirements mapped*
