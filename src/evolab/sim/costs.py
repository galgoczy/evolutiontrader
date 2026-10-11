"""Költségmodell (spec 4., `config/lab.yaml` `costs`): taker díj + slippage, mind teljesülésenként.

A slippage a teljesülési árat rontja (vételnél feljebb, eladásnál lejjebb):
    slip = slippage_base + slippage_atr_mult * ATR / ár
A `cost_mult` a díjat és a slippage-et együtt szorozza (költségérzékenység: 1x, 2x, 3x).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Costs:
    taker_fee: float
    slippage_base: float
    slippage_atr_mult: float
    cost_mult: float = 1.0

    @classmethod
    def from_config(cls, costs: dict, cost_mult: float = 1.0) -> "Costs":
        return cls(float(costs["taker_fee"]), float(costs["slippage_base"]),
                   float(costs["slippage_atr_mult"]), float(cost_mult))

    def slip_frac(self, price: float, atr: float) -> float:
        atr_part = self.slippage_atr_mult * atr / price if atr == atr and price > 0 else 0.0  # NaN-védelem
        return self.cost_mult * (self.slippage_base + atr_part)

    def fill_price(self, price: float, side: int, atr: float) -> float:
        """`side`: +1 vétel, -1 eladás."""
        return price * (1.0 + side * self.slip_frac(price, atr))

    def fee(self, notional: float) -> float:
        return self.cost_mult * self.taker_fee * abs(notional)
