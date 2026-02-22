"""
HA energy entity discovery for EVCC-Smartload.

Discovers which energy entities are configured in Home Assistant's Energy Dashboard,
and detects unconfigured entities that probably should be included.

Warning display policy (user decision from CONTEXT.md):
  Warnings are displayed BOTH as dashboard banner AND as detailed log entries
  with entity IDs and friendly names.

Thread safety:
  run_entity_discovery() should be called from a daemon thread (threading.Thread
  with daemon=True). See Research Pitfall 3: asyncio.run() in the main thread
  blocks the decision loop. The caller stores the result dict in a thread-safe
  object (e.g., StateStore or a threading.Lock-guarded dict).

Design decision: single unified profile (no weekday/weekend split for now).
InfluxDB is the primary history source; HA is used for entity validation only.
"""

import asyncio
import threading
from typing import Dict, List, Optional

import aiohttp
import requests

from logging_util import log

# WebSocket connection timeout — avoids hanging on unresponsive HA
WS_TIMEOUT_SECONDS = 10

# HA device class and state class values identifying energy sensors
ENERGY_DEVICE_CLASS = "energy"
ENERGY_STATE_CLASSES = {"total", "total_increasing"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_entity_discovery(ha_url: str, token: str) -> dict:
    """Discover configured and unconfigured HA energy entities.

    Main entry point. Called once at startup from a daemon thread.
    Results are stored by the caller in a thread-safe dict.

    If ha_url or token are empty, discovery is skipped (non-critical path).
    If WebSocket fails, returns error dict with empty entity lists.
    If unconfigured entities are found, logs German warning messages.

    Args:
        ha_url: HA base URL (e.g., "http://supervisor/core" or
                "http://homeassistant.local:8123")
        token: HA Long-Lived Access Token or SUPERVISOR_TOKEN

    Returns:
        dict with keys: "configured" (list), "unconfigured" (list),
                         "warnings" (list[str]), "error" (str or None)
    """
    if not ha_url or not token:
        log("info", "HA energy discovery: ha_url or ha_token not configured, skipping")
        return {"configured": [], "unconfigured": [], "warnings": [], "error": "not configured"}

    # --- Step 1: WebSocket energy/get_prefs ---
    prefs = fetch_ha_energy_prefs(ha_url, token)
    if not prefs:
        log("warning",
            "HA energy discovery: WebSocket energy/get_prefs failed — skipping entity validation")
        return {
            "configured": [],
            "unconfigured": [],
            "warnings": [],
            "error": "WebSocket failed",
        }

    # --- Step 2: Parse configured entities from energy dashboard ---
    configured = discover_configured_entities(prefs)

    # --- Step 3: Find unconfigured entities via REST /api/states ---
    unconfigured = find_unconfigured_energy_entities(ha_url, token, configured)

    # --- Step 4: Build warnings for unconfigured entities ---
    warnings: List[str] = []
    if unconfigured:
        entity_ids = [e["entity_id"] for e in unconfigured]
        entity_list_str = ", ".join(entity_ids)
        n = len(unconfigured)
        warning_msg = (
            f"HA Energy Dashboard: {n} Energie-Entities nicht konfiguriert: "
            f"{entity_list_str}"
        )
        log("warning", warning_msg)

        # Detailed log with friendly names for each entity
        for entity in unconfigured:
            eid = entity["entity_id"]
            fname = entity.get("friendly_name", "")
            log("warning",
                f"  Nicht konfiguriert: {eid}"
                + (f" ({fname})" if fname else ""))

        warnings.append(warning_msg)

    log("info",
        f"HA energy discovery: {len(configured)} konfiguriert, "
        f"{len(unconfigured)} nicht konfiguriert")

    return {
        "configured": configured,
        "unconfigured": unconfigured,
        "warnings": warnings,
        "error": None,
    }


# ---------------------------------------------------------------------------
# WebSocket: energy/get_prefs
# ---------------------------------------------------------------------------

def fetch_ha_energy_prefs(ha_url: str, token: str) -> dict:
    """Fetch HA energy preferences via WebSocket (synchronous wrapper).

    Runs the async WebSocket call in a new event loop via asyncio.run().
    Must be called from a non-async context (e.g., a daemon thread).

    Args:
        ha_url: HA base URL
        token: HA access token

    Returns:
        Energy prefs dict from HA, or {} on any failure.
    """
    try:
        return asyncio.run(_fetch_energy_prefs_async(ha_url, token))
    except Exception as e:
        log("warning", f"HA energy/get_prefs failed: {e}")
        return {}


async def _fetch_energy_prefs_async(ha_url: str, token: str) -> dict:
    """Async WebSocket implementation for energy/get_prefs.

    Protocol (from HA WebSocket API docs):
      1. Connect — HA sends {"type": "auth_required"}
      2. Send {"type": "auth", "access_token": "<token>"}
      3. HA sends {"type": "auth_ok"} on success
      4. Send {"id": 1, "type": "energy/get_prefs"}
      5. HA sends {"id": 1, "type": "result", "success": true, "result": {...}}

    Args:
        ha_url: HA base URL (http or https)
        token: HA access token

    Returns:
        Energy prefs result dict from HA, or {} on failure.
    """
    # Convert http URL to ws URL
    ws_url = (
        ha_url.rstrip("/")
        .replace("https://", "wss://")
        .replace("http://", "ws://")
    )
    ws_url += "/api/websocket"

    timeout = aiohttp.ClientTimeout(total=WS_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(ws_url) as ws:
            # Step 1: receive auth_required
            msg = await ws.receive_json()
            if msg.get("type") != "auth_required":
                log("warning",
                    f"HA WebSocket: unexpected first message type: {msg.get('type')!r}")
                return {}

            # Step 2: authenticate
            await ws.send_json({"type": "auth", "access_token": token})

            # Step 3: verify auth_ok
            auth_result = await ws.receive_json()
            if auth_result.get("type") != "auth_ok":
                log("warning",
                    f"HA WebSocket auth failed: {auth_result.get('type')!r} "
                    f"(message: {auth_result.get('message', '')})")
                return {}

            # Step 4: request energy preferences
            await ws.send_json({"id": 1, "type": "energy/get_prefs"})

            # Step 5: receive result
            result = await ws.receive_json()
            if not result.get("success"):
                log("warning",
                    f"HA energy/get_prefs returned error: {result.get('error')}")
                return {}

            return result.get("result", {})


# ---------------------------------------------------------------------------
# Entity parsing helpers
# ---------------------------------------------------------------------------

def discover_configured_entities(prefs: dict) -> List[str]:
    """Extract configured energy entity IDs from HA energy dashboard preferences.

    Parses grid sources for consumption (flow_from) and solar feed-in (flow_to)
    entity IDs that are explicitly configured in the HA Energy Dashboard.

    Args:
        prefs: Energy prefs dict from HA energy/get_prefs result

    Returns:
        Sorted list of configured energy entity ID strings.
    """
    configured: List[str] = []

    energy_sources = prefs.get("energy_sources", [])
    for source in energy_sources:
        source_type = source.get("type", "")

        if source_type == "grid":
            # Consumption: flow_from[].stat_energy_from
            for flow in source.get("flow_from", []):
                entity_id = flow.get("stat_energy_from")
                if entity_id and entity_id not in configured:
                    configured.append(entity_id)

            # Solar feed-in: flow_to[].stat_energy_to
            for flow in source.get("flow_to", []):
                entity_id = flow.get("stat_energy_to")
                if entity_id and entity_id not in configured:
                    configured.append(entity_id)

        elif source_type == "solar":
            # Solar production: stat_energy_from
            entity_id = source.get("stat_energy_from")
            if entity_id and entity_id not in configured:
                configured.append(entity_id)

        elif source_type == "battery":
            # Battery charge/discharge entities
            for field in ("stat_energy_from", "stat_energy_to"):
                entity_id = source.get(field)
                if entity_id and entity_id not in configured:
                    configured.append(entity_id)

    return sorted(configured)


def find_unconfigured_energy_entities(
    ha_url: str,
    token: str,
    configured: List[str],
) -> List[Dict]:
    """Find energy sensors not configured in HA Energy Dashboard.

    Queries HA REST API /api/states to find all entities with:
      - attributes.device_class == "energy"
      - attributes.state_class in {"total", "total_increasing"}

    Excludes entities already in the configured list.

    Args:
        ha_url: HA base URL
        token: HA access token
        configured: List of already-configured entity IDs to exclude

    Returns:
        List of {"entity_id": str, "friendly_name": str} dicts for
        entities that could be relevant but are not in the Energy Dashboard.
    """
    try:
        resp = requests.get(
            f"{ha_url.rstrip('/')}/api/states",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        states = resp.json()
    except Exception as e:
        log("warning", f"HA REST /api/states failed: {e}")
        return []

    unconfigured: List[Dict] = []
    configured_set = set(configured)

    for state in states:
        entity_id: str = state.get("entity_id", "")
        attributes: dict = state.get("attributes", {})

        # Filter by energy device class and relevant state class
        device_class = attributes.get("device_class", "")
        state_class = attributes.get("state_class", "")

        if device_class != ENERGY_DEVICE_CLASS:
            continue
        if state_class not in ENERGY_STATE_CLASSES:
            continue

        # Skip already-configured entities
        if entity_id in configured_set:
            continue

        friendly_name = attributes.get("friendly_name", "")
        unconfigured.append({"entity_id": entity_id, "friendly_name": friendly_name})

    return unconfigured


# ---------------------------------------------------------------------------
# Startup helper: run discovery in a daemon thread
# ---------------------------------------------------------------------------

def start_entity_discovery_thread(ha_url: str, token: str, result_store: dict) -> threading.Thread:
    """Launch HA entity discovery in a background daemon thread.

    Prevents blocking the main decision loop during startup (Research Pitfall 3).
    Results are written to result_store dict under key "ha_energy" when complete.

    Usage:
        store = {}
        t = start_entity_discovery_thread(cfg.ha_url, cfg.ha_token, store)
        # main loop continues; store["ha_energy"] available later

    Args:
        ha_url: HA base URL
        token: HA access token
        result_store: Shared dict; "ha_energy" key is set when discovery completes

    Returns:
        The started daemon thread (caller may join() if desired, but not required).
    """

    def _discover():
        result = run_entity_discovery(ha_url, token)
        result_store["ha_energy"] = result

    t = threading.Thread(target=_discover, daemon=True, name="ha-energy-discovery")
    t.start()
    return t
