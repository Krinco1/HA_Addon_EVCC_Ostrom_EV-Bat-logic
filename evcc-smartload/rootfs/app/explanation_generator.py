"""
ExplanationGenerator: German-language slot explanations for Phase 6 Decision Transparency.

Produces short (hover tooltip) and long (click-detail) explanations for each
DispatchSlot in a PlanHorizon. All text is in German, consistent with the existing
dashboard language.

Design decisions:
- Cost delta is a *price-comparison approximation* (current slot vs. cheapest
  future slot), NOT LP dual variables. Clearly marked "ca." as per user convention.
- German decimal convention for user-facing ct values: comma separator
  (e.g. "8,2 ct") but JSON fields use float (dot separator).
- No external dependencies — stdlib only.
"""

from typing import Optional

from state import DispatchSlot, PlanHorizon


class ExplanationGenerator:
    """Generates German short/long explanations for LP plan slots.

    Usage:
        gen = ExplanationGenerator()
        explanation = gen.explain(slot, plan, departure_hours=4.0)
        # {"short": "...", "long": "..."}
    """

    def explain(
        self,
        slot: DispatchSlot,
        plan: PlanHorizon,
        departure_hours: Optional[float] = None,
    ) -> dict:
        """Generate a short and long German explanation for a single slot.

        Args:
            slot: The DispatchSlot to explain.
            plan: The full PlanHorizon (used for price ranking and context).
            departure_hours: Optional hours until EV departure (from config).
                             Used for EV charge and bat_charge explanations.

        Returns:
            dict with keys "short" and "long".
        """
        stats = self._price_stats(slot, plan)
        price_ct = stats["price_ct"]
        rank = stats["rank"]
        n_slots = stats["n_slots"]
        percentile = stats["percentile"]
        delta_eur = stats["delta_eur"]
        pv_next_3h_kwh = stats["pv_next_3h_kwh"]
        bat_soc_pct = round(slot.bat_soc_pct, 1)

        # German decimal format for display (comma as decimal separator)
        price_ct_de = self._de_float(price_ct, 1)
        bat_soc_de = self._de_float(bat_soc_pct, 1)

        if slot.bat_charge_kw > 0.1:
            return self._explain_bat_charge(
                price_ct, price_ct_de, rank, n_slots, percentile,
                delta_eur, pv_next_3h_kwh, bat_soc_de, departure_hours,
            )
        elif slot.bat_discharge_kw > 0.1:
            return self._explain_bat_discharge(
                price_ct, price_ct_de, rank, n_slots, percentile, bat_soc_de,
            )
        elif slot.ev_charge_kw > 0.1:
            ev_name = slot.ev_name or "EV"
            return self._explain_ev_charge(
                ev_name, price_ct, price_ct_de, rank, n_slots, percentile,
                delta_eur, departure_hours,
            )
        else:
            return self._explain_hold(price_ct, price_ct_de, rank, n_slots)

    # ------------------------------------------------------------------
    # Per-action type explanation builders
    # ------------------------------------------------------------------

    def _explain_bat_charge(
        self, price_ct, price_ct_de, rank, n_slots, percentile,
        delta_eur, pv_next_3h_kwh, bat_soc_de, departure_hours,
    ) -> dict:
        short = f"Laden: {price_ct_de} ct (Rang {rank}/{n_slots}), Puffer {bat_soc_de}%"
        if departure_hours is not None:
            dep_h_de = self._de_float(round(departure_hours, 1), 1)
            short += f", Abfahrt in {dep_h_de}h"
        if delta_eur > 0.005:
            short += f", Warten ca. +{self._de_float(delta_eur, 2)} EUR"

        long = (
            f"Batterie wird jetzt geladen, weil der Preis mit {price_ct_de} ct "
            f"im unteren {percentile}% des Forecasts liegt."
        )
        if delta_eur > 0.005:
            long += (
                f" Warten auf einen g\u00fcnstigeren Slot w\u00fcrde "
                f"ca. {self._de_float(delta_eur, 2)} EUR mehr kosten."
            )
        if pv_next_3h_kwh >= 0.1:
            long += (
                f" In den n\u00e4chsten 3h werden ca. "
                f"{self._de_float(pv_next_3h_kwh, 1)} kWh PV erwartet."
            )
        return {"short": short, "long": long}

    def _explain_bat_discharge(
        self, price_ct, price_ct_de, rank, n_slots, percentile, bat_soc_de,
    ) -> dict:
        upper_pct = 100 - percentile
        short = (
            f"Entladen: {price_ct_de} ct (Rang {rank}/{n_slots}), "
            f"Puffer {bat_soc_de}%"
        )
        long = (
            f"Batterie wird entladen, weil der Preis mit {price_ct_de} ct "
            f"im oberen {upper_pct}% liegt und Puffer bei {bat_soc_de}% "
            f"ausreichend ist."
        )
        return {"short": short, "long": long}

    def _explain_ev_charge(
        self, ev_name, price_ct, price_ct_de, rank, n_slots, percentile,
        delta_eur, departure_hours,
    ) -> dict:
        short = f"EV laden: {price_ct_de} ct (Rang {rank}/{n_slots})"
        if departure_hours is not None:
            dep_h_de = self._de_float(round(departure_hours, 1), 1)
            short += f", Abfahrt in {dep_h_de}h"
        if delta_eur > 0.005:
            short += f", Warten ca. +{self._de_float(delta_eur, 2)} EUR"

        departure_info = ""
        if departure_hours is not None:
            dep_h_de = self._de_float(round(departure_hours, 1), 1)
            departure_info = f" und die Abfahrt in {dep_h_de}h ist"

        long = (
            f"{ev_name} wird jetzt geladen, weil der Preis mit {price_ct_de} ct "
            f"im unteren {percentile}% des Forecasts liegt{departure_info}."
        )
        if delta_eur > 0.005:
            long += (
                f" Warten w\u00fcrde ca. {self._de_float(delta_eur, 2)} EUR mehr kosten."
            )
        return {"short": short, "long": long}

    def _explain_hold(self, price_ct, price_ct_de, rank, n_slots) -> dict:
        short = f"Halten: {price_ct_de} ct (Rang {rank}/{n_slots})"
        long = (
            f"Kein Handlungsbedarf \u2014 Preis bei {price_ct_de} ct liegt nicht "
            f"im optimalen Bereich zum Laden oder Entladen."
        )
        return {"short": short, "long": long}

    # ------------------------------------------------------------------
    # Helper: price statistics for a slot
    # ------------------------------------------------------------------

    def _price_stats(self, slot: DispatchSlot, plan: PlanHorizon) -> dict:
        """Compute price context metrics for a slot.

        Returns:
            dict with keys:
                price_ct: float — slot price in ct/kWh (dot separator, for JSON)
                rank: int — 1-based rank in ascending price list
                n_slots: int — total slots in plan
                percentile: int — approximate percentile (1-100, rounded)
                delta_eur: float — estimated extra cost of waiting (>=0); "ca." approximation
                pv_next_3h_kwh: float — expected PV energy in next 3h (kWh)
        """
        all_prices = [s.price_eur_kwh for s in plan.slots]
        n_slots = len(all_prices)

        price_ct = round(slot.price_eur_kwh * 100, 1)

        # 1-based rank (ascending: rank 1 = cheapest)
        sorted_prices = sorted(all_prices)
        # Use bisect-style: count prices strictly less than current
        rank = sum(1 for p in sorted_prices if p < slot.price_eur_kwh) + 1
        rank = max(1, min(rank, n_slots))

        percentile = round(rank / n_slots * 100) if n_slots > 0 else 50
        percentile = max(1, min(percentile, 100))

        # Cost delta: current price vs minimum future price (remaining slots)
        idx = slot.slot_index
        future_prices = [s.price_eur_kwh for s in plan.slots if s.slot_index > idx]

        # kWh in this 15-min slot for the active device
        if slot.bat_charge_kw > 0.1:
            kwh = slot.bat_charge_kw * 0.25
        elif slot.ev_charge_kw > 0.1:
            kwh = slot.ev_charge_kw * 0.25
        else:
            kwh = 0.0

        if future_prices and kwh > 0:
            min_future = min(future_prices)
            delta_eur = max(0.0, (slot.price_eur_kwh - min_future) * kwh)
        else:
            delta_eur = 0.0

        # PV expectation: next 12 slots (3h) starting after current slot
        pv_slots = [
            s.pv_kw for s in plan.slots
            if s.slot_index > idx and s.slot_index <= idx + 12
        ]
        pv_next_3h_kwh = round(sum(pv_slots) * 0.25, 1)

        return {
            "price_ct": price_ct,
            "rank": rank,
            "n_slots": n_slots,
            "percentile": percentile,
            "delta_eur": delta_eur,
            "pv_next_3h_kwh": pv_next_3h_kwh,
        }

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _de_float(value: float, decimals: int) -> str:
        """Format float with German decimal comma (e.g. 8.2 -> '8,2')."""
        fmt = f"{{:.{decimals}f}}"
        return fmt.format(value).replace(".", ",")
