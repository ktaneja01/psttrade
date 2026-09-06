# production/

Scripts on the path to live trading. Run from repo root (`cd ~/pysystemtrade`)
or directly — production scripts resolve `../signals.py` via `__file__`, so they
work from any cwd.

## Current contents (validated)

- **`handcraft_topology_map.py`** — regenerates the frozen instrument weights by
  running Carver's real `handcraft_optimisation` (auto binary-split correlation
  clustering, 50% corr shrink) on the live universe. Writes `/tmp/dict_handcraft.txt`
  (paste into `signals.py` FROZEN_HANDCRAFT_SHRUNK_WEIGHTS). Run monthly/quarterly
  to refresh weights. THIS is the chosen allocation method (beats hand-drawn trees).
- **`data_quality_gate.py`** — QA gate: contract-span / no-200X / per-instrument
  move thresholds / cross-instrument correlation sanity. Run before any rebuilt
  data feeds the live system.

## The config
- **`../signals.py`** stays at repo root — the canonical strategy config (74
  instruments, handcraft weights, Carver trend rules [drop accel + momentum/normmom/
  assettrend], 50/40/10, 25% vol, dyn-opt). Both research and production import it.
  TODO: refactor to separate the CONFIG object from the backtest run-code so the
  production runner imports config cleanly.

## PATH TO PRODUCTION — open work (none built yet)

See `ibkr_pipeline/` for the IBKR data-source plan. Beyond data, production needs
(pysystemtrade ships most of this in `sysproduction/` — wire in, don't rebuild):
1. **MongoDB** — production state store (positions/orders/fills). Currently backtest-only.
2. **IB Gateway + ib_insync** — execution + live price/position feed.
3. **Dyn-opt production runner** — scheduled: pull prices → run system → target
   optimised positions → diff vs IB positions → generate orders.
4. **Roll management** — automated contract rolling near expiry.
5. **Reconciliation + monitoring/alerting** — positions/P&L vs IB.
6. **Paper-trade first** — full loop on IB paper account ~1 month before live capital.
