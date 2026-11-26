from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock, patch

from app.data360_client import (
    DATA360_ROOT,
    Data360Error,
    get_indicator_data,
    search_indicators,
)


class Data360ClientTests(TestCase):
    @patch("app.data360_client.requests.post")
    def test_search_uses_fixed_public_host_and_normalizes_results(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "@odata.count": 3,
            "value": [{
                "@search.score": 12.5,
                "series_description": {
                    "idno": "WB_WDI_NY_GDP_MKTP_KD_ZG",
                    "name": "GDP growth (annual %)",
                    "database_id": "WB_WDI",
                },
            }],
        }
        post.return_value = response

        result = search_indicators("GDP", top=3)

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["results"][0]["indicator_id"], "WB_WDI_NY_GDP_MKTP_KD_ZG")
        self.assertEqual(post.call_args.args[0], f"{DATA360_ROOT}/data360/searchv2")
        self.assertEqual(post.call_args.kwargs["json"]["search"], "GDP")

    @patch("app.data360_client.requests.get")
    def test_data_request_is_constrained_to_indicator_and_country(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "count": 1,
            "value": [{
                "DATABASE_ID": "WB_WDI",
                "INDICATOR": "WB_WDI_SP_POP_TOTL",
                "REF_AREA": "USA",
                "TIME_PERIOD": "2025",
                "OBS_VALUE": "341784857",
                "UNIT_MEASURE": "PS",
                "PRIVATE_FIELD": "not returned",
            }],
        }
        get.return_value = response

        result = get_indicator_data("WB_WDI", "WB_WDI_SP_POP_TOTL", "usa")

        self.assertEqual(result["results"][0]["TIME_PERIOD"], "2025")
        self.assertNotIn("PRIVATE_FIELD", result["results"][0])
        self.assertEqual(get.call_args.args[0], f"{DATA360_ROOT}/data360/data")
        self.assertEqual(get.call_args.kwargs["params"]["REF_AREA"], "USA")
        self.assertEqual(get.call_args.kwargs["params"]["isLatestData"], "true")

    @patch("app.data360_client.requests.post")
    def test_reports_invalid_search_payload(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"unexpected": []}
        post.return_value = response

        with self.assertRaises(Data360Error):
            search_indicators("GDP")

    @patch("app.data360_client.requests.get")
    def test_rejects_untrusted_query_values_before_network_call(self, get: Mock) -> None:
        with self.assertRaises(ValueError):
            get_indicator_data("WB_WDI", "WB_WDI_SP_POP_TOTL", "United States")
        get.assert_not_called()

    @patch("app.data360_client.requests.get")
    def test_explicit_period_range_disables_latest_only_filter(self, get: Mock) -> None:
        response = Mock()
        response.json.return_value = {"count": 0, "value": []}
        get.return_value = response

        get_indicator_data(
            "WB_WDI",
            "WB_WDI_SP_POP_TOTL",
            "USA",
            period_from="2020",
            period_to="2025",
        )

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["timePeriodFrom"], "2020")
        self.assertEqual(params["timePeriodTo"], "2025")
        self.assertNotIn("isLatestData", params)


if __name__ == "__main__":
    import unittest

    unittest.main()
