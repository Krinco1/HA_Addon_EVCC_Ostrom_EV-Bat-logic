# Phase 5: Dynamic Buffer - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

The battery minimum SoC adapts situationally — higher when PV forecast confidence is low or prices are flat, lower when cheap solar is reliably incoming. Includes a DynamicBufferCalc engine, dashboard logging of all adjustments, and a 2-week observation mode before going live. Hard 10% floor always enforced.

</domain>

<decisions>
## Implementation Decisions

### Buffer Formula & Aggressiveness
- Conservative approach: minimum buffer 20% even at highest confidence (hard floor remains 10% but practical minimum is 20%)
- PV-Confidence is the dominant input; price spread and time of day act as modifiers
- Recalculation interval: every 15 minutes
- All calculation inputs logged per event

### Dashboard Logging
- Dual view: Line chart showing buffer level over time + expandable detail table per event
- Full input visibility per event: PV confidence, price spread, time of day, expected PV production, old buffer → new buffer, reason for change
- 7-day history in chart view, older data scrollable in log
- No notifications — passive logging only, user checks dashboard on demand

### Observation Mode
- "Would have changed" log: entries show what DynamicBufferCalc would have done, clearly marked as simulation
- Auto-transition to live after 14 days
- User can manually activate live early OR extend observation period beyond 2 weeks
- Countdown/status indicator visible in dashboard during observation

### Confidence Definition
- Numeric 0-100% confidence value (continuous, not discrete levels)
- Combined data sources: historical forecast accuracy (last 7 days) + current weather conditions
- Displayed as collapsible widget: collapsed = single summary line with key info; expanded = full details + graph
- Confidence value logged with every buffer event

### Claude's Discretion
- Buffer transition behavior (gradual vs. immediate when conditions change)
- Confidence threshold at which buffer starts being lowered (somewhere above 50%)
- Observation mode status banner design and prominence
- Chart styling, exact widget layout, spacing

</decisions>

<specifics>
## Specific Ideas

- Collapsed confidence widget should show just one info line — expanded reveals full detail view with graph
- "Hätte geändert" entries in observation mode should use the exact same format as live entries, just visually distinguished (e.g., dashed line, muted color, or label)
- User wants to understand every buffer decision by looking at the log — full transparency

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-dynamic-buffer*
*Context gathered: 2026-02-23*
