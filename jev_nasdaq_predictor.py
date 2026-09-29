#!/usr/bin/env python3
"""Daily Nasdaq direction prediction with TypeSafe Jev.

The script stores the exact Jev request and response for every successful run.
It uses only the Python standard library so the scheduled job has no package
installation step.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import pstdev
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"
CONFIG_PATH = ROOT / "jev_input_config.json"
PREDICTIONS_PATH = RUNS_DIR / "predictions.jsonl"
UTC = timezone.utc
USER_AGENT = "jev-nasdaq-predictor/1.0"
KEYCHAIN_SERVICE = "typesafe-api-key"
BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
TREASURY_XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | date) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value.isoformat()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def get_api_key() -> str | None:
    """Read the key from the process environment or the macOS Keychain.

    The automation service does not necessarily inherit the environment of an
    already-running Codex process, so Keychain is the durable local fallback.
    The secret is only held in memory for the HTTPS request.
    """
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                os.environ.get("USER", ""),
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    key = result.stdout.strip()
    return key or None


def fetch_history(symbol: str, lookback_days: int) -> list[dict[str, Any]]:
    encoded_symbol = quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?range={max(1, lookback_days)}d&interval=1d&events=history"
    )
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance request failed: {exc}") from exc

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo Finance returned an error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("Yahoo Finance returned no chart data")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote_data.get("close") or []
    volumes = quote_data.get("volume") or []
    rows: list[dict[str, Any]] = []
    for index, (timestamp, close) in enumerate(zip(timestamps, closes)):
        if close is None:
            continue
        session_date = datetime.fromtimestamp(timestamp, UTC).date()
        volume = volumes[index] if index < len(volumes) else None
        rows.append(
            {
                "date": session_date.isoformat(),
                "close": float(close),
                "volume": int(volume) if volume is not None else None,
            }
        )
    if len(rows) < 21:
        raise RuntimeError(f"Yahoo Finance returned only {len(rows)} usable closes")
    return rows


def fetch_yahoo_features(symbols: dict[str, str], lookback_days: int) -> dict[str, Any]:
    """Fetch cross-asset market series and reduce them to point-in-time features."""
    features: dict[str, Any] = {}
    for name, symbol in symbols.items():
        try:
            rows = fetch_history(symbol, lookback_days)
            closes = [row["close"] for row in rows]
            returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]

            def change(days: int) -> float | None:
                if len(closes) <= days:
                    return None
                return pct_change(closes[-1], closes[-days - 1])

            features[name] = {
                "symbol": symbol,
                "source": "Yahoo Finance chart API",
                "latest_session": rows[-1]["date"],
                "latest_close": closes[-1],
                "one_day_change": change(1),
                "five_day_change": change(5),
                "twenty_day_change": change(20),
                "twenty_day_volatility_annualized": pstdev(returns[-20:]) * math.sqrt(252),
            }
        except Exception as exc:
            features[name] = {
                "symbol": symbol,
                "source": "Yahoo Finance chart API",
                "status": "unavailable",
                "error": str(exc),
            }
    return features


def _xml_value(properties: ET.Element, field: str) -> float | None:
    for child in properties:
        if child.tag.rsplit("}", 1)[-1] == field:
            text = child.text
            if text in (None, ""):
                return None
            try:
                return float(text)
            except ValueError:
                return None
    return None


def fetch_treasury_features(run_at: datetime) -> dict[str, Any]:
    """Fetch the latest official Treasury nominal and real curves for this year."""
    year = run_at.date().year
    result: dict[str, Any] = {
        "source": "U.S. Treasury daily XML feed",
        "source_url": TREASURY_XML_URL,
        "retrieved_at_utc": iso(run_at),
    }
    try:
        curves: dict[str, dict[str, Any]] = {}
        for curve_name, params in (
            ("nominal", "daily_treasury_yield_curve"),
            ("real", "daily_treasury_real_yield_curve"),
        ):
            url = f"{TREASURY_XML_URL}?data={params}&field_tdr_date_value={year}"
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=20) as response:
                root = ET.fromstring(response.read())
            entries: list[dict[str, Any]] = []
            for entry in root:
                properties = next(
                    (node for node in entry.iter() if node.tag.rsplit("}", 1)[-1] == "properties"),
                    None,
                )
                if properties is None:
                    continue
                observation_date = next(
                    (node.text for node in properties if node.tag.rsplit("}", 1)[-1] == "NEW_DATE"),
                    None,
                )
                if not observation_date:
                    continue
                observed = date.fromisoformat(observation_date[:10])
                if observed > run_at.date():
                    continue
                if curve_name == "nominal":
                    values = {
                        "yield_2y_pct": _xml_value(properties, "BC_2YEAR"),
                        "yield_10y_pct": _xml_value(properties, "BC_10YEAR"),
                        "yield_30y_pct": _xml_value(properties, "BC_30YEAR"),
                    }
                else:
                    values = {"real_yield_10y_pct": _xml_value(properties, "TC_10YEAR")}
                entries.append({"observation_date": observed.isoformat(), **values})
            if entries:
                curves[curve_name] = sorted(entries, key=lambda item: item["observation_date"])[-1]
        nominal = curves.get("nominal", {})
        if nominal.get("yield_10y_pct") is not None and nominal.get("yield_2y_pct") is not None:
            nominal["yield_curve_10y_minus_2y_pct"] = nominal["yield_10y_pct"] - nominal["yield_2y_pct"]
        result["curves"] = curves
        result["status"] = "ok" if curves else "unavailable"
        return result
    except Exception as exc:
        result.update({"status": "unavailable", "error": str(exc)})
        return result


def fetch_bls_features(run_at: datetime, series_config: dict[str, str]) -> dict[str, Any]:
    """Fetch current BLS observations and calculate only deterministic changes."""
    result: dict[str, Any] = {
        "source": "U.S. Bureau of Labor Statistics public API",
        "source_url": BLS_API_URL,
        "retrieved_at_utc": iso(run_at),
    }
    try:
        start_year = str(run_at.date().year - 3)
        by_name: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, str] = {}
        for name, series_id in series_config.items():
            url = f"{BLS_API_URL}{quote(series_id, safe='')}?startyear={start_year}&endyear={run_at.date().year}"
            payload = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    request = Request(url, headers={"User-Agent": USER_AGENT})
                    with urlopen(request, timeout=20) as response:
                        payload = json.load(response)
                    if payload.get("status") != "REQUEST_SUCCEEDED":
                        raise RuntimeError(f"BLS API status: {payload.get('status')}")
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(1 + attempt)
            if payload is None:
                errors[name] = str(last_error)
                continue
            series = ((payload.get("Results") or {}).get("series") or [{}])[0]
            records = []
            for item in series.get("data", []):
                period = item.get("period", "")
                if not period.startswith("M") or period == "M13":
                    continue
                try:
                    records.append(
                        {
                            "period": f"{item['year']}-{int(period[1:]):02d}",
                            "value": float(item["value"]),
                            "preliminary": any(
                                note.get("code") == "P" for note in item.get("footnotes", []) if note
                            ),
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            by_name[name] = sorted(records, key=lambda item: item["period"])

        def latest(name: str) -> dict[str, Any] | None:
            records = by_name.get(name, [])
            return records[-1] if records else None

        def previous(name: str) -> dict[str, Any] | None:
            records = by_name.get(name, [])
            return records[-2] if len(records) >= 2 else None

        def year_ago(name: str) -> dict[str, Any] | None:
            current = latest(name)
            if not current:
                return None
            target = f"{int(current['period'][:4]) - 1}{current['period'][4:]}"
            return next((item for item in by_name.get(name, []) if item["period"] == target), None)

        def snapshot(name: str, unit: str, yoy: bool = False) -> dict[str, Any] | None:
            current = latest(name)
            if not current:
                return None
            prior = previous(name)
            value: dict[str, Any] = {
                "series_id": series_config.get(name),
                "period": current["period"],
                "value": current["value"],
                "unit": unit,
                "preliminary": current["preliminary"],
            }
            if prior:
                value["month_change"] = current["value"] - prior["value"]
                if prior["value"]:
                    value["month_change_pct"] = current["value"] / prior["value"] - 1.0
            if yoy:
                prior_year = year_ago(name)
                if prior_year and prior_year["value"]:
                    value["year_over_year_pct"] = current["value"] / prior_year["value"] - 1.0
            return value

        result["cpi"] = {
            "headline": snapshot("cpi_headline_index", "index", yoy=True),
            "core": snapshot("cpi_core_index", "index", yoy=True),
        }
        result["labor"] = {
            "unemployment_rate": snapshot("unemployment_rate", "percent"),
            "nonfarm_payrolls": snapshot("nonfarm_payrolls", "thousands_of_jobs"),
            "average_hourly_earnings": snapshot("average_hourly_earnings", "dollars_per_hour", yoy=False),
        }
        result["status"] = "ok" if not errors else "partial"
        if errors:
            result["errors"] = errors
        return result
    except Exception as exc:
        result.update({"status": "unavailable", "error": str(exc)})
        return result


def pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return current / previous - 1.0


def build_state(
    history: list[dict[str, Any]],
    config: dict[str, Any],
    run_at: datetime,
    cross_asset_features: dict[str, Any],
    treasury_features: dict[str, Any],
    bls_features: dict[str, Any],
) -> dict[str, Any]:
    closes = [row["close"] for row in history]
    latest = closes[-1]
    previous = closes[-2]
    returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]

    def window_return(days: int) -> float | None:
        if len(closes) <= days:
            return None
        return pct_change(latest, closes[-days - 1])

    last_20 = closes[-20:]
    low_20 = min(last_20)
    high_20 = max(last_20)
    range_20 = high_20 - low_20
    state = {
        "input_schema_version": config.get("input_schema_version", "unknown"),
        "instrument": {
            "name": "Nasdaq Composite",
            "symbol": config["symbol"],
            "direction_target": "next available US regular trading session close vs latest available close",
        },
        "as_of_utc": iso(run_at),
        "latest_session": history[-1]["date"],
        "latest_close": latest,
        "market_features": {
            "one_day_return": pct_change(latest, previous),
            "five_day_return": window_return(5),
            "twenty_day_return": window_return(20),
            "twenty_day_volatility_annualized": pstdev(returns[-20:]) * math.sqrt(252),
            "twenty_day_low": low_20,
            "twenty_day_high": high_20,
            "twenty_day_range_position": (latest - low_20) / range_20 if range_20 else 0.5,
            "sma_5": sum(closes[-5:]) / 5,
            "sma_20": sum(closes[-20:]) / 20,
        },
        "cross_asset_features": cross_asset_features,
        "rates_features": treasury_features,
        "macro_features": bls_features,
        "data_provenance": {
            "retrieved_at_utc": iso(run_at),
            "point_in_time_rule": "Use only observations returned by the source at or before as_of_utc; retain this request snapshot as the exact model input.",
            "macro_revision_note": "BLS observations can be revised; this run stores the exact values presented to Jev for later audit.",
        },
        "recent_sessions": history[-int(config["recent_points"]):],
        "rules": [
            "Use only the supplied market state.",
            "Treat missing or unavailable source sections as unknown, not as zero.",
            "Do not infer a release that was not available by as_of_utc.",
            "Choose exactly one of up or down.",
            "Do not treat model confidence as a guarantee of correctness.",
        ],
    }
    return state


def expected_next_session(as_of: date, baseline_session: str) -> str:
    baseline = date.fromisoformat(baseline_session)
    # At 20:00 Beijing the current US session has not opened yet, so a weekday
    # with an older latest close is the expected target. Holidays are resolved
    # later by update_evaluations() from the actual next Yahoo candle.
    candidate = as_of if as_of.weekday() < 5 and baseline < as_of else as_of + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def request_payload(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": state,
        "model": config["model"],
        "questions": {
            "direction": {
                "type": "choice",
                "instructions": config["question"],
                "criteria": config["criteria"],
            }
        },
    }


def expanded_data_gaps(state: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    cross_asset = state.get("cross_asset_features", {})
    for name, feature in cross_asset.items():
        if feature.get("status", "ok") != "ok":
            gaps.append(f"cross_asset_features.{name}")
    if state.get("rates_features", {}).get("status") != "ok":
        gaps.append("rates_features")
    if state.get("macro_features", {}).get("status") != "ok":
        gaps.append("macro_features")
    return gaps


def call_jev(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        "https://api.typesafe.ai/v1/systemone",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "jev-nasdaq-predictor/1.0",
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 529) and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Jev API HTTP {exc.code}: {response_body}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Jev API request failed: {exc}") from exc
    raise RuntimeError("Jev API request exhausted retries")


def read_prediction_rows() -> list[dict[str, Any]]:
    if not PREDICTIONS_PATH.exists():
        return []
    rows = []
    with PREDICTIONS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def update_evaluations(history: list[dict[str, Any]]) -> int:
    rows = read_prediction_rows()
    if not rows:
        return 0
    changed = 0
    for row in rows:
        if row.get("actual_direction"):
            continue
        baseline_date = row.get("baseline_session")
        if not baseline_date:
            continue
        following = [item for item in history if item["date"] > baseline_date]
        if not following:
            continue
        actual = following[0]
        baseline = next((item for item in history if item["date"] == baseline_date), None)
        if baseline is None:
            continue
        actual_direction = "up" if actual["close"] > baseline["close"] else "down"
        row.update(
            {
                "actual_session": actual["date"],
                "actual_close": actual["close"],
                "actual_direction": actual_direction,
                "correct": row.get("prediction") == actual_direction,
                "evaluated_at_utc": iso(now_utc()),
            }
        )
        changed += 1
    if changed:
        temporary = PREDICTIONS_PATH.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary.replace(PREDICTIONS_PATH)
    return changed


def run(dry_run: bool = False) -> int:
    run_at = now_utc()
    config = read_json(CONFIG_PATH)
    history = fetch_history(config["symbol"], int(config["lookback_days"]))
    update_evaluations(history)
    cross_asset_features = fetch_yahoo_features(
        config.get("cross_asset_symbols", {}), int(config["lookback_days"])
    )
    treasury_features = fetch_treasury_features(run_at)
    bls_features = fetch_bls_features(run_at, config.get("bls_series", {}))
    state = build_state(
        history,
        config,
        run_at,
        cross_asset_features,
        treasury_features,
        bls_features,
    )
    payload = request_payload(state, config)
    data_gaps = expanded_data_gaps(state)
    run_id = f"{run_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_id
    write_json(run_dir / "jev_request.json", payload)
    metadata = {
        "run_id": run_id,
        "started_at_utc": iso(run_at),
        "baseline_session": history[-1]["date"],
        "expected_next_session": expected_next_session(run_at.date(), history[-1]["date"]),
        "symbol": config["symbol"],
        "model_requested": config["model"],
        "input_schema_version": config.get("input_schema_version", "unknown"),
        "expanded_data_status": "ok" if not data_gaps else "incomplete",
        "expanded_data_gaps": data_gaps,
        "status": "dry_run" if dry_run else "started",
    }
    write_json(run_dir / "run_metadata.json", metadata)

    if dry_run:
        metadata.update({"status": "dry_run", "finished_at_utc": iso(now_utc())})
        write_json(run_dir / "run_metadata.json", metadata)
        print(json.dumps({"run_id": run_id, "status": "dry_run", "request": str(run_dir / 'jev_request.json')}))
        return 0

    if data_gaps:
        error = "Expanded input data is incomplete; Jev was not called: " + ", ".join(data_gaps)
        write_json(run_dir / "error.json", {"error": error, "missing_sections": data_gaps})
        metadata.update({"status": "blocked_incomplete_expanded_data", "finished_at_utc": iso(now_utc())})
        write_json(run_dir / "run_metadata.json", metadata)
        print(error, file=sys.stderr)
        return 3

    api_key = get_api_key()
    if not api_key:
        error = "TYPESAFE_API_KEY is not set; request was saved but Jev was not called"
        write_json(run_dir / "error.json", {"error": error})
        metadata.update({"status": "blocked_missing_api_key", "finished_at_utc": iso(now_utc())})
        write_json(run_dir / "run_metadata.json", metadata)
        print(error, file=sys.stderr)
        return 2

    try:
        response = call_jev(payload, api_key)
        write_json(run_dir / "jev_response.json", response)
        answer = (response.get("answers") or {}).get("direction") or {}
        prediction = answer.get("choice")
        probabilities = answer.get("probabilities") or {}
        summary = {
            "run_id": run_id,
            "run_at_utc": iso(run_at),
            "baseline_session": history[-1]["date"],
            "prediction": prediction,
            "probability_up": probabilities.get("up"),
            "probability_down": probabilities.get("down"),
            "confidence": answer.get("confidence"),
            "model": response.get("model"),
            "input_tokens": (response.get("usage") or {}).get("input_tokens"),
            "output_tokens": (response.get("usage") or {}).get("output_tokens"),
            "expanded_data_status": "ok",
            "input_schema_version": config.get("input_schema_version", "unknown"),
            "usable_for_accuracy": True,
        }
        append_jsonl(PREDICTIONS_PATH, summary)
        metadata.update({"status": "ok", "finished_at_utc": iso(now_utc())})
        write_json(run_dir / "run_metadata.json", metadata)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:  # Persist failures for later diagnosis by the user.
        write_json(run_dir / "error.json", {"error": str(exc)})
        metadata.update({"status": "error", "finished_at_utc": iso(now_utc())})
        write_json(run_dir / "run_metadata.json", metadata)
        print(str(exc), file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch data and save the exact request without calling Jev")
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
