"""Three fake services with ledgers. The chaos layer wraps every method call (see chaos.py)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hack.patient.clock import VirtualClock
from hack.patient.menu import MENU

VALID_TOKENS = {"tok_v1"}


class ServiceError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status} {message}")
        self.status = status
        self.message = message


@dataclass
class Order:
    order_id: str
    items: dict[str, int]
    total_sar: float
    status: str = "created"  # created | queued | confirmed | cancelled


@dataclass
class Payment:
    payment_id: str
    order_id: str
    amount_sar: float
    status: str = "paid"  # paid | failed


@dataclass
class StockAPI:
    clock: VirtualClock
    stock: dict[str, int] = field(default_factory=lambda: {sku: 50 for sku in MENU})
    latency_s: float = 0.08

    def check_stock(self, sku: str, fresh: bool = False) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        if sku not in MENU:
            raise ServiceError(404, f"unknown sku {sku}")
        return {"sku": sku, "qty_available": self.stock[sku], "price": MENU[sku].price_sar,
                "cached": not fresh}

    def reserve(self, items: dict[str, int]) -> None:
        for sku, qty in items.items():
            self.stock[sku] -= qty


@dataclass
class OrderAPI:
    clock: VirtualClock
    stock_api: StockAPI
    tokens: set[str] = field(default_factory=lambda: set(VALID_TOKENS))
    orders: dict[str, Order] = field(default_factory=dict)
    latency_s: float = 0.15

    def create_order(self, items: dict[str, int], total_sar: float, token: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        if token not in self.tokens:
            raise ServiceError(401, "token expired")
        order = Order(f"ORD-{len(self.orders) + 1:04d}", dict(items), float(total_sar))
        self.orders[order.order_id] = order
        self.stock_api.reserve(items)
        return {"order_id": order.order_id, "status": order.status, "total_sar": order.total_sar}

    def get_order(self, order_id: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s / 2)
        order = self._get(order_id)
        return {"order_id": order.order_id, "status": order.status, "total_sar": order.total_sar}

    def confirm_order(self, order_id: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s / 2)
        order = self._get(order_id)
        order.status = "confirmed"
        return {"order_id": order.order_id, "status": order.status}

    def _get(self, order_id: str) -> Order:
        if order_id not in self.orders:
            raise ServiceError(404, f"unknown order {order_id}")
        return self.orders[order_id]


@dataclass
class PaymentAPI:
    clock: VirtualClock
    tokens: set[str] = field(default_factory=lambda: set(VALID_TOKENS))
    payments: dict[str, Payment] = field(default_factory=dict)
    webhooks: dict[str, str] = field(default_factory=dict)  # order_id -> status the webhook delivered
    latency_s: float = 0.3

    def charge(self, order_id: str, amount_sar: float, token: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        if token not in self.tokens:
            raise ServiceError(401, "token expired")
        pay = Payment(f"PAY-{len(self.payments) + 1:04d}", order_id, float(amount_sar))
        self.payments[pay.payment_id] = pay
        self.webhooks[order_id] = pay.status
        return {"payment_id": pay.payment_id, "order_id": order_id, "status": pay.status,
                "amount_sar": pay.amount_sar}

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s / 3)
        if payment_id not in self.payments:
            raise ServiceError(404, f"unknown payment {payment_id}")
        pay = self.payments[payment_id]
        return {"payment_id": pay.payment_id, "order_id": pay.order_id, "status": pay.status,
                "amount_sar": pay.amount_sar}

    def webhook_status(self, order_id: str) -> dict[str, Any]:
        self.clock.sleep(0.01)
        return {"order_id": order_id, "status": self.webhooks.get(order_id, "pending")}
