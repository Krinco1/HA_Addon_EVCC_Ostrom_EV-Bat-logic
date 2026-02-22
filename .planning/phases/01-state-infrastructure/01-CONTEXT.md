# Phase 1: State Infrastructure - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Thread-safe StateStore with RLock and startup config validation. All state writes go through a single guarded StateStore; web server becomes read-only consumer. Invalid configuration is caught before any network connections are made. This is the foundation for all subsequent phases.

</domain>

<decisions>
## Implementation Decisions

### Config-Fehlerbehandlung
- Config-Fehler werden sowohl im Container-Log als auch auf einer Dashboard-Fehlerseite (Port 8099) angezeigt
- Abstufung: Kritische Fehler (z.B. fehlende evcc_url) stoppen das Add-on — Web-Server startet nur für Fehlerseite, keine Optimierung. Nicht-kritische Fehler (z.B. fehlender optionaler Parameter) nutzen sichere Defaults mit Warnung
- Die Fehlerseite läuft auf dem bestehenden Web-Server Port 8099

### Config-Migration
- Bestehende statische Euro-Limits (ev_max_price_ct, battery_max_price_ct) werden als Fallback behalten — wenn der Planer ausfällt, greifen die alten Limits als Sicherheitsnetz
- vehicles.yaml und drivers.yaml bleiben abwärtskompatibel — bestehendes Format wird beibehalten, neue Felder sind optional
- Migration erfolgt still — keine sichtbare Übergangsmeldung beim ersten v6-Start

### State-Konsistenz
- Dashboard zeigt live neue Werte sofort an, mit kurzer visueller Markierung was sich geändert hat
- Doppelte Feedback-Strategie: Kurzes Highlight (1-2 Sek) bei Wertänderung UND dauerhafter Timestamp ("vor X Min aktualisiert") pro Datenpunkt
- Dashboard-Updates via Server-Sent Events (SSE) oder WebSocket — Server pushed Änderungen in Echtzeit statt Polling

### Claude's Discretion
- Welche Config-Felder als kritisch vs. nicht-kritisch eingestuft werden (Claude beurteilt was ohne Funktion unmöglich ist vs. was mit sinnvollen Defaults laufen kann)
- Detailtiefe der Fehlermeldungen und Korrekturvorschläge auf der Fehlerseite
- Neue v6-Config-Felder: Claude wählt sinnvolle Default-Strategie (auto-Defaults vs. explizite Konfiguration je nach Feld)
- Dashboard-Verhalten bei Backend-Verbindungsabbruch (Banner, Ausgrauen, oder Kombination)

</decisions>

<specifics>
## Specific Ideas

- SSE bevorzugt gegenüber WebSocket wegen Einfachheit (unidirektional, HTTP-basiert, kein zusätzliches Protokoll)
- Fehlerseite soll auf dem gleichen Port 8099 laufen wie das normale Dashboard — nur anderer Content wenn Config ungültig
- Highlight bei Wertänderung ähnlich wie bei Trading-Dashboards (kurzes Aufleuchten in Grün/Rot bei Änderung)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-state-infrastructure*
*Context gathered: 2026-02-22*
