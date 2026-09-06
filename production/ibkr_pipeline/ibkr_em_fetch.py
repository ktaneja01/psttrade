"""Probe + fetch EM/Asian instruments that were Barchart dead-ends but IBKR (broker)
should carry: KOSPI/KOSDAQ (KRX), TOPIX/JGB (JPX/OSE), TSX60/CAD10 (Montreal),
BOVESPA (B3), MSCITAIWAN (SGX/TAIFEX), KR10 (KRX). Pulls up to 24M daily bars,
writes loader-shape CSVs to /tmp/ibkr_em/ for the rebuild chain.

USAGE: pst-env/bin/python3 production/ibkr_pipeline/ibkr_em_fetch.py
"""
import os, time
from ib_insync import IB, Future, util

OUT="/tmp/ibkr_em"; os.makedirs(OUT, exist_ok=True)

# candidate list: code -> list of (symbol, exchange, currency) to try in order
CAND = {
 "KOSPI":     [("K200","KSE","KRW"),("KOSPI200","KSE","KRW"),("K2","KSE","KRW")],
 "KOSPI_mini":[("MK200","KSE","KRW"),("KM","KSE","KRW")],
 "KOSDAQ":    [("KOSDQ150","KSE","KRW"),("KQ","KSE","KRW")],
 "TOPIX":     [("TOPX","OSE.JPN","JPY"),("TPX","OSE.JPN","JPY"),("TOPIX","OSE.JPN","JPY")],
 "JGB":       [("JGB","OSE.JPN","JPY"),("JGBL","OSE.JPN","JPY")],
 "TSX60":     [("SXF","CDE","CAD"),("PTF","CDE","CAD")],
 "CAD10":     [("CGB","CDE","CAD"),("CN","CDE","CAD")],
 "BOVESPA":   [("IND","BVMF","BRL"),("BOVESPA","BVMF","BRL"),("WIN","BVMF","BRL")],
 "MSCITAIWAN":[("STW","SGX","USD"),("TW","SGX","USD"),("MST","TAIFEX","TWD")],
 "KR10":      [("KTB10","KSE","KRW"),("LKTB","KSE","KRW")],
}

def resolve_and_fetch(ib, code, cands, dur="2 Y"):
    for sym,exch,ccy in cands:
        try:
            det=ib.reqContractDetails(Future(symbol=sym,exchange=exch,currency=ccy)); time.sleep(2)
            if not det: continue
            c=det[0].contract
            bars=ib.reqHistoricalData(c,endDateTime="",durationStr=dur,barSizeSetting="1 day",
                                      whatToShow="TRADES",useRTH=False,formatDate=1); time.sleep(2)
            nb=len(bars) if bars else 0
            if nb==0:
                # some non-US need MIDPOINT not TRADES
                bars=ib.reqHistoricalData(c,endDateTime="",durationStr=dur,barSizeSetting="1 day",
                                          whatToShow="MIDPOINT",useRTH=False,formatDate=1); time.sleep(2)
                nb=len(bars) if bars else 0
            if nb>0:
                df=util.df(bars)
                # write loader-shape CSV (Time,Open,High,Low,Final,Volume)
                out=df[["date","open","high","low","close","volume"]].copy()
                out.columns=["Time","Open","High","Low","Final","Volume"]
                path=f"{OUT}/{code}_daily.csv"; out.to_csv(path,index=False)
                return f"OK {nb} bars {df.date.min()}..{df.date.max()} ({sym}/{exch}) -> {path}"
        except Exception as e:
            time.sleep(1)
    return "NOT FOUND on IB"

if __name__=="__main__":
    ib=IB(); ib.connect("127.0.0.1",4002,clientId=55,timeout=25)
    for code,cands in CAND.items():
        print(f"  {code:12s} {resolve_and_fetch(ib,code,cands)}",flush=True)
    ib.disconnect()
