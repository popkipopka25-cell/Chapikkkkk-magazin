"""PDF-чек заказа (Этап 7). Шрифт DejaVu лежит в app/fonts — кириллица работает без системных шрифтов."""
from pathlib import Path

from fpdf import FPDF

from app.models import ORDER_STATUS_RU, Order, Payment

FONTS = Path(__file__).parent / "fonts"
PURPLE = (123, 47, 247)


def can_have_receipt(o: Order) -> bool:
    """Чек есть только у заказа, по которому Telegram подтвердил оплату."""
    return o.payment_status.value in ("paid", "refunded")


def build_receipt(o: Order, payment: Payment | None, shop_name: str = "ChapaShop") -> bytes:
    pdf = FPDF(format=(148, 210))  # A5
    pdf.set_auto_page_break(True, 12)
    pdf.add_font("DV", "", str(FONTS / "DejaVuSans.ttf"))
    pdf.add_font("DV", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
    pdf.set_title(f"Чек {o.number}")
    pdf.add_page()
    w = pdf.epw

    pdf.set_font("DV", "B", 20)
    pdf.set_text_color(*PURPLE)
    pdf.cell(w, 10, shop_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 40)
    pdf.set_font("DV", "B", 13)
    pdf.cell(w, 8, f"Чек по заказу №{o.number}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("DV", "", 9)
    rows = [
        ("Дата заказа", o.created_at.strftime("%d.%m.%Y %H:%M UTC")),
        ("Дата оплаты", payment.created_at.strftime("%d.%m.%Y %H:%M UTC") if payment else "—"),
        ("Telegram ID", str(o.telegram_id)),
        ("Roblox", o.roblox_username),
        ("Статус", ORDER_STATUS_RU[o.status.value]),
        ("Способ оплаты", "Telegram Stars (XTR)"),
    ]
    for k, v in rows:
        pdf.set_text_color(120, 120, 140)
        pdf.cell(w * 0.38, 6, k)
        pdf.set_text_color(30, 30, 40)
        pdf.cell(w * 0.62, 6, v, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("DV", "B", 9)
    pdf.set_fill_color(243, 236, 254)
    cols = (w * 0.52, w * 0.16, w * 0.12, w * 0.20)
    for t, cw, al in zip(("Товар", "Цена", "Кол.", "Сумма"), cols, "LRRR"):
        pdf.cell(cw, 7, t, fill=True, align=al)
    pdf.ln()
    pdf.set_font("DV", "", 9)
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
        pdf.set_font("DV", "", 9)
        pdf.cell(w * 0.6, 6.5, f"Скидка (промокод {o.promo_code or ''})")
        pdf.cell(w * 0.4, 6.5, f"-{o.discount_stars} XTR", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DV", "B", 12)
    pdf.cell(w * 0.6, 8, "Итого")
    pdf.cell(w * 0.4, 8, f"{o.total_stars} XTR", align="R", new_x="LMARGIN", new_y="NEXT")

    if o.payment_status.value == "refunded":
        pdf.set_text_color(220, 38, 38)
        pdf.set_font("DV", "B", 10)
        pdf.cell(w, 7, "Оплата возвращена покупателю", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 40)

    if payment:
        pdf.ln(2)
        pdf.set_font("DV", "", 7)
        pdf.set_text_color(120, 120, 140)
        pdf.multi_cell(w, 4, f"ID платежа Telegram: {payment.telegram_payment_charge_id}")
    pdf.ln(4)
    pdf.set_font("DV", "", 7)
    pdf.set_text_color(120, 120, 140)
    pdf.multi_cell(w, 4, "Документ сформирован автоматически и подтверждает получение оплаты "
                         "в Telegram Stars. Не является фискальным чеком.")
    return bytes(pdf.output())
