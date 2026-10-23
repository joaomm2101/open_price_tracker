import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(Base):
    name: str = Field(..., min_length=1, description="Nome do produto")
    brand: str = Field(..., min_length=1, description="Marca do produto")


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
