from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import money_craft as mc  # noqa: E402
import research_run  # noqa: E402
import yfinance_adapter as adapter  # noqa: E402


class FakeLoc:
    def __init__(self, frame: "FakeFrame") -> None:
        self.frame = frame

    def __getitem__(self, key: object) -> "FakeFrame":
        if isinstance(key, tuple):
            row_labels, column_labels = key
            row_positions = [self.frame.index.index(label) for label in row_labels]
            column_positions = [self.frame.columns.index(label) for label in column_labels]
        else:
            row_positions = [position for position, keep in enumerate(key) if keep]  # type: ignore[arg-type]
            column_positions = list(range(len(self.frame.columns)))
        return FakeFrame(
            [self.frame.index[position] for position in row_positions],
            [self.frame.columns[position] for position in column_positions],
            [
                [self.frame.rows[row][column] for column in column_positions]
                for row in row_positions
            ],
        )


class FakeFrame:
    def __init__(self, index: list[object], columns: list[object], rows: list[list[object]]) -> None:
        self.index = index
        self.columns = columns
        self.rows = rows
        self.loc = FakeLoc(self)

    def itertuples(self, index: bool = False, name: object | None = None):  # noqa: A002
        return iter(tuple(row) for row in self.rows)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.fast_info = {
            "currency": "USD",
            "exchange": "NMS",
            "timezone": "America/New_York",
            "quoteType": "EQUITY",
            "lastPrice": 123.45,
            "marketCap": 3000000000,
        }
        self.history_calls: list[dict[str, object]] = []

    def history(self, **kwargs: object) -> FakeFrame:
        self.history_calls.append(kwargs)
        return FakeFrame(
            [dt.datetime(2026, 8, 21, tzinfo=dt.timezone.utc)],
            ["Open", "Close", "Dividends"],
            [[120.0, 123.45, 0.0]],
        )

    def get_valuation_measures(self, **kwargs: object) -> FakeFrame:
        return FakeFrame(["MarketCap", "PeRatio"], ["Current"], [[3000000000], [30.5]])

    def get_income_stmt(self, **kwargs: object) -> FakeFrame:
        return FakeFrame(["TotalRevenue"], ["2025-01-26", "2024-01-28"], [[1000, 800]])

    get_balance_sheet = get_income_stmt
    get_cash_flow = get_income_stmt

    def get_actions(self, **kwargs: object) -> FakeFrame:
        return FakeFrame(
            [dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 1)],
            ["Dividends", "Stock Splits"],
            [[0.1, 0.0], [0.2, 0.0]],
        )


class FakeSearch:
    def __init__(self, query: str, **kwargs: object) -> None:
        self.quotes = [
            {
                "symbol": query.upper(),
                "shortname": "NVIDIA",
                "longname": "NVIDIA Corporation",
                "exchange": "NMS",
                "quoteType": "EQUITY",
                "currency": "USD",
            }
        ]


class FakeYFinance:
    __version__ = "1.7.0-test"
    Search = FakeSearch

    def __init__(self) -> None:
        self.tickers: list[FakeTicker] = []

    def Ticker(self, symbol: str) -> FakeTicker:  # noqa: N802
        ticker = FakeTicker(symbol)
        self.tickers.append(ticker)
        return ticker


