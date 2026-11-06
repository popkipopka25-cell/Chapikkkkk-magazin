"""PDF-чек заказа (Этап 7). Шрифт DejaVu лежит в app/fonts — кириллица работает без системных шрифтов."""
import logging
from pathlib import Path

from fpdf import FPDF

from app.models import ORDER_STATUS_RU, Order, Payment

FONTS = Path(__file__).parent / "fonts"
PURPLE = (123, 47, 247)
log = logging.getLogger("chapashop")

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґ", ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "i", "yi", "ye", "g"]))


def _plain(text) -> str:
    """Запасной вариант без шрифта DejaVu: кириллица -> латиница, чтобы чек всё равно открылся."""
    out = []
    for ch in str(text):
        low = ch.lower()
        t = _TR.get(low)
        out.append((t.capitalize() if ch != low else t) if t is not None else ch)
    return "".join(out).encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    plain = False

    def cell(self, w=None, h=None, text="", *a, **k):
        return super().cell(w, h, _plain(text) if self.plain else text, *a, **k)

    def multi_cell(self, w, h=None, text="", *a, **k):
        return super().multi_cell(w, h, _plain(text) if self.plain else text, *a, **k)


def can_have_receipt(o: Order) -> bool:
    """Чек есть только у заказа, по которому Telegram подтвердил оплату."""
    return o.payment_status.value in ("paid", "refunded")


def build_receipt(o: Order, payment: Payment | None, shop_name: str = "ChapaShop") -> bytes:
    pdf = _PDF(format=(148, 210))  # A5
    pdf.set_auto_page_break(True, 12)
    font = "DV"
    try:
        pdf.add_font("DV", "", str(FONTS / "DejaVuSans.ttf"))
        pdf.add_font("DV", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
    except Exception as e:      # файлов шрифта нет в репозитории — чек всё равно делаем, но латиницей
        log.error("Шрифт чека не загрузился (%s) — проверьте папку app/fonts", type(e).__name__)
        font, pdf.plain = "Helvetica", True
    pdf.set_title(f"Receipt {o.number}" if pdf.plain else f"Чек {o.number}")
    pdf.add_page()
    w = pdf.epw

    pdf.set_font(font, "B", 20)
    pdf.set_text_color(*PURPLE)
    pdf.cell(w, 10, shop_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 40)
    pdf.set_font(font, "B", 13)
    pdf.cell(w, 8, f"Чек по заказу №{o.number}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font(font, "", 9)
    rows = [
        ("Дата заказа", o.created_at.strftime("%d.%m.%Y %H:%M UTC")),
        ("Дата оплаты", payment.created_at.strftime("%d.%m.%Y %H:%M UTC") if payment else "—"),
        ("Telegram ID", str(o.telegram_id)),
        ("Roblox", o.roblox_username),
        ("Статус", ORDER_STATUS_RU[o.status.value]),
        ("Способ оплаты", "Бесплатный заказ" if not o.total_stars else "Telegram Stars (XTR)"),
    ]
    for k, v in rows:
        pdf.set_text_color(120, 120, 140)
        pdf.cell(w * 0.38, 6, k)
        pdf.set_text_color(30, 30, 40)
        pdf.cell(w * 0.62, 6, v, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font(font, "B", 9)
    pdf.set_fill_color(243, 236, 254)
    cols = (w * 0.52, w * 0.16, w * 0.12, w * 0.20)
    for t, cw, al in zip(("Товар", "Цена", "Кол.", "Сумма"), cols, "LRRR"):
        pdf.cell(cw, 7, t, fill=True, align=al)
    pdf.ln()
    pdf.set_font(font, "", 9)
    for i in o.items:
        name = i.product_name if len(i.product_name) <= 40 else i.product_name[:39] + "…"
        pdf.cell(cols[0], 6.5, name)
        pdf.cell(cols[1], 6.5, f"{i.price_stars}", align="R")
        pdf.cell(cols[2], 6.5, f"{i.quantity}", align="R")
        pdf.cell(cols[3], 6.5, f"{i.price_stars * i.quantity} ⭐".replace("⭐", "XTR"), align="R",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*PURPLE)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.l_margin + w, pdf.get_y() + 1)
    pdf.ln(3)
    if o.discount_stars:
        pdf.set_font(font, "", 9)
        pdf.cell(w * 0.6, 6.5, f"Скидка (промокод {o.promo_code or ''})")
        pdf.cell(w * 0.4, 6.5, f"-{o.discount_stars} XTR", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "B", 12)
    pdf.cell(w * 0.6, 8, "Итого")
    pdf.cell(w * 0.4, 8, f"{o.total_stars} XTR", align="R", new_x="LMARGIN", new_y="NEXT")

    if o.payment_status.value == "refunded":
        pdf.set_text_color(220, 38, 38)
        pdf.set_font(font, "B", 10)
        pdf.cell(w, 7, "Оплата возвращена покупателю", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 40)

    if payment:
        pdf.ln(2)
        pdf.set_font(font, "", 7)
        pdf.set_text_color(120, 120, 140)
        pdf.multi_cell(w, 4, f"ID платежа Telegram: {payment.telegram_payment_charge_id}")
    pdf.ln(4)
    pdf.set_font(font, "", 7)
    pdf.set_text_color(120, 120, 140)
    pdf.multi_cell(w, 4, "Документ сформирован автоматически и подтверждает получение оплаты "
                         "в Telegram Stars. Не является фискальным чеком.")
    return bytes(pdf.output())
