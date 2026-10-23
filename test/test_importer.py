import csv
from datetime import date

import pytest
from sqlmodel import select

from app.importer import (
    CsvFormatError,
    import_csv,
    main,
    map_columns,
    parse_date,
    parse_price,
    write_rejected,
)
from app.models import Price, Product, Store

TODAY = date(2026, 10, 23)
HEADER = "product_name,brand,unit,store_name,city,price,date"


def write_csv(path, *lines, header=HEADER, delimiter=","):
    text = "\n".join([header, *lines]) + "\n"
    path.write_text(text.replace(",", delimiter), encoding="utf-8")
    return path


class TestParsePrice:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("19.09", 1909),
            ("4.59", 459),
            ("20,50", 2050),
            ("R$ 20,50", 2050),
            ("1.299,90", 129990),
            ("1,299.90", 129990),
            ("20", 2000),
            ("0.1", 10),
            ("1.000", 100000),
        ],
    )
    def test_converts_to_cents(self, raw, expected):
        assert parse_price(raw) == expected

    def test_no_float_rounding_errors(self):
        assert parse_price("1.15") == 115  # float: 1.15 * 100 = 114.99999999999999

    def test_already_in_cents(self):
        assert parse_price("2050", cents=True) == 2050

    @pytest.mark.parametrize("raw", ["20.5", "abc"])
    def test_cents_mode_rejects_non_integers(self, raw):
        with pytest.raises(ValueError):
            parse_price(raw, cents=True)

    @pytest.mark.parametrize("raw", ["", "abc", "0", "0,00", "-5", None])
    def test_invalid(self, raw):
        with pytest.raises(ValueError):
            parse_price(raw)


class TestParseDate:
    def test_iso(self):
        assert parse_date("2026-10-22") == date(2026, 10, 22)

    def test_day_first(self):
        assert parse_date("22/10/2026") == date(2026, 10, 22)

    def test_strips_spaces(self):
        assert parse_date(" 2026-10-22 ") == date(2026, 10, 22)

    @pytest.mark.parametrize("raw", ["", "22-10-2026", "2026-13-01", "ontem", None])
    def test_invalid(self, raw):
        with pytest.raises(ValueError):
            parse_date(raw)


class TestMapColumns:
    def test_real_file_header(self):
        mapping = map_columns(HEADER.split(","))
        assert mapping["product"] == "product_name"
        assert mapping["location"] == "city"

    def test_case_insensitive_and_portuguese(self):
        mapping = map_columns(["Produto", "MARCA", "Loja", "Cidade", "Preço", "Data"])
        assert mapping["price"] == "Preço"
        assert mapping["store"] == "Loja"

    def test_reports_missing_columns(self):
        with pytest.raises(CsvFormatError, match="price"):
            map_columns(["product", "brand", "store", "location", "date"])


