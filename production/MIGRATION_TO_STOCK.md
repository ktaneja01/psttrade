# Migration to stock pysystemtrade — retire custom scripts, run Carver's daily loop

**Goal:** operationalise the live book on Carver's shipped `sysproduction`
pipeline with as close to **zero custom scripts** as possible. Everything the
book does is already implemented in pysystemtrade — the custom `production/live/`
scripts are re-implementations that predate our understanding of the shipped
pipeline. This doc is the ordered plan to delete them.

> Status: **plan only** — nothing here is executed yet. Each phase has an
> explicit verification gate and a rollback.

---

## 0. The key finding that makes this cheap

Every System stage in `signals.py:742` is **already a shipped pysystemtrade
class** — there is no custom modelling code:

| Stage (`signals.py`) | Ships in |
|---|---|
| `accountForOptimisedStage`, `optimisedPositions` | `systems.provided.dynamic_small_system_optimise` |
| `myFuturesRawData` | `systems.provided.rob_system.rawdata` |
| `volAttenForecastScaleCap` | `systems.provided.attenuate_vol` |
| `Portfolios`, `PositionSizing`, `ForecastCombine`, `Rules` | core `systems.*` |

The **only** genuinely custom class is `optimisedPositionsCapped`
(`signals.py:39`) and it is **dead** — the build at `signals.py:745` uses stock
`optimisedPositions()`; the 0.8 cap never runs (confirmed in the
`oos-and-structural-findings` memory: "no position caps active").

Therefore `signals.py` reduces to two things, neither of which belongs in
production:
1. an **imperative config builder** (mutates a shipped YAML in Python) — replace
   with a **declarative YAML** that the stock runner loads;
2. a **backtest run/print harness** — keep for research, delete from the live path.

The stock production runner `runSystemCarryTrendDynamic`
(`sysproduction/strategy_code/run_dynamic_optimised_system.py:22`) already builds
`futures_system(data, Config(filename))` with a stage list that differs from ours
only in using plain `RawData()`/`ForecastScaleCap()` where we use
`myFuturesRawData()`/`volAttenForecastScaleCap()`. So the entire custom surface
collapses to **one YAML + one ~15-line subclass**.

---

## 1. Redundancy map — custom → stock

| Custom (`production/live/`) | What it does | Stock replacement | Action |
|---|---|---|---|
| `01_fetch_ibkr.py` | IB per-contract fetch via `dataBroker` | `update_historical_prices` (same `dataBroker`) | **Retire** |
| `02_curate_rolladjusted.py` | roll cal + multiple/adjusted build | `update_multiple_adjusted_prices` + `interactive_update_roll_status` | **Retire** |
| `03_append_ib.py` (220 ln) | fetch + append + rebuild | `run_daily_price_updates` | **Retire** — rationale *disproven*, stock byte-stable (Δ=0.00, `custom-append-vs-stock-pipeline` memory) |
| `signals.py` (config half) | Python config mutation | **YAML backtest config** | **Convert** |
| `signals.py` (run/print half) | backtest harness | `update_system_backtests` | **Retire from prod** (keep for research) |
| `optimisedPositionsCapped` | inert 0.8 cap | — | **Delete** (dead) |
| `03_roll_audit.py`, `04_data_quality_gate.py` | QA gates | none | **Keep** — legit guardrails |
| `00_barchart_base.py`, `05_build_scoped.py` | one-time vendor seed | none | **Keep**, demote to research/seed-only |

**End state:** `production/live/` = 1 YAML + 1 shim + 2 QA scripts (down from ~7
scripts / ~900 lines). Daily cadence = stock `sysproduction` processes.

---

## Phase A — Config → declarative YAML (the linchpin)

**Why first:** nothing in the stock daily loop can run our strategy until the
config is a YAML the runner can `Config(filename)`.

### A.1 Generate the YAML mechanically (don't hand-transcribe)
`Config.save(filename)` exists (`sysdata/config/configdata.py:272` — dumps
`config.as_dict()` to YAML). Reuse the exact seam the notebook uses:
`signals.py` splits at `# Build system with dynamic optimisation`. Exec the
config half, then `config.save("private/<book>_config.yaml")`. This captures
instruments, `FROZEN_HANDCRAFT_SHRUNK_WEIGHTS`, forecast weights,
`FROZEN_SCALARS` (per-rule in `trading_rules`), 28 rules, `percentage_vol_target:
25.0`, `notional_trading_capital`, `use_*_estimates: False`, `use_attenuation`,
dyn-opt knobs, and `forecast_post_ceiling_cost_SR`.

**Watch-items when reviewing the dumped YAML:**
- `notional_trading_capital` is env-driven (`CAPITAL`, `signals.py:361`). In
  production, capital comes from `update_strategy_capital`; drop the hard-coded
  value or set it as the sim default only.
