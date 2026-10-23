"""Importa preços de um arquivo CSV para o banco.

Uso:
    uv run python -m app.importer precos.csv [--cents]

Colunas obrigatórias (o cabeçalho não diferencia maiúsculas de minúsculas):
    product, brand, store, location, price, date
Também são aceitos product_name, store_name, city e nomes em português
(produto, marca, loja, local/cidade, preco, data). Colunas extras (ex.: unit) são ignoradas.
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlmodel import Session, select

from app.models import Price, Product, Store

COLUMN_ALIASES = {
    "product": ("product", "product_name", "produto", "name", "nome"),
    "brand": ("brand", "marca"),
    "store": ("store", "store_name", "loja", "market", "mercado"),
    "location": ("location", "local", "localizacao", "localização", "city", "cidade"),
    "price": ("price", "preco", "preço", "valor"),
    "date": ("date", "data"),
}
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")
BATCH_SIZE = 1000


class CsvFormatError(ValueError):
    """O arquivo não tem as colunas esperadas."""


@dataclass
class ImportResult:
    read: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    new_products: int = 0
    new_stores: int = 0
    rejected: list[tuple[int, str, dict]] = field(default_factory=list)  # (linha, motivo, linha original)


def parse_price(raw: str, cents: bool = False) -> int:
    """Converte "20,50", "R$ 1.299,90", "20.5" ou "2050" (com cents=True) em centavos."""
    text = re.sub(r"[^\d.,-]", "", raw or "")
    if not text:
        raise ValueError("price is empty")
    if cents:
        if not re.fullmatch(r"\d+", text):
            raise ValueError(f"price in cents must be a whole number: {raw!r}")
        value = int(text)
    else:
        # O último separador é o decimal; os demais são milhares ("1.299,90" ou "1,299.90").
        last = max(text.rfind(","), text.rfind("."))
        if last != -1 and len(text) - last - 1 <= 2:
            integer, decimals = text[:last], text[last + 1 :]
            text = re.sub(r"[.,]", "", integer) + "." + decimals
        else:
            text = re.sub(r"[.,]", "", text)
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"invalid price: {raw!r}") from None
        value = int((amount * 100).to_integral_value())
    if value <= 0:
        raise ValueError(f"price must be greater than zero: {raw!r}")
    return value


def parse_date(raw: str) -> date:
    """Aceita AAAA-MM-DD ou DD/MM/AAAA."""
    text = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid date (use YYYY-MM-DD or DD/MM/YYYY): {raw!r}")


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def map_columns(fieldnames: list[str] | None) -> dict[str, str]:
    """Liga cada coluna lógica ao cabeçalho real do arquivo."""
    headers = {(name or "").strip().casefold(): name for name in fieldnames or []}
    mapping, missing = {}, []
    for logical, aliases in COLUMN_ALIASES.items():
        found = next((headers[a] for a in aliases if a in headers), None)
        if found is None:
            missing.append(logical)
        else:
            mapping[logical] = found
    if missing:
        raise CsvFormatError(
            f"missing columns: {', '.join(missing)} (found: {', '.join(fieldnames or [])})"
        )
    return mapping


def _open_reader(handle) -> csv.DictReader:
    sample = handle.read(4096)
    handle.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return csv.DictReader(handle, dialect=dialect)


def import_csv(
    path: str | Path,
    session: Session,
    cents: bool = False,
    today: date | None = None,
    batch_size: int = BATCH_SIZE,
) -> ImportResult:
    """
    Lê o CSV linha a linha e grava produtos, lojas e preços.

    - Produtos e lojas que já existem (ignorando maiúsculas) são reaproveitados.
    - Reimportar o mesmo arquivo não duplica: para o mesmo produto, loja e data,
      o preço existente é atualizado se mudou e ignorado se igual.
    - Linhas inválidas não interrompem a importação; vão para `result.rejected`.
    """
    today = today or date.today()
    result = ImportResult()

    products = {
        (p.name.casefold(), p.brand.casefold()): p.id for p in session.exec(select(Product))
    }
    stores = {
        (s.name.casefold(), s.location.casefold()): s.id for s in session.exec(select(Store))
    }

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = _open_reader(handle)
        columns = map_columns(reader.fieldnames)

        for row in reader:
            result.read += 1
            line = reader.line_num
            try:
                name = _clean(row[columns["product"]])
                brand = _clean(row[columns["brand"]])
                store_name = _clean(row[columns["store"]])
                location = _clean(row[columns["location"]])
                if not (name and brand and store_name and location):
                    raise ValueError("product, brand, store and location are required")
                price = parse_price(row[columns["price"]], cents)
                day = parse_date(row[columns["date"]])
                if day > today:
                    raise ValueError(f"date is in the future: {day}")

                product_key = (name.casefold(), brand.casefold())
                if product_key not in products:
                    product = Product(name=name, brand=brand)
                    session.add(product)
                    session.flush()
                    products[product_key] = product.id
                    result.new_products += 1

                store_key = (store_name.casefold(), location.casefold())
                if store_key not in stores:
                    store = Store(name=store_name, location=location)
                    session.add(store)
                    session.flush()
                    stores[store_key] = store.id
                    result.new_stores += 1

                existing = session.exec(
                    select(Price).where(
                        Price.product_id == products[product_key],
                        Price.store_id == stores[store_key],
                        Price.date == day,
                    )
                ).first()
                if existing is None:
                    session.add(
                        Price(
                            product_id=products[product_key],
                            store_id=stores[store_key],
                            price=price,
                            date=day,
                        )
                    )
                    result.created += 1
                elif existing.price != price:
                    existing.price = price
                    session.add(existing)
                    result.updated += 1
                else:
                    result.unchanged += 1
            except ValueError as error:
                result.rejected.append((line, str(error), row))

            if result.read % batch_size == 0:
                session.commit()

    session.commit()
    return result


def write_rejected(path: str | Path, result: ImportResult) -> Path | None:
    """Grava as linhas recusadas, com o motivo, em <arquivo>.rejected.csv."""
    if not result.rejected:
        return None
    target = Path(path).with_suffix(".rejected.csv")
    fieldnames = ["line", "reason", *result.rejected[0][2].keys()]
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for line, reason, row in result.rejected:
            writer.writerow({"line": line, "reason": reason, **row})
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa preços de um CSV para o banco.")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument(
        "--cents",
        action="store_true",
        help="a coluna price já está em centavos inteiros (ex.: 2050 = 20,50)",
    )
    args = parser.parse_args(argv)

    from app.database import create_db_and_tables, engine

    create_db_and_tables()
    with Session(engine) as session:
        try:
            result = import_csv(args.csv_file, session, cents=args.cents)
        except (CsvFormatError, OSError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    print(
        f"{result.read} rows read: {result.created} prices created, "
        f"{result.updated} updated, {result.unchanged} unchanged, "
        f"{len(result.rejected)} rejected "
        f"({result.new_products} new products, {result.new_stores} new stores)"
    )
    rejected_file = write_rejected(args.csv_file, result)
    if rejected_file:
        print(f"rejected rows written to {rejected_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
