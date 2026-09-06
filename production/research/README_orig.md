# production/backtest — reproducible 2018-2025 backtest pipeline

End-to-end reproducible pipeline: raw vendor downloads → curated roll-adjusted
series → handcraft weights + forecast scalars → backtest. Every stage is
deterministic (same inputs → same outputs). Vendor-only (Barchart + Databento),
**no IBKR** — the IBKR-append surgery is kept out of the backtest baseline.

## Layout
```
config.json                      # source of truth: universe (80), window, per-instrument vendor plan, loader
data/raw/<INST>/                 # captured raw hourly contract CSVs (tz-stripped), by instrument
data/curated_rolladjusted/       # curated per-contract + multiple + adjusted (the backtest store)
roll_calendars/                  # generated roll calendars
artifacts/                       # handcraft_weights.txt, forecast_scalars.txt, backtest_results.json, curate_report.json
01_stage_raw.py                  # vendor CSVs -> data/raw (per config vendor_plan)
02_curate_rolladjusted.py        # data/raw -> curated store (Carver's shipped roll+panama chain)
03_roll_audit.py                 # roll & back-adjustment audit on curated store
04_data_quality_gate.py          # data-quality gate on curated store
05_freeze_handcraft.py           # handcraft weights from curated store -> artifact
06_freeze_scalars.py             # forecast scalars from curated store -> artifact
07_run_backtest.py               # backtest using curated store + both artifacts
```

## Run order
```
pst-env/bin/python3 production/backtest/01_stage_raw.py
pst-env/bin/python3 production/backtest/02_curate_rolladjusted.py
pst-env/bin/python3 production/backtest/03_roll_audit.py          # must PASS (see caveats)
pst-env/bin/python3 production/backtest/04_data_quality_gate.py   # review flags
pst-env/bin/python3 production/backtest/05_freeze_handcraft.py
pst-env/bin/python3 production/backtest/06_freeze_scalars.py
pst-env/bin/python3 production/backtest/07_run_backtest.py        # 250K + 500K
```

## Validated result (2018-2025 store, 2019-2025 P&L window, reproducible artifacts)
- **$250K: SR 0.46**, +53.6% total
- **$500K: SR 0.637**, +75.3% total
- Deterministic: re-running 07 reproduces the SR exactly.
- 02 produces adjusted series **byte-identical** to the manually-built /tmp/bc_2018 store.

(Note: an earlier ad-hoc run using the *original* non-reproducible scalars scored
250K 0.474 / 500K 0.602. Stage 07 uses the **reproducible** 2018-fit scalars from
stage 06, which scale carry ~20% higher; hence the small SR difference. The
reproducible artifacts are the canonical set.)

## THE critical gotcha (dot-in-path)
The repo lives under `/Users/kunal.taneja/...`. pysystemtrade resolves parquet
`datapaths` as **package paths**, turning the `.` in `kunal.taneja` into `/`
→ `/Users/kunal/taneja/...` → silent 0-files or "Permission denied". Every stage
handles this:
- 01/02 stage raw + build into DOT-FREE `/tmp/...` work dirs, then copy into the repo.
- 02 builds roll calendars into `/tmp/rc_work` (the calendar writer also mangles dots).
- 03/06/07 point the parquet resolver at a DOT-FREE symlink `/tmp/curated_store`
  → the repo curated store. Direct `pd.read_parquet` (04, 05) is unaffected.

## Known caveats (documented, low-materiality)
- **PLN dropped** — no raw vendor source. 79/80 audited; PLN errors cleanly.
- **CORN 2021-12 annual roll** (hold cycle "Z", Dec-only) flags a ~14% self-reversing
  3-day blip: new-crop/old-crop spread on a thin-overlap roll. Nets ~0 over the week;
  low weight. This is the single roll_audit "bug" flag.
- **ETHER-micro** trips the data-quality move threshold (38% on 2021-05-19) — real
  crypto crash, not corruption.
- **roll_audit "REAL volatile rolls"** (2020-03 COVID equity complex, BTP 2018-05,
  COCOA 2024-05) are real market moves, reported informationally, not failures.

## Reproducing / refreshing scalars & weights
`freeze_scalars` uses Carver's SHIPPED pooled estimator (target_abs=10, all-data
window, min_periods=500, backfill). `freeze_handcraft` uses handcraft_optimisation
(equalise_SR/vols, 50%-toward-average correlation shrink, 5% cap). Both read the
curated store and are byte-reproducible. To adopt in signals.py, paste the two
artifact dicts.
