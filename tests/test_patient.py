"""The patient bot on its own: healthy behaviour, control panel, parsing, traces."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.chats import CHAT_SCRIPTS  # noqa: E402
from hack.patient.bot import OrderBot  # noqa: E402
from hack.patient.brains import ScriptedBrain, is_yes, parse_order  # noqa: E402
from hack.patient.config import BotConfig, ControlPanel  # noqa: E402
from hack.patient.invariants import check_invariants, order_completed  # noqa: E402
from hack.patient.numerals import normalize_digits, parse_quantity  # noqa: E402
from hack.patient.tracing import HARD_MAX_TURNS, Span, metrics_from_spans  # noqa: E402
from hack.patient.world import World  # noqa: E402


def run_all(world: World):
    bot = OrderBot(world, ScriptedBrain())
    return [bot.run_chat(s) for s in CHAT_SCRIPTS]


def test_healthy_bot_passes_every_invariant_and_every_chat():
    world = World.build(seed=0)
    results = run_all(world)
    assert check_invariants(world, results) == []
    assert all(order_completed(world, r) for r in results), [r.chat_id for r in results if not order_completed(world, r)]
    assert max(r.turns for r in results) <= HARD_MAX_TURNS


def test_declines_create_no_confirmed_order():
    world = World.build(seed=0)
    results = {r.chat_id: r for r in run_all(world)}
    assert results["ar_10"].outcome == "declined" and results["en_08"].outcome == "declined"
    assert all(o.status != "confirmed" for o in world.order_api.orders.values()
               if o.order_id in (results["ar_10"].order_id, results["en_08"].order_id))


def test_parse_order_quantities_and_aliases():
    assert parse_order("ابغى 2 شاورما دجاج و 1 بيبسي", False) == {"shawarma_chicken": 2, "pepsi": 1}
    assert parse_order("two meat shawarma with fries", False) == {"shawarma_meat": 2, "fries": 1}
    assert parse_order("اثنين كبسة و ثلاث مويه", False) == {"kabsa": 2, "water": 3}
    assert parse_order("hello there", False) == {}


def test_arabic_indic_digits_need_normalisation():
    assert parse_quantity("٢") is None
    assert parse_quantity(normalize_digits("٢")) == 2
    assert parse_order("ابغى ٢ شاورما دجاج", False) == {"shawarma_chicken": 1}
    assert parse_order("ابغى ٢ شاورما دجاج", True) == {"shawarma_chicken": 2}


def test_yes_no_words_in_dialect():
    assert is_yes("اوكي يلا") and is_yes("yes please") and is_yes("ايوه اكد")
    assert not is_yes("لا خلاص الغي") and not is_yes("no, cancel")


def test_control_panel_history_and_rollback():
    panel = ControlPanel(BotConfig())
    v2 = panel.apply({"retry.max_retries": 3, "field_mappings.order_id": "id"}, "fix", "najda")
    assert v2 == 2 and panel.current.retry.max_retries == 3 and panel.current.field_mappings["order_id"] == "id"
    v3 = panel.rollback(1)
    assert v3 == 3 and panel.current == BotConfig()
    restored = ControlPanel.from_snapshot(panel.snapshot())
    assert restored.current == panel.current and len(restored.history) == 3


def test_traces_have_schema_and_metrics_add_up():
    world = World.build(seed=0)
    results = run_all(world)
    keys = set(Span.__dataclass_fields__)
    spans = [vars(s) for s in world.tracer.spans]
    assert spans and all(set(s) == keys for s in spans)
    m = metrics_from_spans(spans, {r.chat_id: r.outcome for r in results})
    assert m["chats"] == len(CHAT_SCRIPTS) and m["error_rate"] == 0.0
    assert m["orders_confirmed"] == sum(r.outcome == "confirmed" for r in results)
    assert m["per_chat"]["ar_01"]["turns"] == results[0].turns


def test_llm_action_parser_tolerates_bad_json():
    from hack.patient.brains import ChatState, Reply, Tool, _parse_action

    st = ChatState("c")
    assert _parse_action('{"tool": "check_stock", "args": "sku=pepsi"}', st) == Tool("check_stock", {})
    assert _parse_action('text before {"reply": "hi", "outcome": "pending"} after', st) == Reply("hi", "pending")
    assert _parse_action("not json at all", st).outcome == "failed"
    assert _parse_action("[1, 2]", st).outcome == "failed"


def test_router_tolerates_stringified_items_and_service_bugs():
    from hack.patient.bot import ToolRouter
    from hack.patient.brains import Tool

    world = World.build(seed=0)
    router = ToolRouter(world)
    ok = router.execute("c", Tool("create_order", {"items": '{"pepsi": 2}', "total_sar": "8"}))
    assert ok["ok"] and ok["result"]["order_id"] == "ORD-0001"
    bad = router.execute("c", Tool("create_order", {"items": 42, "total_sar": 8}))
    assert not bad["ok"] and bad["status"] == 400

    def boom(**_):
        raise RuntimeError("db connection lost")
    world.order_api.get_order = boom
    crash = router.execute("c", Tool("get_order", {"order_id": "ORD-0001"}))
    assert not crash["ok"] and crash["status"] == 500 and "db connection lost" in crash["error"]
