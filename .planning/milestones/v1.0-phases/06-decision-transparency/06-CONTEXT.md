# Phase 6: Decision Transparency - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Dashboard zeigt den vollständigen 24-48h Plan als interaktive Timeline, erklärt jede Slot-Entscheidung mit echten Zahlen (Preise, Kosten, Zeitfenster), und vergleicht historisch was geplant war vs. was tatsächlich passiert ist. Neue Steuerungsfeatures (Override, Telegram) gehören in Phase 7.

</domain>

<decisions>
## Implementation Decisions

### Plan-Timeline Darstellung
- Gantt-Bars mit Preisoverlay (Preislinie über den Aktionsbalken)
- Rollend 24h ab jetzt als Default-Zeitfenster
- Farbcodierung:
  - Grün: Batterie laden (Netz oder PV)
  - Orange: Batterie entladen (Einspeisung/Hausverbrauch)
  - Blau: EV laden (pro Fahrzeug unterscheidbar)
  - Gelb/Gold: PV-Erzeugung als Hintergrundbereich
  - Rot/Grau: Preislinie
- Interaktion: Hover = kompakte Kurzinfo, Klick = volle Erklärung (Progressive Disclosure)

### Entscheidungs-Erklärungen
- Sprache: Deutsch (konsistent mit bestehendem Dashboard)
- Hover-Kurzinfo: Knapp und zahlenbasiert — "Laden: Preis 8,2 ct (Rang 3/96), Abfahrt in 6h, Warten +1,40 EUR"
- Klick-Erklärung: Voller erklärender Satz — "Kia wird jetzt geladen, weil der Preis mit 8,2 ct im unteren 20% des Forecasts liegt und die Abfahrt in 6h ist — Warten würde ca. 1,40 EUR mehr kosten."
- Kernwerte in jeder Erklärung:
  - Aktueller Preis (ct/kWh) + Rang im Forecast
  - Kostendelta ("Warten würde X EUR mehr kosten")
  - Zeitfenster (Stunden bis Abfahrt / bis nächste günstige Phase)
  - PV-Erwartung ("In 3h werden ~2,4 kWh PV erwartet")
  - Buffer-Status ("Puffer bei 35%, Ziel 20%")

### Plan vs. Realität Vergleich
- Duale Darstellung: Overlay-Chart für schnellen Überblick + Tabelle für Details
- Zeitraum: Letzte 24h als Default, 7-Tage-Ansicht per Toggle
- Abweichungs-Hervorhebung: Kostenbasiert in EUR ("Abweichung hat 0,30 EUR gekostet" / "Plan hätte 0,80 EUR gespart"), farblich unterstützt (grün = gespart, rot = teurer)

### Dashboard-Integration
- 3 Tabs im Dashboard:
  - **Haupttab** (existierend): Status, Buffer, Events, Fahrzeuge
  - **Plan-Tab** (neu): 24h Rolling Timeline mit Hover/Klick-Erklärungen
  - **Historie-Tab** (neu): Planned-vs-Actual Vergleich mit Kostenmetrik
- Tabs halten alles zusammen ohne Hauptansicht zu überladen

### Claude's Discretion
- Gantt-Bar-Format (exaktes Chart-Rendering, SVG vs. Canvas vs. Library)
- Exaktes Layout der Kurzinfo-Tooltips
- Tabellen-Spaltendesign im Historie-Tab
- Chart-Styling (Linienstärke, Opacity, Animationen)
- Overlay-Chart Technik (wie geplante vs. tatsächliche Bars dargestellt werden)
- Tab-Navigation Implementierung (CSS-Tabs, JS-basiert, etc.)

</decisions>

<specifics>
## Specific Ideas

- Progressive Disclosure durchgängig: Überblick zuerst, Detail bei Interaktion
- Kostenbasierte Bewertung als roter Faden — der User will wissen was Abweichungen in EUR bedeuten, nicht nur dass sie existieren
- Erklärungstexte im Stil: konkrete Zahlen + kausale Verknüpfung ("weil... — Warten würde...")
- Konsistentes Muster: Chart für Überblick, Tabelle/Text für Details (gilt für Timeline UND Historie)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-decision-transparency*
*Context gathered: 2026-02-23*
