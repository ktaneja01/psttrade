"""
Download 10 years of hourly OHLCV from Databento for 65 CME-available futures.

Writes one CSV per contract expiration to `data/databento/hourly/` in the same
format as bc-utils so the existing `load_bcutils_hourly.py` can consume it.

Prerequisites:
    pip install databento
    export DATABENTO_API_KEY="db-..."

Usage:
    python download_databento.py
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import databento as db
except ImportError:
    print("ERROR: databento SDK not installed. Run: pip install databento", file=sys.stderr)
    sys.exit(1)


# ============================================================
# Config
# ============================================================
PYSYSTEMTRADE_ROOT = Path("/Users/kunal.taneja/pysystemtrade")
OUTDIR = PYSYSTEMTRADE_ROOT / "data" / "databento" / "hourly"
ROLLCONFIG_PATH = PYSYSTEMTRADE_ROOT / "data" / "futures" / "csvconfig" / "rollconfig.csv"

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1h"
START_DATE = "2015-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# Map pysystemtrade instrument code -> Databento root symbol (CME ticker).
# All 65 instruments have rollconfig / instrumentconfig / spreadcosts entries
# in pysystemtrade already (verified via direct grep).
INSTRUMENTS = {
    # ---- Equity (6) ----
    "SP500":    "ES",
    "NASDAQ":   "NQ",
    "RUSSELL":  "RTY",
    "DOW":      "YM",
    "NIKKEI":   "NKD",
    "SP400":    "EMD",
    # ---- Rates (10) ----
    "US2":      "ZT",
    "US3":      "Z3N",
    "US5":      "ZF",
    "US10":     "ZN",
    "US10U":    "TN",
    "US20":     "ZB",        # classic 30Y T-Bond (renamed 20Y by CME)
    "US30":     "UB",        # Ultra Bond
    "SOFR":     "SR3",
    "SOFR1":    "SR1",
    "FED":      "ZQ",
    # ---- FX (15) ----
    "EUR":      "6E",
    "JPY":      "6J",
    "GBP":      "6B",
    "AUD":      "6A",
    "NZD":      "6N",
    "MXP":      "6M",
    "CHF":      "6S",
    "CAD":      "6C",
    "BRE":      "L6",
    "ZAR":      "6Z",
    "PLN":      "WP",
    "INR":      "H3",
    "CNH-CME":  "CNH",
    "EURCHF":   "RF",
    "GBPEUR":   "RP",
    # ---- Energy (9) ----
    "CRUDE_W":      "CL",
    "GAS_US":       "NG",
    "GASOILINE":    "RB",    # RBOB gasoline
    "BRENT_W":      "BZ",    # NYMEX financial Brent
    "HEATOIL":      "HO",
    "BRENT-LAST":   "BB",
    "GAS-LAST":     "HH",
    "GAS-PEN":      "HP",
    "ETHANOL":      "ZK",
    # ---- Metals (7) ----
    "GOLD":      "GC",
    "SILVER":    "SI",
    "COPPER":    "HG",
    "PLAT":      "PL",
    "PALLAD":    "PA",
    "ALUMINIUM": "ALI",
    "STEEL":     "HRC",
    # ---- Grains (7) ----
    "WHEAT":     "ZW",
    "SOYBEAN":   "ZS",
    "SOYMEAL":   "ZM",
    "SOYOIL":    "ZL",
    "RICE":      "ZR",
    "OATIES":    "ZO",
    "CORN":      "ZC",
    "REDWHEAT":  "KE",
    # ---- Livestock / Dairy (6) ----
    "LEANHOG":   "HE",
    "LIVECOW":   "LE",
    "FEEDCOW":   "GF",
    "MILK":      "DC",
    "CHEESE":    "CSC",
    "BUTTER":    "CB",
    # ---- Crypto (3) ----
    "BITCOIN":   "BTC",
    "ETHEREUM":  "ETH",
    "BRR":       "BRR",
    # ---- Lumber (1) ----
    "LUMBER-new":"LBR",
    # ---- CME micros / e-minis (fill-friendly at $500K capital) ----
    "SP500_micro":  "MES",   # Micro E-mini S&P 500
    "NASDAQ_micro": "MNQ",   # Micro E-mini Nasdaq-100
    "COPPER-micro": "MHG",   # Micro Copper
    "CRUDE_W_micro":"MCL",   # Micro WTI
    "ETHER-micro":  "MET",   # Micro Ether
    "GAS_US_mini":  "QG",    # E-mini Natural Gas
    "EUR_micro":    "M6E",   # Micro EUR/USD
    "AUD_micro":    "M6A",   # Micro AUD/USD
    "GBP_micro":    "M6B",   # Micro GBP/USD
    "US10Y_micro":  "10Y",   # Micro 10-Year Yield (NOTE: yield future, inverse to price)
    "SILVER-mini":  "SIL",   # 2500oz Mini Silver
    "CAD_micro":    "M6C",   # Micro CAD/USD
}

# Standard CME month code → numeric month
MONTH_CODES = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}


# ============================================================
# Helpers
# ============================================================
def load_priced_cycles() -> dict:
    """Read PricedRollCycle for each instrument from rollconfig.csv."""
    df = pd.read_csv(ROLLCONFIG_PATH)
    return dict(zip(df["Instrument"], df["PricedRollCycle"]))


def parse_contract_symbol(symbol: str, root: str) -> tuple:
    """Extract (month_letter, year_int) from a CME contract symbol.

    Examples: 'ESH25' → ('H', 2025), '6EM24' → ('M', 2024), 'ZNZ24' → ('Z', 2024).
    Returns (None, None) if unparseable (e.g. continuous symbols).
    """
    if not symbol.startswith(root):
        return None, None
    tail = symbol[len(root):]
    # Databento uses formats like "ESH5" or "ESH25" or "ESH2025". Try to parse
    # month letter at position 0, then 1-4 digit year.
    if not tail or tail[0] not in MONTH_CODES:
        return None, None
    month_letter = tail[0]
    year_str = tail[1:]
    try:
        year_int = int(year_str)
    except ValueError:
        return None, None
    # Normalise to 4-digit year.
    # SINGLE-digit years (Databento's current-era symbols, e.g. 'KEZ6' = Dec-2026)
    # are ambiguous; resolve to the current decade (2020s), NOT 200X. Using the
    # old "<70 => 2000+" rule mis-dated current contracts as 2006/2007, so recent
    # data was written to wrong-year filenames (and then treated as stale/deleted).
    if len(year_str) == 1:
        decade = (datetime.now().year // 10) * 10   # e.g. 2020
        year_int = decade + year_int                # 6 -> 2026
        if year_int < datetime.now().year - 1:      # rolled past decade boundary
            year_int += 10
    elif year_int < 100:
        # 2-digit year
        year_int += 2000 if year_int < 70 else 1900
    elif year_int < 1000:
        pass  # 3-digit (rare) — take as-is
    return month_letter, year_int


def write_contract_csv(df: pd.DataFrame, code: str, year: int, month_num: int) -> Path:
    """Write a contract's hourly data to the bc-utils-compatible format.

    Filename: Hour_{CODE}_{YYYYMM}00.csv
    Columns:  Time, Open, High, Low, Latest, Volume
    """
    OUTDIR.mkdir(parents=True, exist_ok=True)
    fname = OUTDIR / f"Hour_{code}_{year:04d}{month_num:02d}00.csv"

    out = pd.DataFrame({
        "Time": df.index.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "Open": df["open"],
        "High": df["high"],
        "Low": df["low"],
        "Latest": df["close"],
        "Volume": df["volume"].astype(int),
    })
    # Databento timestamps come tz-aware UTC already; format `+0000`
    out["Time"] = out["Time"].str.replace(r"\+0000$", "+0000", regex=True)
    out.to_csv(fname, index=False)
    return fname


def download_instrument(code: str, root: str, client, priced_cycle: str) -> int:
    """Download all contracts for one instrument, partition by expiration,
    write one CSV per contract month that matches the priced roll cycle.

    Returns the number of contracts written.
    """
    allowed_months = set(priced_cycle)
    print(f"  fetching {code} ({root}.FUT), priced cycle={priced_cycle}", flush=True)

    try:
        data = client.timeseries.get_range(
            dataset=DATASET,
            symbols=[f"{root}.FUT"],
            stype_in="parent",
            schema=SCHEMA,
            start=START_DATE,
            end=END_DATE,
        )
        df = data.to_df()
    except Exception as e:
        print(f"    ERROR fetching {code}: {e}", file=sys.stderr)
        return 0

    if df.empty:
        print(f"    no data returned for {code}")
        return 0

    if "symbol" not in df.columns or "instrument_id" not in df.columns:
        print(f"    WARNING: missing symbol/instrument_id column for {code}")
        return 0

    written = 0
    skipped_wrong_cycle = 0
    unparseable = 0

    # Group by instrument_id (UNAMBIGUOUS). Databento recycles single-digit-year
    # symbols every decade (e.g. `HEG5` = Feb-2015 AND Feb-2025), so the symbol
    # letter+digit cannot identify the contract or its year. instrument_id is
    # unique per real contract; the year is taken from the contract's OWN data
    # (a contract's hourly bars end within ~a month of its expiry), never from
    # the ambiguous symbol digit. Spread/BF symbols (containing '-' or ' ') are
    # not outright contracts and are skipped.
    for instr_id, sub in df.groupby("instrument_id"):
        contract_symbol = str(sub["symbol"].iloc[0])
        # skip spreads / butterflies / any non-outright symbol
        if "-" in contract_symbol or " " in contract_symbol:
            unparseable += 1
            continue
        if not contract_symbol.startswith(root):
            unparseable += 1
            continue
        tail = contract_symbol[len(root):]
        if not tail or tail[0] not in MONTH_CODES:
            unparseable += 1
            continue
        month_letter = tail[0]
        if month_letter not in allowed_months:
            skipped_wrong_cycle += 1
            continue
        month_num = MONTH_CODES[month_letter]

        # Derive the true contract YEAR from the data itself. A contract expires
        # in `month_num`; its last bar is on/just before expiry. Take the year of
        # the last data point, then correct for the (rare) case where the last
        # bar precedes the delivery month within its year.
        last_ts = sub.index.max()
        year = last_ts.year
        if last_ts.month < month_num - 1:
            # data ends well before the delivery month -> contract is that year
            # (no adjustment); if it ends after, the contract already delivered
            pass
        elif last_ts.month > month_num + 1:
            year += 1  # trading tail spilled past delivery into next year (rare)

        sub = sub.drop(columns=["symbol", "instrument_id", "rtype",
                                "publisher_id"], errors="ignore")
        try:
            write_contract_csv(sub, code, year, month_num)
            written += 1
        except Exception as e:
            print(f"    ERROR writing {contract_symbol} ({instr_id}): {e}",
                  file=sys.stderr)

    print(f"    {code}: wrote {written} contracts "
          f"(skipped {skipped_wrong_cycle} off-cycle, {unparseable} non-outright)",
          flush=True)
    return written


# ============================================================
# Main
# ============================================================
def main():
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        print("ERROR: DATABENTO_API_KEY not set in environment.", file=sys.stderr)
        print("Set it via: export DATABENTO_API_KEY='db-...'", file=sys.stderr)
        print("Find your keys at: https://databento.com/portal/keys", file=sys.stderr)
        sys.exit(1)

    client = db.Historical(key=api_key)
    priced_cycles = load_priced_cycles()

    print(f"Downloading {len(INSTRUMENTS)} instruments from {DATASET}")
    print(f"Schema: {SCHEMA}, window: {START_DATE} → {END_DATE}")
    print(f"Output: {OUTDIR}")
    print()

    total_contracts = 0
    missing_cycle = []

    for code, root in INSTRUMENTS.items():
        if code not in priced_cycles:
            missing_cycle.append(code)
            print(f"  SKIP {code}: no PricedRollCycle in rollconfig.csv")
            continue
        n = download_instrument(code, root, client, priced_cycles[code])
        total_contracts += n

    print()
    print(f"Done. Wrote {total_contracts} contract CSVs to {OUTDIR}")
    if missing_cycle:
        print(f"Missing rollconfig: {missing_cycle}")


if __name__ == "__main__":
    main()
