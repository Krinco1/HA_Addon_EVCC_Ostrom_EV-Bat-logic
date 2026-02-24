---
status: complete
phase: 07-driver-interaction
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md]
started: 2026-02-23T18:00:00Z
updated: 2026-02-23T18:05:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Boost Charge Button on Dashboard
expected: Each vehicle card on the dashboard Status tab shows a "Boost Charge" button. Clicking it triggers an immediate charge — the button changes to an active state showing remaining time (out of 90 minutes). A "Boost stoppen" cancel button appears.
result: pass

### 2. Cancel Override from Dashboard
expected: While Boost Charge is active, clicking the "Boost stoppen" button cancels the override. The button reverts to the normal "Boost Charge" state and the planner resumes control on the next cycle.
result: pass

### 3. Telegram /boost Command
expected: Sending "/boost" (or "/boost [Fahrzeugname]") to the Telegram bot triggers immediate charging. Bot replies with confirmation. If only one vehicle exists, it auto-selects.
result: pass

### 4. Telegram /stop Command
expected: Sending "/stop" to the Telegram bot cancels an active Boost override. Bot replies confirming the override was cancelled.
result: pass

### 5. Boost Charge Blocked During Quiet Hours
expected: During quiet hours, pressing Boost Charge (dashboard or Telegram) is rejected with a German message explaining that boost is not available during quiet hours.
result: pass

### 6. Override Gantt Marker
expected: While Boost Charge is active, the plan timeline Gantt chart shows an orange override banner at the top of the current time slot.
result: pass

### 7. Telegram Departure Inquiry on Plug-In
expected: When a vehicle is plugged in, the Telegram bot sends a German message asking "Wann brauchst du ihn?" with 4 inline buttons: "In 2h", "In 4h", "In 8h", "Morgen frueh".
result: pass

### 8. Departure Time via Inline Button
expected: Tapping one of the inline buttons (e.g. "In 4h") sets the departure time. Bot replies with a German confirmation showing the calculated departure time.
result: pass

### 9. Departure Time via Free Text
expected: Replying with free text like "um 14:30" or "in 3 Stunden" sets the departure time. Bot confirms with the calculated time. If text is unparseable, bot asks again with a hint.
result: pass

### 10. 30-Minute Silent Fallback
expected: If no departure reply is received within 30 minutes after the inquiry, the system silently uses the configured default departure time — no extra notification is sent to the driver.
result: pass

### 11. Urgency Score on Vehicle Cards
expected: When two or more vehicles are waiting to charge, each vehicle card shows urgency info: "Dringlichkeit: X.X" with a reason like "(Abfahrt in 3h, SoC 45%)", color-coded red (>=10), amber (>=3), or blue (<3). A priority badge (P1, P2) appears on the card header.
result: pass

### 12. Urgency-Based Priority Order
expected: A vehicle departing in 2h with 50% SoC is prioritized over one departing in 12h with 40% SoC. The vehicle cards are sorted by urgency (highest first). The wallbox charges the most urgent vehicle.
result: pass

## Summary

total: 12
passed: 12
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