- Trading-rule functions must serialize as import paths (they do — rules are
  registered by dotted string), not as live function objects.
- `start_date: 2018-01-01` and `instrument_div_multiplier: 2.5` carry over verbatim.

### A.2 The one unavoidable shim
Stock `dynamic_system()` builds with `RawData()` + `ForecastScaleCap()`. We need
`myFuturesRawData()` + `volAttenForecastScaleCap()`. Subclass and override the
builder only (~15 lines), living in `sysproduction/strategy_code/` (or a private
module):

```python
class runSystemBookDynamic(runSystemCarryTrendDynamic):
    def system_method(self, notional_trading_capital=arg_not_supplied,
                      base_currency=arg_not_supplied):
        # identical to dynamic_system() but swap RawData->myFuturesRawData
        # and ForecastScaleCap->volAttenForecastScaleCap in the stage list
        ...
```

Alternative to check first: if stock `ForecastScaleCap` honours
`config.use_attenuation` natively, the shim disappears entirely and we point
straight at stock `runSystemCarryTrendDynamic`. **Verify before writing the shim.**

### A.3 Verification gate (equivalence)
Load the YAML through the shim and confirm it reproduces `signals.py`:
- same `system.get_instrument_list()`;
- same latest forecasts per (rule, instrument) — cross-check `forecast_matrix.py`;
- **same optimal integer positions** on a fixed as-of date (the number that
  actually trades). Tolerance: exact for positions; forecasts to ~1e-6.

**Rollback:** none needed — additive; `signals.py` untouched until the gate passes.

---

## Phase B — Retire the data scripts for `run_daily_price_updates`

**Why safe:** the `custom-append-vs-stock-pipeline` memory already proved stock
`run_daily_price_updates` (`update_historical_prices` → per-contract
append-with-merge + spike check; `update_multiple_adjusted_prices` → incremental
rebuild) is **byte-stable**: max|Δ| 2019-2025 adjusted = 0.00, tail-append
correct. `01_fetch/02_curate/03_append` reinvent it.

### B.1 Genuinely-still-needed (do NOT delete)
1. **Store isolation** — point `parquet_store` at the live store. (Currently
   `/tmp/curate_work` dry-run in `private/private_config.yaml` — repoint to the
   real `/usr/local/bc_data` when promoting.)
2. **One-time vendor seed → IB cycle-month alignment** — the seed step only,
   from `00_barchart_base.py`/`05_build_scoped.py` (research/seed only).
3. **Roll management** — stock does NOT auto-roll in the price update. It needs
   `update_sampled_contracts` + `interactive_update_roll_status` + auto-roll.
   The custom from-scratch roll-calendar rebuild was standing in for this.

### B.2 Steps
1. On a **copy** of the live store, run `update_historical_prices` +
   `update_multiple_adjusted_prices` for the full universe.
2. Diff adjusted prices vs the current custom-built store: expect max|Δ| 2019–2025
   = 0.00 and a correct tail extension (re-confirm the memory's result on today's
   store, not just the earlier sample).
3. Wire `update_sampled_contracts` + `interactive_update_roll_status` for rolls.
   (Import `rollingAdjustedAndMultiplePrices` directly if
   `interactive_update_roll_status` hits the scipy/statsmodels `_lazywhere`
   mismatch — see `ib-data-pipeline` memory.)
4. Delete `01_fetch_ibkr.py`, `02_curate_rolladjusted.py`, `03_append_ib.py`.

### B.3 Verification gate
Byte-stability diff passes (Δ=0.00 on frozen history) **and** a manual roll via
`interactive_update_roll_status` produces a correct panama shift (validate in
engine space with `roll_audit.py`, never `pct_change` the level — `roll-audit-and-stalls` memory).

**Rollback:** keep the custom scripts + a store snapshot (`~/bc_data_backups/`)
until two consecutive daily cycles reconcile clean; restore snapshot + scripts if not.

---

## Phase C — Wire the stock daily loop

All shipped; no new code. Config lives in `private_config.yaml` (strategy) and
`private_control_config.yaml` (process schedule).

### C.1 Strategy registration (`private_config.yaml`)
```yaml
strategy_list:
  <book>:
    load_backtests:
      object: <module>.runSystemBookDynamic   # or stock runSystemCarryTrendDynamic if no shim
      function: system_method
    reporting_code:
      function: sysproduction.strategy_code.report_system_dynamic.report_system_dynamic

strategy_capital_allocation:
  function: sysproduction.strategy_code.strategy_allocation.weighted_strategy_allocation
  strategy_weights:
    <book>: 100.0
```

