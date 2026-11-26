from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from pypdf import PdfReader

from app.gci_index import (
    GCIIndexError,
    build_competitiveness_context,
    build_country_pdf,
    get_country,
    parse_booklet_pages,
    search_countries,
    ensure_index,
)


def _synthetic_pages() -> list[str]:
    pages = [""] * 87
    names = [f"Economy {index:02d}" for index in range(1, 71)]
    overall_rows = [
        f"{index:02d} {name} {100 - index / 2:.2f} k 1"
        for index, name in enumerate(names, start=1)
    ]
    pages[65] = "\n".join(overall_rows[:35])
    pages[66] = "\n".join(overall_rows[35:])

    factor_pages = ((75, 76), (77, 78), (79, 80), (81, 82))
    for factor_index, (first_page, second_page) in enumerate(factor_pages):
        rows = [
            f"{index:02d} {name} {100 - index / (factor_index + 2):.2f} k 1"
            for index, name in enumerate(names, start=1)
        ]
        pages[first_page] = "\n".join(rows[:36])
        pages[second_page] = "\n".join(rows[36:])

    for index, name in enumerate(names, start=1):
        ranks = " ".join([f"{index:02d}"] * 10)
        pages[85] += f"{name} {ranks}\n"
        pages[86] += f"{ranks} {name}\n"
    return pages


class GCIIndexTests(TestCase):
    def test_parser_keeps_factor_scores_distinct_from_subfactor_ranks(self) -> None:
        parsed = parse_booklet_pages(_synthetic_pages())

        self.assertEqual(len(parsed), 70)
        economy = parsed["Economy 01"]
        self.assertEqual(economy["overall_rank"], 1)
        self.assertEqual(len(economy["dimensions"]), 24)
        factors = [item for item in economy["dimensions"] if item["kind"] == "factor"]
        subfactors = [item for item in economy["dimensions"] if item["kind"] == "subfactor"]
        self.assertEqual(len(factors), 4)
        self.assertTrue(all(item["score"] is not None for item in factors))
        self.assertEqual(len(subfactors), 20)
        self.assertTrue(all(item["score"] is None for item in subfactors))
        self.assertEqual(subfactors[-1]["source_page"], 87)

    def test_rejects_incomplete_subfactor_tables(self) -> None:
        pages = _synthetic_pages()
        pages[86] = "\n".join(pages[86].splitlines()[:-1])

        with self.assertRaises(GCIIndexError):
            parse_booklet_pages(pages)

    def test_builds_searchable_index_report_context_and_country_pdf(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Booklet_WCY_2026.pdf"
            source.write_bytes(b"synthetic booklet")
            database = root / "index.sqlite3"
            with patch("app.gci_index._read_booklet_pages", return_value=_synthetic_pages()):
                result = ensure_index(pdf_path=source, db_path=database)
                self.assertTrue(result["updated"])

                country = get_country("economy 01", pdf_path=source, db_path=database)
                self.assertIsNotNone(country)
                self.assertEqual(len(country["dimensions"]), 24)
                self.assertEqual(search_countries("Economy 01", pdf_path=source, db_path=database)[0]["country"], "Economy 01")

                context = build_competitiveness_context(
                    {"paper_title": "A study in Economy 01"},
                    pdf_path=source,
                    db_path=database,
                )
                self.assertEqual(context["status"], "matched")
                self.assertEqual(context["country"], "Economy 01")
                self.assertEqual(len(context["subfactors"]), 20)

                ambiguous = build_competitiveness_context(
                    {"paper_title": "A comparison of Economy 01 and Economy 02"},
                    pdf_path=source,
                    db_path=database,
                )
                self.assertEqual(ambiguous["status"], "ambiguous")

                with patch("app.gci_index._read_booklet_pages", return_value=_synthetic_pages()):
                    pdf = build_country_pdf("Economy 01", pdf_path=source, db_path=database)
                text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
                self.assertIn("Economy 01", text)
                self.assertIn("Domestic Economy", text)


if __name__ == "__main__":
    import unittest

    unittest.main()