class TestImportCsv:
    def test_imports_rows(self, tmp_path, session):
        path = write_csv(
            tmp_path / "p.csv",
            "Milk 1L,Brand C,l,Store C,City C,5.49,2026-10-20",
            "Milk 1L,Brand C,l,Store A,City A,5.99,2026-10-21",
        )
        result = import_csv(path, session, today=TODAY)

        assert (result.read, result.created, len(result.rejected)) == (2, 2, 0)
        assert (result.new_products, result.new_stores) == (1, 1)  # Store A já existe
        milk = session.exec(select(Product).where(Product.name == "Milk 1L")).one()
        prices = session.exec(select(Price).where(Price.product_id == milk.id)).all()
        assert sorted(p.price for p in prices) == [549, 599]
        assert all(type(p.date) is date for p in prices)

    def test_reuses_existing_product_and_store_ignoring_case(self, tmp_path, session):
        path = write_csv(
            tmp_path / "p.csv", "  rice   5KG ,brand a,kg,STORE a,city a,25.00,2026-10-22"
        )
        result = import_csv(path, session, today=TODAY)
        assert (result.new_products, result.new_stores, result.created) == (0, 0, 1)
        assert len(session.exec(select(Product)).all()) == 2
        assert len(session.exec(select(Store)).all()) == 2

    def test_reimport_is_idempotent(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Milk,B,l,Store C,City C,5.49,2026-10-20")
        import_csv(path, session, today=TODAY)
        second = import_csv(path, session, today=TODAY)
        assert (second.created, second.updated, second.unchanged) == (0, 0, 1)
        assert len(session.exec(select(Price)).all()) == 5

    def test_changed_price_is_updated(self, tmp_path, session):
        import_csv(write_csv(tmp_path / "a.csv", "Milk,B,l,S,C,5.49,2026-10-20"), session, today=TODAY)
        result = import_csv(
            write_csv(tmp_path / "b.csv", "Milk,B,l,S,C,5.99,2026-10-20"), session, today=TODAY
        )
        assert (result.created, result.updated) == (0, 1)
        assert session.exec(select(Price).where(Price.price == 599)).one()

    def test_bad_rows_are_rejected_not_fatal(self, tmp_path, session):
        path = write_csv(
            tmp_path / "p.csv",
            "Milk,B,l,Store C,City C,5.49,2026-10-20",
            "Milk,B,l,Store C,City C,abc,2026-10-20",
            "Milk,B,l,Store C,City C,5.49,2026-13-40",
            "Milk,B,l,Store C,City C,5.49,2099-01-01",
            ",B,l,Store C,City C,5.49,2026-10-20",
            "Milk,B,l,Store C,City C,0,2026-10-21",
        )
        result = import_csv(path, session, today=TODAY)
        assert (result.read, result.created, len(result.rejected)) == (6, 1, 5)
        reasons = [reason for _, reason, _ in result.rejected]
        assert any("price" in r for r in reasons)
        assert any("future" in r for r in reasons)
        assert [line for line, _, _ in result.rejected] == [3, 4, 5, 6, 7]

    def test_rejected_row_does_not_leave_orphan_product(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Soap,B,un,Store C,City C,abc,2026-10-20")
        result = import_csv(path, session, today=TODAY)
        assert result.created == 0
        assert session.exec(select(Product).where(Product.name == "Soap")).first() is None

    def test_cents_flag(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Milk,B,l,S,C,549,2026-10-20")
        import_csv(path, session, cents=True, today=TODAY)
        assert session.exec(select(Price).where(Price.price == 549)).one()

    def test_semicolon_delimiter_and_bom(self, tmp_path, session):
        path = tmp_path / "p.csv"
        path.write_text(
            "﻿produto;marca;loja;cidade;preco;data\nLeite;Marca X;Loja Y;Cidade Z;5,49;22/10/2026\n",
            encoding="utf-8",
        )
        result = import_csv(path, session, today=TODAY)
        assert (result.created, len(result.rejected)) == (1, 0)
        assert session.exec(select(Price).where(Price.price == 549)).one().date == date(2026, 10, 22)

    def test_extra_columns_ignored(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Milk,B,l,S,C,5.49,2026-10-20")
        assert import_csv(path, session, today=TODAY).created == 1

    def test_missing_column_raises(self, tmp_path, session):
        path = tmp_path / "p.csv"
        path.write_text("product,brand\nMilk,B\n", encoding="utf-8")
        with pytest.raises(CsvFormatError):
            import_csv(path, session, today=TODAY)

    def test_commits_in_batches(self, tmp_path, session):
        lines = [f"Item {i},B,un,S,C,1.00,2026-10-20" for i in range(25)]
        result = import_csv(write_csv(tmp_path / "p.csv", *lines), session, today=TODAY, batch_size=10)
        assert result.created == 25
        assert len(session.exec(select(Product)).all()) == 27

    def test_header_only_file(self, tmp_path, session):
        result = import_csv(write_csv(tmp_path / "p.csv"), session, today=TODAY)
        assert result.read == 0


class TestWriteRejected:
    def test_writes_reasons(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Milk,B,l,S,C,abc,2026-10-20")
        result = import_csv(path, session, today=TODAY)
        out = write_rejected(path, result)
        assert out == tmp_path / "p.rejected.csv"
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert rows[0]["line"] == "2"
        assert "price" in rows[0]["reason"]
        assert rows[0]["product_name"] == "Milk"

    def test_nothing_rejected_writes_nothing(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Milk,B,l,S,C,5.49,2026-10-20")
        assert write_rejected(path, import_csv(path, session, today=TODAY)) is None
        assert not (tmp_path / "p.rejected.csv").exists()


class TestCli:
    def test_main_imports_into_configured_database(self, tmp_path, engine, monkeypatch, capsys):
        from app import database

        monkeypatch.setattr(database, "engine", engine)
        path = write_csv(
            tmp_path / "p.csv",
            "Milk,B,l,Store C,City C,5.49,2026-10-20",
            "Milk,B,l,Store C,City C,abc,2026-10-20",
        )
        assert main([str(path)]) == 0
        out = capsys.readouterr().out
        assert "1 prices created" in out and "1 rejected" in out
        assert (tmp_path / "p.rejected.csv").exists()

    def test_main_reports_bad_file(self, tmp_path, engine, monkeypatch, capsys):
        from app import database

        monkeypatch.setattr(database, "engine", engine)
        bad = tmp_path / "bad.csv"
        bad.write_text("x,y\n1,2\n", encoding="utf-8")
        assert main([str(bad)]) == 1
        assert "missing columns" in capsys.readouterr().err
        assert main([str(tmp_path / "nope.csv")]) == 1


class TestDryRun:
    def test_reports_but_saves_nothing(self, tmp_path, session):
        path = write_csv(
            tmp_path / "p.csv",
            "Milk,B,l,Store C,City C,5.49,2026-10-20",
            "Milk,B,l,Store C,City C,abc,2026-10-20",
        )
        result = import_csv(path, session, today=TODAY, dry_run=True)
        assert result.dry_run is True
        assert (result.created, result.new_products, result.new_stores, len(result.rejected)) == (1, 1, 1, 1)
        assert session.exec(select(Product).where(Product.name == "Milk")).first() is None
        assert session.exec(select(Store).where(Store.name == "Store C")).first() is None
        assert len(session.exec(select(Price)).all()) == 4

    def test_same_numbers_as_the_real_import(self, tmp_path, session):
        path = write_csv(
            tmp_path / "p.csv",
            "Milk,B,l,Store C,City C,5.49,2026-10-20",
            "Rice 5kg,Brand A,kg,Store A,City A,25.00,2026-10-02",
            "Rice 5kg,Brand A,kg,Store A,City A,20.00,2026-10-02",
        )
        dry = import_csv(path, session, today=TODAY, dry_run=True)
        real = import_csv(path, session, today=TODAY)
        fields = ("read", "created", "updated", "unchanged", "new_products", "new_stores")
        assert [getattr(dry, f) for f in fields] == [getattr(real, f) for f in fields]

    def test_exposes_detected_columns(self, tmp_path, session):
        path = write_csv(tmp_path / "p.csv", "Milk,B,l,S,C,5.49,2026-10-20")
        result = import_csv(path, session, today=TODAY, dry_run=True)
        assert result.columns["location"] == "city"


class TestMessyRows:
    def test_rows_with_extra_or_missing_cells(self, tmp_path, session):
        path = tmp_path / "p.csv"
        path.write_text(
            f"{HEADER}\nMilk,B,l,S,C,5.49,2026-10-20,EXTRA\nShort,B,l\n", encoding="utf-8"
        )
        result = import_csv(path, session, today=TODAY)
        assert (result.created, len(result.rejected)) == (1, 1)
        out = write_rejected(path, result)
        assert "Short" in out.read_text(encoding="utf-8")
