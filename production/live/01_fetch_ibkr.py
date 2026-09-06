"""Stage 1 (IBKR) — fetch per-contract daily bars from IB Gateway into data/raw/.

Uses the SHIPPED sysproduction dataBroker (sysbrokers/IB) — the same path production
uses. For each instrument: resolve its live contract chain, pull daily bars per
contract, write a raw CSV per contract into data/raw/<INST>/, named
Hour_<INST>_<YYYYMM>00.csv (the roll-cycle month convention, NOT IB's expiry-day
date — this pre-empts the 20260918-vs-20260900 collision so the curate/roll chain
matches the backtest pipeline). File shape matches the vendor loader:
Time,Open,High,Low,Latest,Volume with ISO timestamps (no tz suffix).

Only bars >= fetch_start are kept. Per-instrument try/except; resumable.

Run:  pst-env/bin/python3 production/live/01_fetch_ibkr.py [INST ...]
"""
import os, io, contextlib, json, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
RAW = os.path.join(HERE, "data", "raw")
os.makedirs(RAW, exist_ok=True)
FETCH_START = pd.Timestamp(CFG["window"]["fetch_start"])
ONLY = sys.argv[1:]

from sysdata.data_blob import dataBlob
from sysproduction.data.broker import dataBroker
from sysobjects.contracts import futuresContract
from syscore.dateutils import DAILY_PRICE_FREQ

data = dataBlob()
broker = dataBroker(data)
universe = ONLY or CFG["universe"]
done = 0; total_files = 0; failed = []

# ---------------------------------------------------------------------------
# IB expiry-date -> true cycle month (contractMonth) map.
#
# The shipped broker_get_futures_contract_list returns each contract's
# lastTradeDateOrContractMonth (the EXPIRY date). For instruments whose
# contracts stop trading the month BEFORE their delivery/cycle month
# (SUGAR11, PLAT, SILVER-mini, PALLAD, JPY, MXP, ZAR, EUA ...) truncating the
# expiry to YYYYMM mislabels the file (Oct contract, expiry 20260930, would be
# filed as 202609 -> collides / breaks the roll stitch against the Barchart
# seed which is keyed by the cycle LETTER).
#
# IB's reqContractDetails exposes `contractMonth` = the true YYYYMM cycle month
# (SBV6 -> 202610), exactly what bc-utils derives from the cycle letter. We
# build {expiryYYYYMMDD -> YYYYMM00} per instrument and label raw files by it.
# ---------------------------------------------------------------------------
_MONTH_LETTER = {1:"F",2:"G",3:"H",4:"J",5:"K",6:"M",7:"N",8:"Q",9:"U",10:"V",11:"X",12:"Z"}

def _roll_cycle_months(inst):
    """Set of month-numbers in the instrument's PricedRollCycle (empty if unknown)."""
    try:
        import pandas as pd
        rc = pd.read_csv("data/futures/csvconfig/rollconfig.csv").set_index("Instrument")
        cyc = str(rc.loc[inst, "PricedRollCycle"])
        inv = {v: k for k, v in _MONTH_LETTER.items()}
        return set(inv[c] for c in cyc if c in inv)
    except Exception:
        return set()

def build_contract_month_map(inst):
    """Return {expiry 'YYYYMMDD' -> cycle-month 'YYYYMM00'} from IB contractMonth,
    keeping ONLY contracts whose contractMonth is in the instrument's roll cycle.

    IB lists serial (monthly) contracts alongside cycle contracts for some
    instruments (PLAT/PALLAD/JPY/MXP/ZAR/EUA). Those serials' contractMonth is
    off-cycle (e.g. Nov for an FJNV instrument) and must be dropped — the roll
    calendar only stitches cycle months, and the Barchart seed only has them."""
    try:
        from ib_insync import Future
        cmap = CFG["ib_contract_map"][inst]
        cur = cmap.get("currency")
        # config currency can be None or the string "nan"/"NA" (shipped CSV uses NA);
        # omit it and let IB resolve, matching how the main fetch resolves contracts.
        kw = {"symbol": cmap["symbol"], "exchange": cmap["exchange"]}
        if cur and str(cur).lower() not in ("nan", "na", "none", ""):
            kw["currency"] = str(cur)
        ibfut = Future(**kw)
        ib = broker.data.ib_conn.ib  # shipped ib_insync connection
        details = ib.reqContractDetails(ibfut)
        cycle_months = _roll_cycle_months(inst)
        out = {}
        for cd in details:
            exp = str(cd.contract.lastTradeDateOrContractMonth)[:8]
            cm = str(getattr(cd, "contractMonth", "") or "")[:6]
            if len(exp) != 8 or len(cm) != 6:
                continue
            if cycle_months and int(cm[4:6]) not in cycle_months:
                continue  # drop off-cycle serial contract
            out[exp] = cm + "00"
        return out
    except Exception as e:
        print(f"  {inst:15s} WARN contractMonth map unavailable ({str(e)[:40]}); "
              f"falling back to expiry-month")
        return {}

for inst in universe:
    try:
        dest = os.path.join(RAW, inst)
        os.makedirs(dest, exist_ok=True)
        import datetime
        fwd_limit = (datetime.date.today() + datetime.timedelta(days=270)).strftime("%Y%m%d")
        dates = sorted(d for d in
                       (str(x).strip()[:8] for x in
                        broker.get_list_of_contract_dates_for_instrument_code(inst, allow_expired=False))
                       if d <= fwd_limit)
        cm_map = build_contract_month_map(inst)     # {expiry YYYYMMDD -> cycle YYYYMM00}
        n = 0
        for raw_date in dates:
            ymd = raw_date                          # IB expiry day (already YYYYMMDD)
            # Label by the TRUE cycle month (IB contractMonth), not the expiry month.
            if cm_map:
                if ymd not in cm_map:
                    continue                        # off-cycle serial contract -> skip
                month_id = cm_map[ymd]
            else:
                month_id = ymd[:6] + "00"           # map unavailable -> expiry-month fallback
            fc = futuresContract(inst, ymd)         # fetch by the real IB contract
            try:
                px = broker.get_prices_at_frequency_for_contract_object(fc, DAILY_PRICE_FREQ)
                df = px.return_final_prices() if hasattr(px, "return_final_prices") else px
            except Exception:
                continue
            df = (df if isinstance(df, pd.Series) else df.iloc[:, 0]).dropna()
            df.index = pd.to_datetime(df.index)
            df = df[df.index >= FETCH_START]
            if len(df) < 2:
                continue
            # write in vendor-loader shape, keyed by MONTH id (dedupe/merge if the file exists)
            out = os.path.join(dest, f"Hour_{inst}_{month_id[:6]}00.csv")
            rows = pd.DataFrame({
                "Time": df.index.strftime("%Y-%m-%dT%H:%M:%S"),
                "Open": df.values, "High": df.values, "Low": df.values,
                "Latest": df.values, "Volume": 1})
            if os.path.exists(out):
                prev = pd.read_csv(out)
                rows = pd.concat([prev, rows]).drop_duplicates("Time").sort_values("Time")
            rows.to_csv(out, index=False)
            n += 1
        if n == 0:
            failed.append(inst)
        else:
            done += 1; total_files += n
        print(f"  {inst:15s} {n} contracts")
    except Exception as e:
        failed.append(inst); print(f"  {inst:15s} ERR {str(e)[:60]}")

data.close()
print(f"\nFETCHED {done}/{len(universe)} instruments, {total_files} contract files -> {RAW}")
if failed:
    print("FAILED/empty:", failed)
