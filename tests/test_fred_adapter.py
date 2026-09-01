from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import fred_adapter as fred  # noqa: E402
import money_craft as mc  # noqa: E402


TEST_KEY = "a" * 32


class FakeResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class FakeOpener:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[object] = []

    def open(self, request: object, timeout: int) -> FakeResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome


class FredCredentialTests(unittest.TestCase):
    def test_secure_file_and_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = fred.api_key_path(home, {})
            path.parent.mkdir(parents=True)
            path.write_text(TEST_KEY + "\n", encoding="utf-8")
            path.chmod(0o600)
            credential = fred.load_credential({}, home=home)
            self.assertEqual(credential.api_key, TEST_KEY)
            self.assertEqual(credential.source, "secure-file")
            overridden = fred.load_credential({"FRED_API_KEY": "b" * 32}, home=home)
            self.assertEqual(overridden.api_key, "b" * 32)
            self.assertEqual(overridden.source, "environment")

    def test_secure_file_rejects_permissive_mode_symlink_and_bad_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = fred.api_key_path(home, {})
            path.parent.mkdir(parents=True)
            path.write_text(TEST_KEY + "\n", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(fred.FredAdapterError):
                fred.load_credential({}, home=home)
            path.unlink()
            target = path.parent / "target"
            target.write_text(TEST_KEY + "\n", encoding="utf-8")
            target.chmod(0o600)
            path.symlink_to(target)
            with self.assertRaises(fred.FredAdapterError):
                fred.load_credential({}, home=home)
            path.unlink()
            path.write_text("INVALID\n", encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(fred.FredAdapterError) as caught:
                fred.load_credential({}, home=home)
            self.assertEqual(caught.exception.kind, "invalid_configuration")


class FredClientTests(unittest.TestCase):
    def test_observations_preserve_wire_payload_without_persisting_key(self) -> None:
        raw = json.dumps(
            {
                "realtime_start": "2026-08-31",
                "realtime_end": "2026-08-31",
                "count": 1,
                "observations": [
                    {
                        "realtime_start": "2026-08-31",
                        "realtime_end": "2026-08-31",
                        "date": "2026-07-01",
                        "value": "2.7",
                    }
                ],
            }
        ).encode("utf-8")
        opener = FakeOpener([FakeResponse(raw)])
        result = fred.FredClient(TEST_KEY, base_url="https://fixture.invalid", opener=opener).request(
            "observations",
            {
                "series_id": "PCEPI",
                "realtime_start": "2026-08-31",
                "realtime_end": "2026-08-31",
            },
        )
        request = opener.requests[0]
        self.assertIn("api_key=" + TEST_KEY, request.full_url)
        self.assertNotIn("api_key", result.parameters)
        self.assertNotIn(TEST_KEY.encode(), result.raw_response)
        self.assertEqual(result.data["observations"][0]["value"], "2.7")

    def test_http_rate_limit_retries_and_bounds_retry_after(self) -> None:
        error = urllib.error.HTTPError(
            "https://fixture.invalid/series/search",
            429,
            "rate limited",
            {"Retry-After": "99"},
            io.BytesIO(b'{"error_code":429,"error_message":"rate limited"}'),
        )
        success = FakeResponse(b'{"seriess":[]}')
        opener = FakeOpener([error, success])
        sleeps: list[float] = []
        result = fred.FredClient(
            TEST_KEY,
            base_url="https://fixture.invalid",
            opener=opener,
            sleeper=sleeps.append,
        ).request("search", {"search_text": "inflation", "limit": 5})
        self.assertEqual(result.data["seriess"], [])
        self.assertEqual(sleeps, [10.0])

    def test_error_message_redacts_reflected_key(self) -> None:
        error = urllib.error.HTTPError(
            "https://fixture.invalid/series",
            400,
            "bad request",
            {},
            io.BytesIO(
                json.dumps(
                    {"error_code": 400, "error_message": f"invalid api_key {TEST_KEY}"}
                ).encode("utf-8")
            ),
        )
        with self.assertRaises(fred.FredAdapterError) as caught:
            fred.FredClient(
                TEST_KEY,
                base_url="https://fixture.invalid",
                opener=FakeOpener([error]),
            ).request("series", {"series_id": "FEDFUNDS"})
        self.assertNotIn(TEST_KEY, str(caught.exception))


class FredCliTests(unittest.TestCase):
    def test_cli_maps_current_and_as_known_on_observations(self) -> None:
        parser = mc.build_parser()
        args = parser.parse_args(
            [
                "data",
                "observations",
                "--series-id",
                "t10yie",
                "--start",
                "2025-01-01",
                "--end",
                "2026-01-01",
                "--as-known-on",
                "2026-01-15",
                "--units",
                "lin",
            ]
        )
        operation, path, parameters, output = mc.prepare_operation(args)
        self.assertEqual((operation, path), ("observations", "fred://series/observations"))
        self.assertEqual(parameters["series_id"], "T10YIE")
        self.assertEqual(parameters["realtime_start"], "2026-01-15")
        self.assertEqual(parameters["realtime_end"], "2026-01-15")
        self.assertEqual(output["as_known_on"], "2026-01-15")

    def test_fred_rejects_market_data_operations(self) -> None:
        parser = mc.build_parser()
        args = parser.parse_args(
            ["data", "snapshot", "--provider", "fred", "--thscodes", "600519.SH"]
        )
        with self.assertRaises(mc.MoneyCraftError):
            mc.prepare_operation(args)

    def test_missing_key_cli_exits_three_without_network(self) -> None:
        environment = dict(os.environ)
        environment.pop("FRED_API_KEY", None)
        environment.pop(mc.DATA_PYTHON_ENV, None)
        with tempfile.TemporaryDirectory() as directory:
            environment["HOME"] = directory
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "money_craft.py"),
                    "data",
                    "series",
                    "--series-id",
                    "FEDFUNDS",
                ],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, mc.EXIT_CONFIG)
        self.assertEqual(payload["provider"], "fred")
        self.assertEqual(payload["error"]["kind"], "missing_configuration")

    def test_default_data_runtime_is_stable_and_repo_external(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, source = mc.preferred_data_python({}, home=Path(directory))
        self.assertEqual(source, "default")
        self.assertEqual(
            path.parts[-7:],
            (".local", "share", "money-craft", "venvs", "data", "bin", "python"),
        )


if __name__ == "__main__":
    unittest.main()
