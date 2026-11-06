"""Остатки товаров. stock = None — без ограничения; число — сколько штук осталось."""
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Order, Product


def take(db: Session, product: Product, qty: int) -> bool:
    """Атомарно забирает qty штук. Два одновременных заказа не смогут забрать больше, чем есть."""
    if product.stock is None:
        return True
    res = db.execute(update(Product).where(Product.id == product.id, Product.stock >= qty)
                     .values(stock=Product.stock - qty))
    return res.rowcount == 1


def give_back(db: Session, order: Order) -> None:
    """Возвращает на склад товары отклонённого/возвращённого заказа (только там, где остаток ограничен)."""
    for i in order.items:
        if i.product_id:
            db.execute(update(Product).where(Product.id == i.product_id, Product.stock.is_not(None))
                       .values(stock=Product.stock + i.quantity))
