# IBKR production data pipeline — plan

Goal: replace the research-era Databento/bc-utils fetch with IBKR as the **production
data source**, so the data you TRADE on is the same venue you EXECUTE on (no vendor/
broker mismatch). `ib_insync` 0.9.86 is already installed in pst-env.

## Why IBKR for production data
- **Data = execution venue.** Backtest/live prices come from the same source you
  trade — eliminates the reconciliation gap between a data vendor and IB fills.
- **Covers your whole tradeable universe** — anything IB can route, IB can serve bars.
- **Free** with the account (+ ~$10-30/mo exchange market-data subscriptions).
- Native on macOS/Linux via IB Gateway (headless) — no Windows appliance (unlike Norgate).

## Known IBKR limitation (design around it)
- **Historical depth is shallow.** `reqHistoricalData` caps intraday history (often
  ~1-2yr for hourly, sometimes months for some venues) and daily depth varies.
- **Therefore: HYBRID.** Keep the deep backtest history from the existing parquet
  store (Databento/bc-utils, 2018-2026 seed). Use IBKR only to **append recent + live
  daily bars going forward.** IB owns "today onward"; the frozen seed owns the past.

## Architecture (mirrors the proven rebuild chain)
```
IB Gateway (headless, paper first)
   └─ ibkr_fetch.py  (reqHistoricalData per front contract, daily bars)
        └─ writes Hour_/Day_ CSVs to a dot-free stage dir (same shape as bc-utils)
             └─ existing chain: init_db → derive daily → roll calendar
                → multiple_prices → adjusted_prices  (append mode, not full rebuild)
                  └─ data_quality_gate.py  (QA before it feeds the live system)
                       └─ signals.py reads the parquet store  → dyn-opt target positions
```

## Build steps
1. **Contract map**: pysystemtrade instrument code → IB contract (symbol, exchange,
   secType=FUT, currency, multiplier). Most already in `instrumentconfig.csv`
   (Currency/Pointsize/Region) — extend with IB exchange + symbol per instrument.
2. **ibkr_fetch.py** (skeleton in this folder): connect IB Gateway → for each
   instrument resolve the current front contract → `reqHistoricalData` daily bars →
   write CSV in loader shape (Time,Open,High,Low,Final,Volume).
3. **Roll handling**: IB gives per-contract bars; reuse `build_and_write_roll_calendar`
   or IB's continuous. Verify carry column (near+far) is buildable — CARRY rules need it.
4. **Append, don't rebuild**: only fetch bars since the store's last date; append.
5. **QA gate** every run before it feeds live.
6. **Verify vs seed**: spot-check IB bars align with the Databento/bc-utils history at
   the seam (no level jump from adjustment-method mismatch).

## De-risk FIRST (30 min, before building)
Confirm IB Gateway returns daily bars for a few of YOUR instruments — especially the
non-US ones (EUREX sectors, LME metals, HKEX). If IB can't serve historical bars for
some, those need the frozen-seed fallback or a data gap. Run `ibkr_fetch.py --probe`.

## Paper-trade gate
Run the FULL loop (fetch → rebuild → dyn-opt → order-gen → IB paper fills →
reconcile) on an IB **paper account** for ~1 month before any live capital.

## Contract-map resolution status (2026-08 probe)
- **66/74 validated** against IB Gateway (paper). All show SHALLOW history
  (6-24 months) — confirms hybrid design (IB=recent+live, parquet seed=deep history).
- **8 still need TWS GUI lookup** (scripted search hit symbol-collisions + rate limits):
  - VERIFY (loose match, likely wrong exchange): CHF (should be 6S/CME not SF/NYBOT),
    IRON (TIO/COMEX?), CANOLA (RS — ICE Canada not NYBOT).
  - NOT FOUND: BRE (Brazilian real), ZINC_LME, MSCISING, US-REALESTATE, EUROSTX-SMALL.
  - Fix by typing each symbol into TWS contract search, read localSymbol+exchange.
  - Reusable resolver: /tmp/ib_resolve*.py (wait ~10min between runs for rate limit).

## FINAL contract-map status (after fuzzy-search resolve)
- **71/74 validated with IB data.** Resolved via reqMatchingSymbols name search:
  BRE(BRE/CME), MSCISING(SSG/SGX), EUROSTX-SMALL(DJESS/EUREX), IRON(TIO/COMEX),
  CANOLA(RS/NYBOT).
- **3 remaining:**
  - CHF (6S/CME) — throttle artifact; franc future DEFINITELY exists, retry clean.
  - ZINC_LME — set to LZ/NYMEX (COMEX London zinc); verify. Else frozen-seed.
  - US-REALESTATE — appears INDEX-ONLY on IB (S5RLST/SIXRE not tradeable FUT).
    Likely genuine gap -> frozen-seed fallback (low weight, fine).

## Last-2 resolution (final)
- CHF: SET to 6S/CME (standard CME Swiss Franc). Scripted probes throttled / hit the
  SFR=SOFR collision; 6S is the known-correct symbol — confirm in TWS (10 sec).
- ZINC_LME: NOT resolvable via reqContractDetails(Future) — LME metals have non-standard
  (forward-dated/continuous) contract structure on IB. Options: (a) special LME handling
  in fetch, or (b) frozen-seed fallback. Low weight -> (b) is fine for now.
- US-REALESTATE: index-only on IB -> frozen-seed fallback.
FINAL: 72/74 mappable to IB (CHF pending TWS confirm); ZINC_LME + US-REALESTATE on seed.

## HONEST FINAL validated count (2026-08, after ~11 probe passes)
- **68/74 CONFIRMED with data** (OK + bars in a probe log).
- **4 THROTTLE false-negatives (NOT gaps): NZD(6N), ZAR(6Z), CHF(6S), ROBUSTA(RC).**
  These are highly-liquid contracts that resolved EARLIER this session; failing now
  ONLY because the IB Gateway API is throttled from ~11 heavy reqContractDetails runs.
  -> Settle via TWS contract-search (30s) OR restart Gateway then one clean probe.
  DO NOT keep scripted-probing — it deepens the throttle and returns false negatives.
- **2 genuine seed-fallbacks: ZINC_LME (LME non-standard structure), US-REALESTATE
  (index-only on IB, no tradeable FUT).**
- Realistic reachable-on-IB total once throttle clears: 72/74. 2 on frozen seed.

## RESOLVED after Gateway restart (2026-08) — root-cause was WRONG SYMBOLS, not throttle
- CME FX use the CURRENCY NAME as symbol (localSymbol is the 6X code). FIXED:
  CHF->CHF/CME, NZD->NZD/CME, ZAR->ZAR/CME, JPY->JPY/CME, MXP->MXP/CME, BRE->BRE/CME.
- ROBUSTA -> D/ICEEUSOFT (localSymbol RCU6), confirmed 64 bars.
- REMAINING gaps (frozen-seed): ZINC_LME (LME structure), US-REALESTATE (index-only).
- **FINAL: 72/74 mappable+confirmed on IB; 2 on frozen seed.**
