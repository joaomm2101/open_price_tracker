import csv
import io
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, col, func, select

from app.database import create_db_and_tables, get_session
from app.logic import (
    DEFAULT_MAX_AGE_DAYS,
    calculate_average_price,
    calculate_highest_price,
    filter_recent_prices,
    get_cheapest_price,
    get_current_prices,
)
from app.importer import CsvFormatError, import_stream
from app.models import Price, Product, Store
from app.schemas import PriceCreate, ProductCreate, StoreCreate


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_REJECTED_SHOWN = 200

SessionDep = Annotated[Session, Depends(get_session)]

# Quantos dias para trás um preço ainda é considerado "atual".
MaxAgeDays = Annotated[
    int,
    Query(
        ge=1,
        le=365,
        description="Considera apenas preços dos últimos N dias",
    ),
]


def find_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def find_store(session: Session, store_id: int) -> Store:
    store = session.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


def product_prices(session: Session, product_id: int) -> list[dict]:
    find_product(session, product_id)
    rows = session.exec(select(Price).where(Price.product_id == product_id)).all()
    return [row.model_dump() for row in rows]


def store_prices(session: Session, store_id: int) -> list[dict]:
    find_store(session, store_id)
    rows = session.exec(select(Price).where(Price.store_id == store_id)).all()
    return [row.model_dump() for row in rows]


def current_product_prices(
    session: Session, product_id: int, max_age_days: int
) -> list[dict]:
    current = get_current_prices(product_prices(session, product_id), max_age_days)
    if not current:
        raise HTTPException(
            status_code=404,
            detail=f"No prices in the last {max_age_days} days",
        )
    return current


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def get_health():
    return {"status": "ok"}


@app.get("/products")
def get_products(session: SessionDep):
    return session.exec(select(Product)).all()


