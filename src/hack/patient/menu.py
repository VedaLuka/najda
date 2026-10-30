"""The restaurant menu. Prices are in SAR. Aliases are what customers actually type."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MenuItem:
    sku: str
    name_en: str
    name_ar: str
    price_sar: float
    aliases: tuple[str, ...]


MENU: dict[str, MenuItem] = {m.sku: m for m in [
    MenuItem("shawarma_chicken", "Chicken Shawarma", "شاورما دجاج", 12.0,
             ("shawarma dajaj", "chicken shawarma", "شاورما دجاج", "شاورما")),
    MenuItem("shawarma_meat", "Meat Shawarma", "شاورما لحم", 14.0,
             ("meat shawarma", "shawarma laham", "شاورما لحم")),
    MenuItem("kabsa", "Chicken Kabsa", "كبسة دجاج", 28.0, ("kabsa", "كبسة", "كبسه")),
    MenuItem("falafel", "Falafel Sandwich", "ساندويتش فلافل", 6.0, ("falafel", "فلافل")),
    MenuItem("fries", "Fries", "بطاطس", 8.0, ("fries", "بطاطس", "بطاطا", "chips")),
    MenuItem("pepsi", "Pepsi", "بيبسي", 4.0, ("pepsi", "بيبسي", "ببسي")),
    MenuItem("water", "Water", "ماء", 2.0, ("water", "ماء", "مويه", "موية")),
    MenuItem("karak", "Karak Tea", "شاي كرك", 5.0, ("karak", "كرك", "شاي كرك")),
]}


def price_of(items: dict[str, int]) -> float:
    """Total in SAR for {sku: qty}. Used by invariants, never by the bot."""
    return round(sum(MENU[sku].price_sar * qty for sku, qty in items.items()), 2)


def find_sku(text: str) -> str | None:
    """Longest alias that appears in the (lowercased) text wins."""
    best: tuple[int, str] | None = None
    for item in MENU.values():
        for alias in item.aliases:
            if alias in text and (best is None or len(alias) > best[0]):
                best = (len(alias), item.sku)
    return best[1] if best else None
