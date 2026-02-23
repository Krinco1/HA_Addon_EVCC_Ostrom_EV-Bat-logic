"""
Notification Manager — v5.0 NEW

Direct Telegram Bot API integration. No Home Assistant automation needed.
One Python thread handles long-polling for incoming responses.

Design:
  Smartload → Telegram Bot API → Fahrer (Inline-Buttons)
  Fahrer drückt Button → callback_query → _poll_loop → on_soc_response()
  on_soc_response() → ChargeSequencer.add_request()
"""

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import requests

from logging_util import log


# =============================================================================
# Telegram Bot
# =============================================================================

class TelegramBot:
    """Direct Telegram Bot API wrapper with Long-Polling thread."""

    _API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str):
        self.token = token
        self.offset = 0
        self._callbacks: Dict[str, Callable] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_polling(self):
        if not self.token:
            log("info", "Telegram: no token → polling disabled")
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log("info", "Telegram Bot polling started")

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    # Long-polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self):
        while self._running:
            try:
                resp = requests.get(
                    self._API.format(token=self.token, method="getUpdates"),
                    params={"offset": self.offset, "timeout": 30},
                    timeout=35,
                )
                if resp.status_code != 200:
                    log("warning", f"Telegram poll {resp.status_code}")
                    time.sleep(5)
                    continue
                for update in resp.json().get("result", []):
                    self.offset = update["update_id"] + 1
                    self._handle_update(update)
            except requests.Timeout:
                continue
            except Exception as e:
                log("error", f"Telegram poll error: {e}")
                time.sleep(10)

    def _handle_update(self, update: Dict):
        # Inline button press
        if "callback_query" in update:
            cb = update["callback_query"]
            data = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            self._api("answerCallbackQuery", {"callback_query_id": cb["id"]})
            for prefix, handler in self._callbacks.items():
                if data.startswith(prefix):
                    try:
                        handler(chat_id, data)
                    except Exception as e:
                        log("error", f"Telegram callback error: {e}")
                    break

        # Plain text message (e.g. driver types "80")
        elif "message" in update and "text" in update["message"]:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            text = msg["text"].strip()
            if "text_handler" in self._callbacks:
                try:
                    self._callbacks["text_handler"](chat_id, text)
                except Exception as e:
                    log("error", f"Telegram text handler error: {e}")

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def register_callback(self, prefix: str, handler: Callable):
        self._callbacks[prefix] = handler

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    def send_message(
        self,
        chat_id: int,
        text: str,
        inline_keyboard: Optional[List] = None,
    ) -> bool:
        payload: Dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        return self._api("sendMessage", payload)

    def edit_message(self, chat_id: int, message_id: int, text: str) -> bool:
        return self._api(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"},
        )

    def _api(self, method: str, payload: Dict) -> bool:
        try:
            resp = requests.post(
                self._API.format(token=self.token, method=method),
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                return True
            log("warning", f"Telegram {method}: {resp.text[:200]}")
            return False
        except Exception as e:
            log("error", f"Telegram API error: {e}")
            return False


# =============================================================================
# Notification Manager
# =============================================================================

class NotificationManager:
    """Coordinates driver notifications via Telegram.

    Flow:
      1. Main loop detects charge opportunity → send_charge_inquiry()
      2. Driver taps inline button  → _handle_soc_callback()
      3. on_soc_response(vehicle, target_soc) → ChargeSequencer.add_request()

    Phase 7 additions:
      - /boost [Fahrzeug] command → activate Boost Charge override
      - /stop command → cancel active override
      - boost_ inline button callback → activate Boost Charge
    """

    def __init__(
        self,
        bot: TelegramBot,
        driver_manager,
        on_soc_response: Optional[Callable] = None,
    ):
        self.bot = bot
        self.drivers = driver_manager
        self.on_soc_response = on_soc_response
        self.pending_inquiries: Dict[str, datetime] = {}   # vehicle → sent_at
        # Phase 7: OverrideManager — injected by main.py as late attribute
        self.override_manager = None
        # Phase 7 Plan 02: DepartureTimeStore — injected by main.py as late attribute
        self.departure_store = None
        # Track which vehicle's departure we are currently awaiting free-text reply for
        self._pending_departure_vehicle: Optional[str] = None

        bot.register_callback("soc_", self._handle_soc_callback)
        bot.register_callback("boost_", self._handle_boost_callback)
        bot.register_callback("depart_", self._handle_departure_callback)
        bot.register_callback("text_handler", self._handle_text_message)

    # ------------------------------------------------------------------
    # Outgoing notifications
    # ------------------------------------------------------------------

    def send_charge_inquiry(
        self,
        vehicle_name: str,
        current_soc: float,
        reason: str,
        options: Optional[List[int]] = None,
    ) -> bool:
        """Ask driver: charge to what %?"""
        if options is None:
            options = [80, 100]

        driver = self.drivers.get_driver(vehicle_name)
        if not driver or not driver.telegram_chat_id:
            log("info", f"No Telegram for {vehicle_name} — skipping notification")
            return False

        # Throttle: don't re-ask within 2 hours
        if vehicle_name in self.pending_inquiries:
            age_h = (datetime.now() - self.pending_inquiries[vehicle_name]).total_seconds() / 3600
            if age_h < 2:
                return False

        # Build vehicle key for boost callback (replace spaces with underscores)
        vehicle_key = vehicle_name.replace(" ", "_")
        keyboard = [
            [
                {"text": f"🔋 {s}%", "callback_data": f"soc_{vehicle_name}_{s}"}
                for s in options
            ]
            + [{"text": "❌ Nein", "callback_data": f"soc_{vehicle_name}_skip"}],
            [{"text": "⚡ Jetzt laden!", "callback_data": f"boost_{vehicle_key}"}],
        ]

        msg = (
            f"⚡ <b>{vehicle_name}</b> ({current_soc:.0f}%)\n"
            f"{reason}\n\n"
            f"Auf wieviel % laden?"
        )

        success = self.bot.send_message(driver.telegram_chat_id, msg, keyboard)
        if success:
            self.pending_inquiries[vehicle_name] = datetime.now()
            log("info", f"Telegram: charge inquiry sent to {driver.name} for {vehicle_name}")
        return success

    def send_plug_reminder(self, vehicle_name: str, message: str):
        """Reminder: please plug in EV before quiet hours."""
        driver = self.drivers.get_driver(vehicle_name)
        if not driver or not driver.telegram_chat_id:
            return
        self.bot.send_message(driver.telegram_chat_id, f"🔌 {message}")

    def send_charge_complete(self, vehicle_name: str, final_soc: float):
        driver = self.drivers.get_driver(vehicle_name)
        if not driver or not driver.telegram_chat_id:
            return
        self.bot.send_message(
            driver.telegram_chat_id,
            f"✅ <b>{vehicle_name}</b> Ladung fertig ({final_soc:.0f}%)",
        )

    def send_switch_request(self, done_vehicle: str, next_vehicle: str, reason: str):
        """Ask next driver to plug in after previous EV is done."""
        driver = self.drivers.get_driver(next_vehicle)
        if not driver or not driver.telegram_chat_id:
            return
        self.bot.send_message(
            driver.telegram_chat_id,
            f"🔄 {done_vehicle} fertig. Bitte <b>{next_vehicle}</b> anstecken.\n{reason}",
        )

    def send_departure_inquiry(self, vehicle_name: str, current_soc: float) -> bool:
        """Phase 7-02: Ask driver when they need the vehicle.

        Sends a German-language message with 4 inline time buttons. If no
        specific driver is found for this vehicle, sends to all configured
        chat_ids. Sets _pending_departure_vehicle for free-text reply matching.
        """
        safe_name = vehicle_name.replace(" ", "_")
        keyboard = [[
            {"text": "In 2h",       "callback_data": f"depart_{safe_name}_2h"},
            {"text": "In 4h",       "callback_data": f"depart_{safe_name}_4h"},
            {"text": "In 8h",       "callback_data": f"depart_{safe_name}_8h"},
            {"text": "Morgen frueh","callback_data": f"depart_{safe_name}_morgen"},
        ]]

        msg = (
            f"Hey, der {vehicle_name} ist angeschlossen! "
            f"(SoC: {current_soc:.0f}%) Wann brauchst du ihn?"
        )

        # Find chat_ids to notify
        driver = self.drivers.get_driver(vehicle_name)
        if driver and driver.telegram_chat_id:
            chat_ids = [driver.telegram_chat_id]
        else:
            # Fall back to all configured drivers with Telegram
            chat_ids = [d.telegram_chat_id for d in self.drivers.drivers if d.telegram_chat_id]

        if not chat_ids:
            log("info", f"Telegram: no chat_id for departure inquiry ({vehicle_name}) — skipped")
            return False

        sent = False
        for chat_id in chat_ids:
            if self.bot.send_message(chat_id, msg, keyboard):
                sent = True

        if sent:
            self._pending_departure_vehicle = vehicle_name
            log("info", f"Telegram: departure inquiry sent for {vehicle_name} (SoC={current_soc:.0f}%)")
        return sent

    # ------------------------------------------------------------------
    # Incoming handlers
    # ------------------------------------------------------------------

    def _handle_soc_callback(self, chat_id: int, callback_data: str):
        """Process button reply: soc_KIA_EV9_80 or soc_KIA_EV9_skip."""
        parts = callback_data.split("_")
        if len(parts) < 3:
            return
        vehicle = "_".join(parts[1:-1])
        value = parts[-1]

        if value == "skip":
            log("info", f"Telegram: {vehicle} → driver declined")
            self.bot.send_message(chat_id, f"👍 {vehicle} wird nicht geladen.")
            self.pending_inquiries.pop(vehicle, None)
            return

        try:
            target_soc = int(value)
        except ValueError:
            return

        log("info", f"Telegram: {vehicle} → target SoC {target_soc}%")
        self.bot.send_message(
            chat_id,
            f"✅ {vehicle} wird auf <b>{target_soc}%</b> geladen.\n"
            f"Bitte sicherstellen dass das Fahrzeug angesteckt ist.",
        )
        self.pending_inquiries.pop(vehicle, None)

        if self.on_soc_response:
            self.on_soc_response(vehicle, target_soc, chat_id)

    def _handle_departure_callback(self, chat_id: int, callback_data: str):
        """Phase 7-02: Process departure inline button.

        Callback format: "depart_{safe_vehicle}_{time_str}"
        Example: "depart_KIA_EV9_4h" → vehicle "KIA EV9", time "4h"
        """
        # Strip "depart_" prefix, then split on last "_" to get time_str
        rest = callback_data[len("depart_"):]
        # Time token is always the last segment; vehicle uses underscores
        parts = rest.rsplit("_", 1)
        if len(parts) != 2:
            self.bot.send_message(
                chat_id,
                "Konnte die Zeit nicht verstehen. Versuch es mit z.B. 'in 3h' oder 'um 14:30'.",
            )
            return

        safe_vehicle, time_str = parts
        vehicle_name = safe_vehicle.replace("_", " ")

        from departure_store import parse_departure_time
        now = datetime.now(timezone.utc)
        departure = parse_departure_time(time_str, now)

        if departure is None:
            self.bot.send_message(
                chat_id,
                "Konnte die Zeit nicht verstehen. Versuch es mit z.B. 'in 3h' oder 'um 14:30'.",
            )
            return

        if self.departure_store is not None:
            self.departure_store.set(vehicle_name, departure)
            self._pending_departure_vehicle = None

        # Display in local time for user-facing confirmation
        local_departure = departure.astimezone()
        self.bot.send_message(
            chat_id,
            f"Alles klar! {vehicle_name} wird bis {local_departure.strftime('%H:%M')} fertig sein.",
        )
        log("info", f"Telegram: departure set for {vehicle_name} -> {departure.isoformat()}")

    def _handle_boost_callback(self, chat_id: int, callback_data: str):
        """Process Boost inline button: boost_KIA_EV9 → activate for 'KIA EV9'."""
        # Strip "boost_" prefix, replace underscores back to spaces
        vehicle_key = callback_data[len("boost_"):]
        vehicle_name = vehicle_key.replace("_", " ")

        log("info", f"Telegram: Boost callback for {vehicle_name} from chat {chat_id}")

        if self.override_manager is None:
            self.bot.send_message(chat_id, "Boost Charge nicht verfügbar.")
            return

        result = self.override_manager.activate(vehicle_name, "telegram", chat_id)
        if result.get("ok"):
            from override_manager import OVERRIDE_DURATION_MINUTES
            self.bot.send_message(
                chat_id,
                f"Boost Charge für <b>{vehicle_name}</b> aktiviert! "
                f"Läuft {OVERRIDE_DURATION_MINUTES} Minuten.",
            )
        elif result.get("quiet_hours_blocked"):
            self.bot.send_message(chat_id, result.get("message", "Leise-Stunden aktiv."))
        else:
            self.bot.send_message(chat_id, f"Fehler: {result.get('message', 'Unbekannt')}")

    def _handle_text_message(self, chat_id: int, text: str):
        """Process free-text reply: SoC number, /boost command, /stop command, or departure time."""
        driver = self.drivers.get_driver_by_chat_id(chat_id)

        # /boost command — Phase 7
        if text.startswith("/boost"):
            self._handle_boost_command(chat_id, text, driver)
            return

        # /stop command — Phase 7
        if text.startswith("/stop"):
            self._handle_stop_command(chat_id)
            return

        # Phase 7-02: Check if a departure inquiry is pending — handle free-text departure times
        # BEFORE falling through to numeric SoC handling (departure times like "in 3h" are not ints)
        if (
            self._pending_departure_vehicle is not None
            and self.departure_store is not None
            and self.departure_store.is_inquiry_pending(self._pending_departure_vehicle)
        ):
            from departure_store import parse_departure_time
            now = datetime.now(timezone.utc)
            departure = parse_departure_time(text, now)
            if departure is not None:
                self.departure_store.set(self._pending_departure_vehicle, departure)
                local_departure = departure.astimezone()
                vehicle_name = self._pending_departure_vehicle
                self._pending_departure_vehicle = None
                self.bot.send_message(
                    chat_id,
                    f"Alles klar! {vehicle_name} wird bis {local_departure.strftime('%H:%M')} fertig sein.",
                )
                log("info", f"Telegram: departure set via free text for {vehicle_name} -> {departure.isoformat()}")
                return
            else:
                # Couldn't parse — hint, but keep pending so they can retry
                self.bot.send_message(
                    chat_id,
                    "Hmm, das hab ich nicht verstanden. Versuch 'in 3h', 'um 14:30' oder tippe auf einen Button oben.",
                )
                return

        if not driver:
            return
        try:
            soc = int(text)
            if 10 <= soc <= 100:
                for vehicle in driver.vehicles:
                    if vehicle in self.pending_inquiries:
                        self._handle_soc_callback(chat_id, f"soc_{vehicle}_{soc}")
                        return
        except ValueError:
            pass

    def _handle_boost_command(self, chat_id: int, text: str, driver):
        """/boost [Fahrzeug] — activate Boost Charge for named (or default) vehicle."""
        if self.override_manager is None:
            self.bot.send_message(chat_id, "Boost Charge nicht verfügbar.")
            return

        # Parse vehicle name from command: "/boost KIA EV9" → "KIA EV9"
        parts = text.strip().split(None, 1)
        vehicle_name = parts[1].strip() if len(parts) > 1 else ""

        # If no vehicle specified, use driver's first vehicle (if only one exists)
        if not vehicle_name and driver and len(driver.vehicles) == 1:
            vehicle_name = driver.vehicles[0]

        if not vehicle_name:
            self.bot.send_message(
                chat_id,
                "Bitte Fahrzeug angeben: /boost KIA EV9\nOder nutze den Inline-Button."
            )
            return

        log("info", f"Telegram: /boost command for {vehicle_name} from chat {chat_id}")
        result = self.override_manager.activate(vehicle_name, "telegram", chat_id)

        if result.get("ok"):
            from override_manager import OVERRIDE_DURATION_MINUTES
            self.bot.send_message(
                chat_id,
                f"Boost Charge für <b>{vehicle_name}</b> aktiviert! "
                f"Läuft {OVERRIDE_DURATION_MINUTES} Minuten.",
            )
        elif result.get("quiet_hours_blocked"):
            self.bot.send_message(chat_id, result.get("message", "Leise-Stunden aktiv."))
        else:
            self.bot.send_message(chat_id, f"Fehler: {result.get('message', 'Unbekannt')}")

    def _handle_stop_command(self, chat_id: int):
        """/stop — cancel the active Boost Charge override."""
        if self.override_manager is None:
            self.bot.send_message(chat_id, "Override-Manager nicht verfügbar.")
            return

        log("info", f"Telegram: /stop command from chat {chat_id}")
        result = self.override_manager.cancel()

        if result.get("ok"):
            self.bot.send_message(chat_id, "Override gestoppt — Planer übernimmt.")
        else:
            self.bot.send_message(chat_id, "Kein aktiver Override.")

    def get_pending(self) -> Dict[str, str]:
        """Return pending inquiries with age for dashboard display."""
        now = datetime.now()
        return {
            v: f"{(now - ts).total_seconds() / 60:.0f}min ago"
            for v, ts in self.pending_inquiries.items()
        }
