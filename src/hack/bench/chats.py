"""Customer chat scripts: Arabic (MSA + Saudi dialect) and English. Each is 2 customer turns:
the order, then the confirmation (or a decline). expected_items is what a correct bot must order."""
from __future__ import annotations

from hack.patient.bot import ChatScript

CHAT_SCRIPTS: list[ChatScript] = [
    ChatScript("ar_01", ["ابغى 2 شاورما دجاج و 1 بيبسي", "ايوه"], {"shawarma_chicken": 2, "pepsi": 1}),
    ChatScript("ar_02", ["السلام عليكم، ممكن 1 كبسة دجاج و 2 ماء", "نعم أكد"], {"kabsa": 1, "water": 2}),
    ChatScript("ar_03", ["ابي 3 فلافل و 1 كرك لو سمحت", "تمام"], {"falafel": 3, "karak": 1}),
    ChatScript("ar_04", ["هلا، عطني 2 شاورما لحم مع 2 بطاطس", "اوكي يلا"], {"shawarma_meat": 2, "fries": 2}),
    ChatScript("ar_05", ["مساء الخير ابغى 1 كبسة", "اكيد"], {"kabsa": 1}),
    ChatScript("ar_06", ["ممكن 4 شاورما دجاج", "ايوه اكد"], {"shawarma_chicken": 4}),
    ChatScript("ar_07", ["ودي بـ 2 كرك و 1 فلافل", "ماشي"], {"karak": 2, "falafel": 1}),
    ChatScript("ar_08", ["ابغى 1 شاورما لحم و 1 بيبسي و 1 بطاطس", "نعم"], {"shawarma_meat": 1, "pepsi": 1, "fries": 1}),
    ChatScript("ar_09", ["اثنين كبسة و ثلاث مويه", "ايوه"], {"kabsa": 2, "water": 3}),
    ChatScript("ar_10", ["ابغى 2 شاورما دجاج", "لا خلاص الغي"], None),
    ChatScript("ar_11", ["عطني 5 ببسي و 2 بطاطا", "تمام اكد"], {"pepsi": 5, "fries": 2}),
    ChatScript("ar_12", ["ابي 1 كرك بس", "لا ما ابغى"], None),
    ChatScript("en_01", ["Hi, can I get 2 chicken shawarma and 1 pepsi", "yes"], {"shawarma_chicken": 2, "pepsi": 1}, "en"),
    ChatScript("en_02", ["1 kabsa and 2 water please", "yes confirm"], {"kabsa": 1, "water": 2}, "en"),
    ChatScript("en_03", ["I'd like 3 falafel and 1 karak", "ok"], {"falafel": 3, "karak": 1}, "en"),
    ChatScript("en_04", ["two meat shawarma with fries", "sure"], {"shawarma_meat": 2, "fries": 1}, "en"),
    ChatScript("en_05", ["Can I order 2 kabsa", "yes please"], {"kabsa": 2}, "en"),
    ChatScript("en_06", ["4 chicken shawarma, 4 pepsi", "confirm"], {"shawarma_chicken": 4, "pepsi": 4}, "en"),
    ChatScript("en_07", ["one karak and one water", "okay"], {"karak": 1, "water": 1}, "en"),
    ChatScript("en_08", ["3 fries please", "no, cancel"], None, "en"),
    ChatScript("mix_01", ["hey ابغى 2 shawarma dajaj و 1 pepsi", "yes تمام"], {"shawarma_chicken": 2, "pepsi": 1}),
    ChatScript("mix_02", ["ممكن 1 kabsa and 2 كرك", "ايوه"], {"kabsa": 1, "karak": 2}),
]

SCRIPTS_BY_ID: dict[str, ChatScript] = {s.id: s for s in CHAT_SCRIPTS}