class YFinanceAdapterTests(unittest.TestCase):
    def test_search_is_a_versioned_adapter_export_not_a_claimed_wire_response(self) -> None:
        module = FakeYFinance()
        result = adapter.YFinanceClient(module, version="1.7.0-test").request(
            "search", {"query": "NVDA", "limit": 5}
        )
        export = json.loads(result.adapter_export)
        self.assertEqual(export["schema"], "money-craft.yfinance-adapter-export.v1")
        self.assertEqual(export["provider"], "yfinance")
        self.assertEqual(result.data["item"][0]["symbol"], "NVDA")

    def test_empty_search_retries_with_a_bound_and_remains_a_provider_gap(self) -> None:
        calls: list[str] = []

        class EmptySearch:
            def __init__(self, query: str, **kwargs: object) -> None:
                calls.append(query)
                self.quotes: list[object] = []

        module = FakeYFinance()
        module.Search = EmptySearch
        sleeps: list[float] = []
        with self.assertRaises(adapter.YFinanceAdapterError) as caught:
            adapter.YFinanceClient(module, version="1.7.0-test", sleeper=sleeps.append).request(
                "search", {"query": "NVDA", "limit": 5}
            )
        self.assertEqual(caught.exception.kind, "transient_provider_error")
        self.assertEqual(calls, ["NVDA", "NVDA", "NVDA"])
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_history_converts_inclusive_money_craft_end_to_yfinance_exclusive_end(self) -> None:
        module = FakeYFinance()
        result = adapter.YFinanceClient(module, version="1.7.0-test").request(
            "history",
            {
                "symbol": "NVDA",
                "start": "2026-08-01",
                "end": "2026-08-23",
                "interval": "1d",
                "adjust": "auto",
            },
        )
        self.assertEqual(module.tickers[0].history_calls[0]["end"], "2026-08-24")
        self.assertEqual(result.data["adjustment"], "auto-adjusted")
        self.assertEqual(result.data["table"]["columns"], ["Open", "Close", "Dividends"])

    def test_snapshot_maps_current_fast_info_camel_case_contract(self) -> None:
        module = FakeYFinance()
        result = adapter.YFinanceClient(module, version="1.7.0-test").request(
            "snapshot", {"symbol": "NVDA"}
        )
        self.assertEqual(result.data["last_price"], adapter.Decimal("123.45"))
        self.assertEqual(result.data["market_cap"], 3000000000)
        self.assertEqual(result.data["quote_type"], "EQUITY")

    def test_financials_are_bounded_to_requested_columns(self) -> None:
        module = FakeYFinance()
        result = adapter.YFinanceClient(module, version="1.7.0-test").request(
            "financials.income",
            {"symbol": "NVDA", "period": "annual", "limit": 1},
        )
        self.assertEqual(result.data["table"]["columns"], ["2025-01-26"])
        self.assertEqual(result.data["table"]["rows"], [[1000]])

    def test_data_cli_preparation_keeps_fuyao_compatible_and_adds_explicit_yfinance_symbol(self) -> None:
        parser = mc.build_parser()
        args = parser.parse_args(
            [
                "data",
                "history",
                "--provider",
                "yfinance",
                "--symbol",
                "0700.HK",
                "--start",
                "2026-01-01",
                "--end",
                "2026-08-23",
                "--adjust",
                "auto",
            ]
        )
        operation, path, parameters, output = mc.prepare_operation(args)
        self.assertEqual((operation, path), ("history", "yfinance://history"))
        self.assertEqual(parameters["symbol"], "0700.HK")
        self.assertEqual(output["end"], "2026-08-23")

    def test_research_run_command_and_identity_are_provider_bound(self) -> None:
        item = {
            "id": "S01",
            "provider": "yfinance",
            "operation": "search",
            "arguments": {"query": "NVDA", "limit": 5},
        }
        command = research_run.operation_command(Path("runtime.py"), item, Path("captures"))
        self.assertIn("yfinance", command)
        payload = {
            "schema": "money-craft.data-response.v1",
            "ok": True,
            "provider": "yfinance",
            "operation": "search",
            "data": {
                "item": [
                    {"symbol": "NVDA", "currency": "USD", "quoteType": "EQUITY"}
                ]
            },
        }
        case = {
            "identity": {
                "base_currency": "USD",
                "provider_identifiers": {"yfinance": "NVDA"},
            }
        }
        research_run.validate_identity(payload, case)

    def test_yfinance_capture_is_labeled_as_an_unauthenticated_adapter_export(self) -> None:
        module = FakeYFinance()
        adapter_result = adapter.YFinanceClient(module, version="1.7.0-test").request(
            "snapshot", {"symbol": "NVDA"}
        )
        result = mc.ProviderResult(
            operation="snapshot",
            path="yfinance://snapshot",
            parameters={"symbol": "NVDA"},
            payload={"request_id": None, "data": adapter_result.data},
            raw_response=adapter_result.adapter_export,
            fetched_at=adapter_result.fetched_at,
            provider="yfinance",
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = mc.capture_result(
                Path(directory),
                "S02",
                result,
                output_parameters=result.parameters,
                authentication="none",
            )
            request = json.loads((destination / "request.json").read_text(encoding="utf-8"))
            capture = json.loads((destination / "capture.json").read_text(encoding="utf-8"))
        self.assertEqual(request["provider"], "yfinance")
        self.assertEqual(request["authentication"], "none")
        self.assertEqual(capture["provider"], "yfinance")


if __name__ == "__main__":
    unittest.main()
