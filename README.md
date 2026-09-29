# JEV Nasdaq daily prediction

This repository contains a TypeSafe Jev runner for Nasdaq direction research. The current daily 20:00 (`Asia/Shanghai`) schedule is a local Codex automation managed outside this repository. A clone of this repository contains the runner and configuration, but does not automatically create a scheduler.

At each run the script fetches the latest daily Nasdaq Composite (`^IXIC`) history plus S&P 500, Nasdaq futures, VIX, dollar, WTI, Brent, gold, official Treasury nominal/real yields, and the latest BLS CPI and labor observations. It asks Jev whether the next available US regular trading session will close up or down versus the latest available close, and saves the complete request and response under `runs/`.

## One-time setup

Set the TypeSafe API key in the macOS Keychain used by the local automation:

```bash
security add-generic-password -U -a "$USER" -s typesafe-api-key -w 'your-typesafe-api-key'
```

The script first checks `TYPESAFE_API_KEY`, then reads the Keychain item. The key is read at runtime and is never written to the request or result files. The automation runs `python3 jev_nasdaq_predictor.py` from this directory. Run a local dry check with:

```bash
python3 jev_nasdaq_predictor.py --dry-run
```

For a non-macOS environment, provide `TYPESAFE_API_KEY` through the process environment. Never commit a real key, `.env` file, or generated `runs/` output.

## Stored data

- `runs/<run-id>/jev_request.json`: the exact JSON sent to Jev, including the state, model, question, and criteria.
- `runs/<run-id>/jev_response.json`: Jev's raw response, including probabilities, confidence, model version, and token usage.
- `runs/<run-id>/run_metadata.json`: timestamps, baseline session, and run status.
- `runs/predictions.jsonl`: one compact row per successful prediction. Future runs backfill `actual_session`, `actual_direction`, and `correct` when the next market close is available. `input_schema_version`, `expanded_data_status`, and `usable_for_accuracy` distinguish the original price-only baseline from the expanded-input runs.

The expanded request state records the source, observation date, retrieval time, and missing-data status for each cross-asset, Treasury, and BLS section. The BLS API can revise historical observations; the saved `jev_request.json` is the authoritative record of exactly what Jev saw for that run. Treasury daily curves may lag the 20:00 Beijing cutoff because they are published from New York market-day observations.

For a real run, the script refuses to call Jev if any expanded section is incomplete. It saves the request and an `error.json` so a missing source cannot silently turn into a prediction based on the old, smaller input.

The model is pinned to `jev-1.13.0` in `jev_input_config.json` so later model releases do not silently change the calibration target. Adjusting the question, criteria, lookback, or recent points in that file changes the next request and leaves prior requests untouched.

This is a measurement loop, not a guarantee of high accuracy. Use `predictions.jsonl` to evaluate accuracy by probability/confidence bucket before changing the input configuration.
