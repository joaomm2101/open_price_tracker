import datetime as dt

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Product(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("name", "brand"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str
    brand: str


class Store(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("name", "location"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str
    location: str


class Price(SQLModel, table=True):
    """Preço de um produto em uma loja, em centavos."""

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    store_id: int = Field(foreign_key="store.id", index=True)
    price: int
    date: dt.date = Field(index=True)
