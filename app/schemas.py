import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(Base):
    name: str = Field(..., min_length=1, description="Nome do produto")
    brand: str = Field(..., min_length=1, description="Marca do produto")
    # Opcional: loja onde o produto foi visto. Um produto se liga a uma loja por um
    # preço, então `store_id` e `price` vêm juntos e criam o primeiro preço.
    store_id: int | None = Field(default=None, description="ID da loja onde o produto foi visto")
    price: int | None = Field(
        default=None, gt=0, description="Preço nessa loja, em centavos (ex.: R$ 20,50 = 2050)"
    )
    date: dt.date = Field(
        default_factory=dt.date.today, description="Data desse preço (padrão: hoje)"
    )

    @model_validator(mode="after")
    def store_and_price_go_together(self):
        if (self.store_id is None) != (self.price is None):
            raise ValueError("store_id and price must be sent together")
        return self


class StoreCreate(Base):
    name: str = Field(..., min_length=1, description="Nome da loja")
    location: str = Field(..., min_length=1, description="Localização da loja")


class PriceCreate(Base):
    product_id: int = Field(..., description="ID do produto")
    store_id: int = Field(..., description="ID da loja")
    price: int = Field(..., gt=0, description="Preço em centavos (ex.: R$ 20,50 = 2050)")
    date: dt.date = Field(
        default_factory=dt.date.today, description="Data do preço (padrão: hoje)"
    )
