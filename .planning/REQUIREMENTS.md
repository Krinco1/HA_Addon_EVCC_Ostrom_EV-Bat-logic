# Requirements: SmartLoad v6

**Defined:** 2026-02-22
**Core Value:** Das System trifft zu jedem Zeitpunkt die wirtschaftlich beste Energieentscheidung unter Berücksichtigung aller verfügbaren Informationen — und der Nutzer versteht warum.

## v1 Requirements

Requirements for v6.0 release. Each maps to roadmap phases.

### Reliability

- [ ] **RELI-01**: Vehicle SoC wird korrekt und aktuell angezeigt, auch wenn Fahrzeug an Wallbox angeschlossen ist
- [ ] **RELI-02**: Charge Sequencer wechselt sofort zum nächsten Fahrzeug wenn aktuelles Fahrzeug fertig geladen ist (keine 15-Min-Verzögerung)
- [ ] **RELI-03**: Web-Server State-Updates sind thread-safe — keine Race Conditions zwischen Decision-Loop, Web-Requests und Polling-Threads
- [ ] **RELI-04**: Ungültige Konfiguration wird beim Start erkannt und mit klarer Fehlermeldung gemeldet
- [ ] **RELI-05**: RL Bootstrap begrenzt Speicherverbrauch und zeigt Fortschritt an

### Prädiktive Planung

- [ ] **PLAN-01**: System erstellt einen 24-48h Rolling-Horizon Energieplan der Batterie und EV gemeinsam optimiert
- [ ] **PLAN-02**: Statische Euro-Ladegrenzen (ev_max_price_ct, battery_max_price_ct) werden durch dynamische planbasierte Optimierung ersetzt
- [ ] **PLAN-03**: Hausakku-Mindest-SoC passt sich situationsabhängig an (Tageszeit, PV-Prognose, erwarteter Verbrauch, Preislage)
- [ ] **PLAN-04**: Hausverbrauch wird aus HA-Datenbank/InfluxDB-Historie hochgerechnet und in Planung berücksichtigt
- [ ] **PLAN-05**: PV-Ertragsprognose wird via evcc Solar-Tariff API bezogen und in den 24-48h Plan integriert

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
| RELI-01 | — | Pending |
| RELI-02 | — | Pending |
| RELI-03 | — | Pending |
| RELI-04 | — | Pending |
| RELI-05 | — | Pending |
| PLAN-01 | — | Pending |
| PLAN-02 | — | Pending |
| PLAN-03 | — | Pending |
| PLAN-04 | — | Pending |
| PLAN-05 | — | Pending |
| TRAN-01 | — | Pending |
| TRAN-02 | — | Pending |
| TRAN-03 | — | Pending |
| TRAN-04 | — | Pending |
| DRIV-01 | — | Pending |
| DRIV-02 | — | Pending |
| DRIV-03 | — | Pending |
| LERN-01 | — | Pending |
| LERN-02 | — | Pending |
| LERN-03 | — | Pending |
| LERN-04 | — | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 0
- Unmapped: 21 ⚠️

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-22 after initial definition*
