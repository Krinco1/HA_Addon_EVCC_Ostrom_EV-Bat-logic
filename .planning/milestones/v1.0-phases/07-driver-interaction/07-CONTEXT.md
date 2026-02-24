# Phase 7: Driver Interaction - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Drivers can override the plan immediately (Boost Charge), the system proactively asks about departure times via Telegram when a vehicle is plugged in, and multi-EV priority uses urgency (time-to-departure vs SoC deficit) instead of SoC-only ranking. All within existing dashboard + Telegram infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Override UX
- Boost Charge button lives on each per-vehicle card on the dashboard Status tab
- Telegram: both `/boost [Fahrzeug]` command AND inline buttons in charge status notifications
- Cancel override: both dashboard button (on vehicle card) AND `/stop` Telegram command — override ends immediately, planner resumes
- Boost Charge does NOT override quiet hours — driver gets notified: "Leise-Stunden aktiv, Laden startet um [HH:MM]"

### Telegram Conversation Flow
- Language: casual German with "du" — e.g. "Hey, der Kia ist angeschlossen! Wann brauchst du ihn?"
- Reply options: inline time buttons ("In 2h" | "In 4h" | "In 8h" | "Morgen früh") AND free text parsing (e.g. "um 14:30", "in 3 Stunden")
- 30-minute reply window: silent fallback to configured default departure time — no extra notification on timeout (avoids spam)

### Multi-EV Priority Visibility
- Urgency score visible on vehicle cards: e.g. "Dringlichkeit: 4.2 (Abfahrt in 3h, SoC 45%)" — full transparency
- Priority order shown on dashboard (exact visual pattern at Claude's discretion)

### Claude's Discretion
- Override visualization in Plan tab Gantt chart (bar highlighting, banner, or both)
- Boost Charge confirmation feedback pattern (immediate reply, progress follow-up, etc.)
- Unparseable departure time handling (re-ask with hint vs best-guess-and-confirm)
- Telegram notifications on priority changes (deprioritization only vs every change vs silent)
- Urgency score in Gantt chart tooltips (or vehicle cards only)
- Wallbox swap strategy when Boost conflicts with currently charging vehicle
- Multi-override strategy (queue vs replace) — single wallbox constraint applies

</decisions>

<specifics>
## Specific Ideas

- Inline Telegram buttons are preferred for common actions (time selection, boost trigger) — minimize typing
- "du" tone consistent with a personal home system, not a corporate product
- Urgency score should show both the score number AND the natural language reason (departure time + SoC)
- Quiet hours are a hard boundary — even manual overrides respect them

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-driver-interaction*
*Context gathered: 2026-02-23*
