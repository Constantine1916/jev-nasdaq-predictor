# JEV Nasdaq Daily Prediction

English / [简体中文](README.zh-CN.md)

This repository contains a Python runner that uses TypeSafe Jev to predict the direction of the Nasdaq Composite.

The current daily schedule at 20:00 Asia/Shanghai is managed by a local Codex automation and is intentionally outside this repository. A clone includes the runner and configuration, but you must configure the API key and scheduler yourself.

Each run:

1. Fetches Nasdaq Composite (`^IXIC`) history.
2. Fetches S&P 500, Nasdaq futures, VIX, the dollar, WTI, Brent, gold, U.S. Treasury yields, and BLS CPI and labor observations.
3. Builds the state sent to Jev.
4. Calls the pinned `jev-1.13.0` model to predict whether the next available U.S. regular-session close will be higher or lower than the latest known close.
5. Stores the complete request, raw Jev response, and an evaluable prediction record.

## Setup

The project uses only the Python standard library. On macOS, store the API key in Keychain:

```bash
security add-generic-password -U -a "$USER" -s typesafe-api-key -w 'your-typesafe-api-key'
```

The script first checks `TYPESAFE_API_KEY`; if it is absent, it reads the Keychain item for the current macOS user. The API key is used only at runtime and is never written to request files, result files, or logs.

On non-macOS systems, provide the key through the environment:

```bash
export TYPESAFE_API_KEY='your-typesafe-api-key'
```

Never commit a real API key, a `.env` file, or generated `runs/` output.

## Usage

Run a dry run to fetch data and save the Jev request without calling Jev:

```bash
python3 jev_nasdaq_predictor.py --dry-run
```

Run a real prediction:

```bash
python3 jev_nasdaq_predictor.py
```

## Output files

- `runs/<run-id>/jev_request.json`: the complete JSON request sent to Jev.
- `runs/<run-id>/jev_response.json`: Jev's raw response, including probabilities, confidence, model version, and token usage.
- `runs/<run-id>/run_metadata.json`: timestamps, baseline session, and run status.
- `runs/predictions.jsonl`: one row per successful prediction. Later runs backfill the actual direction and `correct` after the next close is available.

`runs/` and Python caches are included in `.gitignore` and are not committed to Git.

## Definition and limitations

The target is whether the next available U.S. regular-session close is higher or lower than the latest known Nasdaq close. Weekends and U.S. market holidays advance automatically to the next actual trading session.

This is a measurement and calibration loop, not a guarantee of high accuracy. Use the accumulated outcomes in `predictions.jsonl` to evaluate performance by probability and confidence bucket before changing the input parameters.

## License

MIT. See [LICENSE](LICENSE).
