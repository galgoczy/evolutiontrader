"""Funding-elszámolás (spec 4.): esedékességkor a pozíció mark áras névértékére, a rögzített rátával.

Pozitív rátánál a long fizet, a short kap. Az esemény a gyertyához tartozik, amelyiknek a zárása
az esemény ideje (`data.store.funding_by_bar`), és az akkor tartott pozícióra számolódik.
"""

from __future__ import annotations


def payment(qty: float, mark_price: float, rate: float) -> float:
    """A számla pénzmozgása (előjeles): long + pozitív ráta -> negatív."""
    return -qty * mark_price * rate
