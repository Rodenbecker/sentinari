from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from app.eu_portal_search import (
    EuPortalSearchError,
    ingest_eu_dataset_metadata_into_field,
    search_eu_datasets,
)


class EuPortalSearchTests(unittest.TestCase):
    @patch("app.eu_portal_search.requests.get")
    def test_search_normalizes_dataset_and_uses_public_search_api(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "result": {
                "count": 100,
                "results": [
                    {
                        "id": "ai-dataset",
                        "resource": "http://data.europa.eu/88u/dataset/ai-dataset",
                        "title": {"fr": "IA européenne", "en": "European AI"},
                        "description": {
                            "en": "<dp-prose><p>AI research data &amp; statistics.</p></dp-prose>"
                        },
                        "publisher": {"en": "European Commission"},
                        "catalog": {"label": "European catalogue"},
                        "issued": "2024-06-01T00:00:00Z",
                        "modified": "2025-01-10T00:00:00Z",
                        "distributions": [
                            {
                                "title": {"en": "CSV data"},
                                "access_url": ["https://data.europa.eu/files/ai.csv"],
                                "format": {
                                    "id": "CSV",
                                    "label": "CSV",
                                    "resource": "http://example.test/CSV",
                                },
                            },
                            {
                                "title": {"en": "Insecure data"},
                                "access_url": ["http://example.test/data.csv"],
                            },
                        ],
                    }
                ],
            }
        }
        get.return_value = response

        result = search_eu_datasets("European AI", page=2, limit=7, from_year=2020)

        self.assertEqual(result["count"], 1)
        dataset = result["datasets"][0]
        self.assertEqual(dataset["title"], "European AI")
        self.assertEqual(dataset["description"], "AI research data & statistics.")
        self.assertEqual(dataset["source_url"], "https://data.europa.eu/88u/dataset/ai-dataset")
        self.assertEqual(len(dataset["distributions"]), 1)
        self.assertEqual(dataset["distributions"][0]["format"], "CSV")

        call = get.call_args
        self.assertEqual(call.args[0], "https://data.europa.eu/api/hub/search/search")
        self.assertEqual(call.kwargs["params"]["filters"], "dataset")
        self.assertEqual(call.kwargs["params"]["page"], 2)
        self.assertEqual(call.kwargs["params"]["minDate"], "2020-01-01T00:00:00Z")
        self.assertNotIn("Authorization", call.kwargs["headers"])

    @patch("app.eu_portal_search.requests.get")
    def test_reports_invalid_search_response(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {"unexpected": []}
        get.return_value = response

        with self.assertRaises(EuPortalSearchError):
            search_eu_datasets("European AI")

    def test_ingests_metadata_record_with_resource_links(self) -> None:
        ingestion_module = types.ModuleType("app.ingestion")
        ingest_files = Mock(return_value={"ingested": 1, "failed": 0, "items": []})
        ingestion_module.ingest_files = ingest_files
        dataset = {
            "dataset_id": "ai-dataset",
            "title": "European AI",
            "description": "A public dataset description.",
            "source_url": "https://data.europa.eu/88u/dataset/ai-dataset",
            "resource_uri": "http://data.europa.eu/88u/dataset/ai-dataset",
            "publisher": "European Commission",
            "catalogue": "EU catalogue",
            "issued": "2024-06-01T00:00:00Z",
            "modified": "2025-01-10T00:00:00Z",
            "license": "CC-BY-4.0",
            "distributions": [
                {
                    "title": "CSV data",
                    "url": "https://data.europa.eu/files/ai.csv",
                    "format": "CSV",
                    "license": "CC-BY-4.0",
                }
            ],
        }

        with TemporaryDirectory() as temp_dir:
            with (
                patch.dict(sys.modules, {"app.ingestion": ingestion_module}),
                patch("app.eu_portal_search.get_project_root", return_value=Path(temp_dir)),
            ):
                result = ingest_eu_dataset_metadata_into_field("computer science", dataset)
            metadata_file = (
                Path(temp_dir)
                / "data"
                / "research_sources"
                / "eu_data_portal"
                / "ai-dataset.md"
            )
            content = metadata_file.read_text(encoding="utf-8")

        self.assertEqual(result["ingested"], 1)
        self.assertIn("A public dataset description.", content)
        self.assertIn("https://data.europa.eu/files/ai.csv", content)
        self.assertIn("not downloaded automatically", content)
        self.assertEqual(ingest_files.call_args.args[0], [str(metadata_file)])
        self.assertEqual(
            ingest_files.call_args.kwargs["metadata"]["scientific_field"],
            "computer science",
        )
        self.assertEqual(
            ingest_files.call_args.kwargs["metadata"]["source_type"],
            "eu_data_portal",
        )

    def test_rejects_non_portal_dataset_link(self) -> None:
        with self.assertRaises(ValueError):
            ingest_eu_dataset_metadata_into_field(
                "computer science",
                {"dataset_id": "bad-link", "source_url": "javascript:alert(1)"},
            )


if __name__ == "__main__":
    unittest.main()
