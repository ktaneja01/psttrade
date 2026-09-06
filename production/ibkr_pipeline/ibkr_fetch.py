"""IBKR production data fetch (SKELETON — de-risk before relying on it).

Connects to IB Gateway via ib_insync, pulls daily bars per front-contract, writes
CSVs in the shape the existing rebuild chain consumes
(Time,Open,High,Low,Final,Volume — Final = close). Hybrid design: IB owns recent+live
bars; deep 2018-2026 history stays in the frozen parquet seed.

USAGE:
    # 1. Start IB Gateway (paper) listening on 127.0.0.1:4002 (paper) / 4001 (live)
    # 2. Probe first — does IB serve bars for your instruments?
    pst-env/bin/python3 production/ibkr_pipeline/ibkr_fetch.py --probe SP500 GOLD EU-BANKS
    # 3. Full daily fetch (once contract map is filled in):
    pst-env/bin/python3 production/ibkr_pipeline/ibkr_fetch.py --fetch

STATUS: skeleton. The CONTRACT_MAP below must be populated (IB symbol + exchange per
instrument) before --fetch works. --probe works with the few examples provided.
"""
import os, sys, argparse

STAGE = "/tmp/ibkr_stage"   # dot-free stage dir (loader resolves package paths; avoid dots)
IB_HOST, IB_PORT_PAPER, IB_PORT_LIVE = "127.0.0.1", 4002, 4001

# pysystemtrade code -> IB contract spec. secType=FUT. Fill in from IB contract search.
# exchange + symbol are the IB-native ones (NOT the Barchart codes).
CONTRACT_MAP = {
    "SP500_micro": ("MES","CME","USD", 1),
    "RUSSELL": ("M2K","CME","USD", 1),
    "NIKKEI": ("NKD","CME","USD", 1),
    "US10": ("ZN","CBOT","USD", 1),
    "US30": ("UB","CBOT","USD", 1),
    "GOLD_micro": ("MGC","COMEX","USD", 1),
    "SILVER-mini": ("QI","COMEX","USD", 1),
    "PALLAD": ("PA","NYMEX","USD", 1),
    "PLAT": ("PL","NYMEX","USD", 1),
    "COPPER-micro": ("MHG","COMEX","USD", 1),
    "CRUDE_W_micro": ("MCL","NYMEX","USD", 1),
    "HEATOIL": ("HO","NYMEX","USD", 1),
    "GASOILINE": ("RB","NYMEX","USD", 1),
    "GAS_US_mini": ("QG","NYMEX","USD", 1),
    "CORN": ("ZC","CBOT","USD", 1),
    "WHEAT": ("ZW","CBOT","USD", 1),
    "REDWHEAT": ("KE","CBOT","USD", 1),
    "SOYBEAN": ("ZS","CBOT","USD", 1),
    "SOYMEAL": ("ZM","CBOT","USD", 1),
    "SOYOIL": ("ZL","CBOT","USD", 1),
    "RICE": ("ZR","CBOT","USD", 1),
    "LIVECOW": ("LE","CME","USD", 1),
    "FEEDCOW": ("GF","CME","USD", 1),
    "LEANHOG": ("HE","CME","USD", 1),
    "COFFEE": ("KC","NYBOT","USD", 1),
    "COCOA": ("CC","NYBOT","USD", 1),
    "OJ": ("OJ","NYBOT","USD", 1),
    "BITCOIN": ("MBT","CME","USD", 1),
    "ETHER-micro": ("MET","CME","USD", 1),
    "VIX": ("VIX","CFE","USD", 1),
    "EUR_micro": ("M6E","CME","USD", 1),
    "GBP_micro": ("M6B","CME","USD", 1),
    "AUD_micro": ("M6A","CME","USD", 1),
    "JPY": ("JPY","CME","USD", 1),
    "NZD": ("NZD","CME","USD", 1),
    "CHF": ("CHF","CME","USD", 1),
    "MXP": ("MXP","CME","USD", 1),
    "BRE": ("BRE","CME","USD", 1),
    "ZAR": ("ZAR","CME","USD", 1),
    "EURCAD": ("ECD","CME","CAD", 1),
    "BUND": ("GBL","EUREX","EUR", 1),
    "BTP": ("BTP","EUREX","EUR", 1),
    "EUROSTX": ("ESTX50","EUREX","EUR", 1),
    "TECDAX": ("TDX","EUREX","EUR", 1),
    "EUROSTX-SMALL": ("DJESS","EUREX","EUR", 1),
    "EU-BANKS": ("SX7E","EUREX","EUR", 1),
    "EU-BASIC": ("SXPP","EUREX","EUR", 1),
    "EU-INSURE": ("SXIP","EUREX","EUR", 1),
    "EU-TECH": ("SX8P","EUREX","EUR", 1),
    "EU-HEALTH": ("SXDP","EUREX","EUR", 1),
    "EU-OIL": ("SXEP","EUREX","EUR", 1),
    "EU-AUTO": ("SXAP","EUREX","EUR", 1),
    "EU-MEDIA": ("SXMP","EUREX","EUR", 1),
    "EU-DJ-TELECOM": ("SXKP","EUREX","EUR", 1),
    "EU-TRAVEL": ("SXTP","EUREX","EUR", 1),
    "GASOIL": ("GOIL","IPE","USD", 1),
    "EUA": ("ECF","ENDEX","EUR", 1),
    "ROBUSTA": ("D","ICEEUSOFT","USD", 1),
    "FTSE100": ("Z","ICEEU","GBP", 1),
    "GILT": ("R","ICEEU","GBP", 1),
    "SMI": ("SMI","EUREX","CHF", 1),
    "AEX_mini": ("EOE","FTA","EUR", 1),
    "HANG_mini": ("MHI","HKFE","HKD", 1),
    "FTSECHINAA": ("XINA50","SGX","USD", 1),
    "MSCISING": ("SSG","SGX","SGD", 1),
    "IRON": ("TIO","COMEX","USD", 1),
    "NOK": ("NOK","CME","USD", 1),
    "SEK": ("SEK","CME","USD", 1),
    "PLN": ("PLN","CME","USD", 1),
    "CANOLA": ("RS","NYBOT","CAD", 1),
    "ALUMINIUM_LME": ("ALI","COMEX","USD", 1),
    "ZINC_LME": ("LZ","NYMEX","USD", 1),
    "US-REALESTATE": ("S5RLST","CME","USD", 1),
    "IG": ("IBXXIBIG","CFE","USD", 1),
}

