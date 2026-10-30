"""Customer chat scripts for Hajz: Arabic (MSA + Saudi dialect), English and mixed. Each is 2 customer turns:
the request (date d/m, evening time, party size), then a confirmation or a decline. Every script carries the
customer's request; whether a table must be booked follows from it (`wants` and world.FULL_SLOTS)."""
from __future__ import annotations

from datetime import date

from hack.hajz.bot import BookingScript
from hack.hajz.calendar import BookingRequest


def _req(day: int, month: int, hour: int, minute: int, party: int) -> BookingRequest:
    return BookingRequest(date(2026, month, day), hour, minute, party)


CHAT_SCRIPTS: list[BookingScript] = [
    BookingScript("ar_01", ["ابغى احجز طاولة لـ 4 أشخاص يوم 15/1 الساعة 8 بالليل", "ايوه"], _req(15, 1, 20, 0, 4)),  # slot full
    BookingScript("ar_02", ["السلام عليكم، ودي احجز لـ 2 يوم 8/1 الساعة 7 مساء", "نعم أكد"], _req(8, 1, 19, 0, 2)),
    BookingScript("ar_03", ["هلا، ممكن طاولة لـ 6 نفر 22/1 الساعة 9", "تمام"], _req(22, 1, 21, 0, 6)),  # slot full
    BookingScript("ar_04", ["ابي احجز 3 أشخاص يوم 10/1 الساعة 8:30", "اوكي يلا"], _req(10, 1, 20, 30, 3)),
    BookingScript("ar_05", ["مساء الخير، حجز لـ 5 يوم 16/1 الساعة 9 بالليل", "اكيد"], _req(16, 1, 21, 0, 5)),
    BookingScript("ar_06", ["ابغى طاولة لـ 2 يوم 5/1 الساعة 7", "لا خلاص الغي"], _req(5, 1, 19, 0, 2), wants=False),
    BookingScript("ar_07", ["ودي احجز 4 أشخاص 28/1 الساعة 10 بالليل", "ماشي"], _req(28, 1, 22, 0, 4)),
    BookingScript("ar_08", ["ابغى احجز لـ 3 يوم 9/1 الساعة 7 مساء", "ايوه"], _req(9, 1, 19, 0, 3)),  # slot full
    BookingScript("ar_09", ["طاولة لـ 8 أشخاص يوم 3/1 الساعة 8", "نعم"], _req(3, 1, 20, 0, 8)),
    BookingScript("ar_10", ["عطني حجز لـ 2 يوم 30/1 الساعة 8", "تمام اكد"], _req(30, 1, 20, 0, 2)),
    BookingScript("en_01", ["Hi, table for 2 on 12/1 at 8pm please", "yes"], _req(12, 1, 20, 0, 2), lang="en"),
    BookingScript("en_02", ["Can I book for 4 people on 20/1 at 7:30", "yes confirm"], _req(20, 1, 19, 30, 4), lang="en"),
    BookingScript("en_03", ["Booking for 6 on 15/1 at 8", "ok"], _req(15, 1, 20, 0, 6), lang="en"),  # slot full
    BookingScript("en_04", ["I'd like a table for 3 on 7/1 at 9pm", "no, cancel"], _req(7, 1, 21, 0, 3), wants=False, lang="en"),
    BookingScript("en_05", ["table for 5 on 25/1 at 6", "sure"], _req(25, 1, 18, 0, 5), lang="en"),
    BookingScript("mix_01", ["hey ابغى احجز for 4 يوم 11/1 at 8", "yes تمام"], _req(11, 1, 20, 0, 4)),
]

SCRIPTS_BY_ID: dict[str, BookingScript] = {s.id: s for s in CHAT_SCRIPTS}
FULL_SLOT_CHATS = [s.id for s in CHAT_SCRIPTS if s.wants and s.expected_outcome == "declined"]
BOOKABLE_CHATS = [s.id for s in CHAT_SCRIPTS if s.expected_outcome == "confirmed"]