### C.2 Process schedule (`private_control_config.yaml`)
```yaml
process_configuration_methods:
  run_systems:
    <book>:
      max_executions: 1
      object: <module>.runSystemBookDynamic
      backtest_config_filename: private.<book>_config.yaml
  run_strategy_order_generator:
    <book>:
      object: sysexecution.strategies.dynamic_optimised_positions.orderGeneratorForDynamicPositions
      max_executions: 1
```
(`orderGeneratorForDynamicPositions` — `sysexecution/strategies/dynamic_optimised_positions.py:64`
— is the dynamic-opt equivalent of the classic buffered generator.)

### C.3 Daily cadence (all stock `run_*`)
`run_daily_fx_and_contract_updates` → `run_daily_price_updates` → `run_systems`
(→ our YAML) → `run_strategy_order_generator` → `run_stack_handler` (order stack →
IB fills) → `run_capital_update` → `run_reports`; `run_cleaners`/`run_backups`
housekeeping. Rolls via `interactive_update_roll_status` (as-needed, near expiry).

### C.4 Verification gate
Each process runs green individually against the paper account (4002, DUR997745)
before chaining; `run_reports` status + reconcile reports clean.

---

## Phase D — Paper-trade the full loop (~1 month)

Run the whole cron cadence on IB paper. Watch daily reconcile (positions/P&L vs
IB), roll events, and the strategy report. Only then promote to live capital.

**Pre-flight blockers to clear first (from memory, unchanged):**
- Stale trade-cost config (`spreadcosts.csv` undated; GBPJPY per_block=359;
  GILT/TECDAX/ZINC=0) — re-sample from broker (`cost-config-needs-refresh`).
- Prune universe to IB-tradeable contracts (LME/EUA/iBoxx may not fill).
- Keep `roll_audit.py` + `data_quality_gate.py` as pre-flight checks on rebuilt data.

---

## Deletion checklist (only after the gate above each is green)

- [x] `production/live/03_append_ib.py` — retired 2026-09-24 (backup `/tmp/retired_live_scripts_2026-09-24/`)
- [x] `production/live/02_curate_rolladjusted.py` — retired 2026-09-24
- [x] `production/live/01_fetch_ibkr.py` — retired 2026-09-24
- [ ] `optimisedPositionsCapped` + `MAX_POSITION_FRAC` block in `signals.py` (dead)
- [ ] `signals.py` run/print harness — factor config into the YAML; keep a thin
      research runner that loads the same YAML (single source of truth)

---

## Daily IBKR data update (post-migration) — the exact process

Three stock processes, in order (crontab or `run_backups`-style scheduler; IB
Gateway + MongoDB must be up). No custom scripts.

```bash
python -m sysproduction.run_daily_fx_and_contract_updates      # 1. FX + roll sampling
python -m sysproduction.run_daily_price_updates                # 2. per-contract prices
python -m sysproduction.run_daily_update_multiple_adjusted_prices  # 3. rebuild multiple+adjusted
```

Then the strategy/execution loop consumes it: `run_systems` →
`run_strategy_order_generator` → `run_stack_handler`. Rolls are **not** daily —
run `interactive_update_roll_status` only when a contract nears expiry.

### What each does under the covers

1. **`run_daily_fx_and_contract_updates`** = `update_fx_prices` +
   `update_sampled_contracts`.
   - *FX:* pulls spot FX from IB, appends to the FX store (base-ccy conversion for P&L/capital).
   - *Sampled contracts:* for each instrument, asks IB which contracts exist,
     and marks the set we should be pricing (the sampling universe around the
     current roll cycle). This is what tells step 2 *which* contracts to fetch —
     no roll calendars are rebuilt from scratch.

2. **`run_daily_price_updates`** = `update_historical_prices`. For every sampled
   contract, pulls recent daily (and intraday) bars from IB and **appends with
   merge**: keeps stored history, adds only rows after each contract's last
   stored date, runs an >8σ spike check (flags, doesn't silently overwrite). This
   is the incremental, byte-stable path that replaces `03_append_ib.py` — history
   is never re-derived.

3. **`run_daily_update_multiple_adjusted_prices`** = `update_multiple_adjusted_prices`.
   Extends the **multiple prices** (PRICE/FORWARD/CARRY contract columns) with the
   new rows on the *current* contracts, then extends the **panama-adjusted** series
   using `update_with_multiple_prices_no_roll` — pure tail-append, **no re-splice**
   (it raises if a roll happened without being registered, rather than silently
   shifting history). The adjusted series is what the backtest/system reads.

**Net:** IB → per-contract prices (append-only) → multiple → adjusted, extending
the tail each day, leaving all historical rows byte-identical. A roll only ever
happens as a discrete, explicit `interactive_update_roll_status` action — never
inside the daily price job.

---

Related memory: `custom-append-vs-stock-pipeline`, `productionise-pysystemtrade`,
`ib-data-pipeline`, `live-store-seed-staleness`, `roll-audit-and-stalls`,
`oos-and-structural-findings`.