@app.post("/products", status_code=201)
def create_product(product: ProductCreate, session: SessionDep):
    """
    Cria um produto. Se `store_id` e `price` vierem, cria junto o primeiro preço
    dele nessa loja; tudo ou nada: se a loja não existir, nada é gravado.
    """
    existing = session.exec(
        select(Product).where(
            Product.name == product.name, Product.brand == product.brand
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product already exists")

    if product.store_id is not None:
        find_store(session, product.store_id)
        if product.date > date.today():
            raise HTTPException(status_code=400, detail="Price date cannot be in the future")

    new_product = Product(name=product.name, brand=product.brand)
    session.add(new_product)
    session.flush()  # gera o id do produto, sem confirmar ainda

    first_price = None
    if product.store_id is not None:
        first_price = Price(
            product_id=new_product.id,
            store_id=product.store_id,
            price=product.price,
            date=product.date,
        )
        session.add(first_price)

    session.commit()
    session.refresh(new_product)
    if first_price is None:
        return new_product
    session.refresh(first_price)
    return {**new_product.model_dump(), "initial_price": first_price}


@app.get("/products/{product_id}")
def get_product(product_id: int, session: SessionDep):
    return find_product(session, product_id)


@app.get("/products/{product_id}/prices")
def get_product_prices(
    product_id: int, session: SessionDep, max_age_days: MaxAgeDays = DEFAULT_MAX_AGE_DAYS
):
    prices = filter_recent_prices(product_prices(session, product_id), max_age_days)
    return {"product_id": product_id, "max_age_days": max_age_days, "prices": prices}


@app.get("/products/{product_id}/prices/history")
def get_price_history(
    product_id: int,
    session: SessionDep,
    start_date: Annotated[
        date | None, Query(description="Início do período (inclusivo), AAAA-MM-DD")
    ] = None,
    end_date: Annotated[
        date | None, Query(description="Fim do período (inclusivo), AAAA-MM-DD")
    ] = None,
):
    """
    Resumo dos preços de um produto em qualquer período, inclusive antigo.

    Diferente de `/cheapest`, aqui valem todos os registros do período (o menor
    preço já registrado), não só o último preço de cada loja. Sem `start_date`
    ou `end_date`, o período fica aberto naquela ponta.
    """
    find_product(session, product_id)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422, detail="start_date must not be after end_date"
        )

    conditions = [Price.product_id == product_id]
    if start_date:
        conditions.append(Price.date >= start_date)
    if end_date:
        conditions.append(Price.date <= end_date)

    # Menor preço do período; em caso de empate, o mais recente.
    cheapest = session.exec(
        select(Price)
        .where(*conditions)
        .order_by(col(Price.price), col(Price.date).desc(), col(Price.id).desc())
        .limit(1)
    ).first()
    if cheapest is None:
        raise HTTPException(
            status_code=404, detail="No prices found in the given period"
        )

    count, average, highest = session.exec(
        select(func.count(Price.id), func.avg(Price.price), func.max(Price.price)).where(
            *conditions
        )
    ).one()
    return {
        "product_id": product_id,
        "start_date": start_date,
        "end_date": end_date,
        "count": count,
        "cheapest": {
            "price": cheapest.price,
            "date": cheapest.date,
            "store": find_store(session, cheapest.store_id),
        },
        "average_price": round(average),
        "highest_price": highest,
    }


@app.get("/products/{product_id}/prices/average")
def get_average_price_endpoint(
    product_id: int, session: SessionDep, max_age_days: MaxAgeDays = DEFAULT_MAX_AGE_DAYS
):
    prices = current_product_prices(session, product_id, max_age_days)
    return {
        "product_id": product_id,
        "max_age_days": max_age_days,
        "average_price": calculate_average_price(prices),
    }


@app.get("/products/{product_id}/prices/highest")
def get_highest_price_endpoint(
    product_id: int, session: SessionDep, max_age_days: MaxAgeDays = DEFAULT_MAX_AGE_DAYS
):
    prices = current_product_prices(session, product_id, max_age_days)
    highest = max(prices, key=lambda p: p["price"])
    return {
        "product_id": product_id,
        "max_age_days": max_age_days,
        "highest_price": calculate_highest_price(prices),
        "store_id": highest["store_id"],
        "date": highest["date"],
    }


@app.get("/products/{product_id}/cheapest")
def get_cheapest_endpoint(
    product_id: int, session: SessionDep, max_age_days: MaxAgeDays = DEFAULT_MAX_AGE_DAYS
):
    prices = current_product_prices(session, product_id, max_age_days)
    cheapest = get_cheapest_price(prices)
    return {
        "product_id": product_id,
        "max_age_days": max_age_days,
        "price": cheapest["price"],
        "date": cheapest["date"],
        "store": find_store(session, cheapest["store_id"]),
    }


@app.get("/stores")
def get_stores(session: SessionDep):
    return session.exec(select(Store)).all()


@app.post("/stores", status_code=201)
def create_store(store: StoreCreate, session: SessionDep):
    existing = session.exec(
        select(Store).where(
            Store.name == store.name, Store.location == store.location
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Store already exists")

    new_store = Store(**store.model_dump())
    session.add(new_store)
    session.commit()
    session.refresh(new_store)
    return new_store


# Declarada antes de qualquer rota "/stores/{store_id}" para não ser capturada por ela.
@app.get("/stores/count")
def get_stores_count(session: SessionDep):
    return {"count": len(session.exec(select(Store.id)).all())}


@app.get("/stores/{store_id}/prices")
def get_prices_by_store_endpoint(
    store_id: int, session: SessionDep, max_age_days: MaxAgeDays = DEFAULT_MAX_AGE_DAYS
):
    prices = filter_recent_prices(store_prices(session, store_id), max_age_days)
    return {"store_id": store_id, "max_age_days": max_age_days, "prices": prices}


@app.post("/prices", status_code=201)
def create_price(price: PriceCreate, session: SessionDep):
    find_product(session, price.product_id)
    find_store(session, price.store_id)
    if price.date > date.today():
        raise HTTPException(status_code=400, detail="Price date cannot be in the future")

    new_price = Price(**price.model_dump())
    session.add(new_price)
    session.commit()
    session.refresh(new_price)
    return new_price


@app.post("/imports")
def import_prices(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="Arquivo CSV com os preços")],
    dry_run: Annotated[
        bool,
        Query(description="true só confere o arquivo, sem gravar; false importa de verdade"),
    ] = True,
    cents: Annotated[
        bool, Query(description="a coluna de preço já está em centavos inteiros")
    ] = False,
):
    """
    Confere ou importa um CSV de preços (veja `app/importer.py` para as colunas).

    Por padrão é uma simulação (`dry_run=true`): devolve o que seria criado,
    atualizado ou recusado, sem alterar o banco.
    """
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 20 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # exportações do Excel em pt-BR

    try:
        result = import_stream(
            io.StringIO(text, newline=""), session, cents=cents, dry_run=dry_run
        )
    except CsvFormatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except csv.Error as error:
        raise HTTPException(status_code=422, detail=f"Not a valid CSV file: {error}") from error

    return {
        "filename": file.filename,
        "dry_run": result.dry_run,
        "columns": result.columns,
        "read": result.read,
        "created": result.created,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "new_products": result.new_products,
        "new_stores": result.new_stores,
        "rejected_total": len(result.rejected),
        "rejected": [
            {"line": line, "reason": reason, "row": row}
            for line, reason, row in result.rejected[:MAX_REJECTED_SHOWN]
        ],
    }
