from pydantic import BaseModel, ConfigDict, Field


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    icon: str | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    image_url: str | None
    category_id: int | None
    price_stars: int
    old_price_stars: int | None = None
    discount_percent: int = 0
    is_available: bool = Field(validation_alias="available_now")   # с учётом остатка на складе
    stock: int | None = None                                       # None — без ограничения
    is_demo: bool


class CartLineIn(BaseModel):
    product_id: int
    quantity: int


class CartQuoteIn(BaseModel):
    items: list[CartLineIn]
    promo_code: str | None = None


class CartLineOut(BaseModel):
    product_id: int
    name: str
    price_stars: int
    quantity: int
    subtotal: int
    available: bool
    old_price_stars: int | None = None
    category_id: int | None = None
    image_url: str | None = None
    stock: int | None = None


class CartQuoteOut(BaseModel):
    items: list[CartLineOut]
    total_stars: int          # итог после скидки
    count: int
    removed: list[int]
    subtotal_stars: int = 0
    discount_stars: int = 0
    promo_code: str | None = None
    promo_title: str | None = None
    promo_error: str | None = None