def _connect(paper=True):
    from ib_insync import IB
    ib = IB()
    ib.connect(IB_HOST, IB_PORT_PAPER if paper else IB_PORT_LIVE, clientId=17, timeout=15)
    return ib

def probe(codes, paper=True):
    """Check IB returns daily bars for each code's front contract. Prints span + count."""
    from ib_insync import Future, util
    ib = _connect(paper)
    for code in codes:
        spec = CONTRACT_MAP.get(code)
        if not spec:
            print(f"  {code:14s} NO CONTRACT_MAP entry"); continue
        sym, exch, ccy, mult = spec
        try:
            # continuous front future
            c = Future(symbol=sym, exchange=exch, currency=ccy)
            det = ib.reqContractDetails(c)
            if not det:
                print(f"  {code:14s} IB: no contract found ({sym}/{exch})"); continue
            front = det[0].contract
            bars = ib.reqHistoricalData(front, endDateTime="", durationStr="2 Y",
                                        barSizeSetting="1 day", whatToShow="TRADES",
                                        useRTH=False, formatDate=1)
            if not bars:
                print(f"  {code:14s} IB: 0 bars ({sym}/{exch}) — DATA GAP"); continue
            df = util.df(bars)
            print(f"  {code:14s} OK  {len(df)} bars  {df.date.min()}..{df.date.max()}  ({sym}/{exch})")
        except Exception as e:
            print(f"  {code:14s} ERR {str(e)[:70]}")
    ib.disconnect()

def fetch(paper=True):
    print("fetch() not implemented — populate CONTRACT_MAP for all 74 instruments first,")
    print("then: per instrument, resolve front contract, reqHistoricalData daily bars,")
    print("write STAGE/Hour_<CODE>_<YYYYMM>00.csv (Time,Open,High,Low,Final,Volume),")
    print("and feed the existing init->roll->multiple->adjusted chain in APPEND mode.")

if __name__ == "__main__":
    os.makedirs(STAGE, exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs="*", help="codes to probe for IB data availability")
    ap.add_argument("--all", action="store_true", help="probe ALL instruments in CONTRACT_MAP")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--live", action="store_true", help="use live port 4001 (default paper 4002)")
    a = ap.parse_args()
    if a.all:
        probe(list(CONTRACT_MAP.keys()), paper=not a.live)
    elif a.probe:
        probe(a.probe, paper=not a.live)
    elif a.fetch:
        fetch(paper=not a.live)
    else:
        ap.print_help()
