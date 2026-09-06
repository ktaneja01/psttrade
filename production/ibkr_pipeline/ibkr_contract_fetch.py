"""IB PER-CONTRACT fetch: for each instrument, enumerate all individual futures
contracts, pull daily bars each, write Hour_<CODE>_<YYYYMM>00.csv (loader shape) to
the bc-utils barchart path so the standard rebuild chain (init->roll->multiple->
adjusted) can build a CLEAN panama-stitched series (fixes the continuous-series
roll-gap vol corruption seen on KOSPI/KOSDAQ)."""
import os, sys, time
from ib_insync import IB, Future, util
import pandas as pd

SAVE=os.path.expanduser("~/data/barchart")  # same path rebuild_breadth reads
MONTHCODE={1:"F",2:"G",3:"H",4:"J",5:"K",6:"M",7:"N",8:"Q",9:"U",10:"V",11:"X",12:"Z"}

# code -> (ibSymbol, exchange, currency)
SPECS={
 "KOSPI":("K200","KSE","KRW"), "KOSDAQ":("KOSDQ150","KSE","KRW"),
 "TOPIX":("TOPX","OSE.JPN","JPY"), "JGB":("JGB","OSE.JPN","JPY"),
 "CAD10":("CGB","CDE","CAD"),
}
def fetch(ib, code):
    sym,exch,ccy=SPECS[code]
    det=ib.reqContractDetails(Future(symbol=sym,exchange=exch,currency=ccy)); time.sleep(2)
    if not det: return f"{code}: no contracts"
    n=0
    for d in det:
        c=d.contract
        exp=c.lastTradeDateOrContractMonth  # YYYYMMDD or YYYYMM
        if not exp or len(exp)<6: continue
        yyyymm=exp[:6]
        try:
            bars=ib.reqHistoricalData(c,endDateTime="",durationStr="2 Y",barSizeSetting="1 day",
                                      whatToShow="TRADES",useRTH=False,formatDate=1); time.sleep(1.5)
            if not bars:
                bars=ib.reqHistoricalData(c,endDateTime="",durationStr="2 Y",barSizeSetting="1 day",
                                          whatToShow="MIDPOINT",useRTH=False,formatDate=1); time.sleep(1.5)
            if not bars: continue
            df=util.df(bars)
            out=df[["date","open","high","low","close","volume"]].copy()
            out.columns=["Time","Open","High","Low","Final","Volume"]
            # loader wants ISO time; make it a datetime string
            out["Time"]=pd.to_datetime(out["Time"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
            path=f"{SAVE}/Hour_{code}_{yyyymm}00.csv"; out.to_csv(path,index=False)
            n+=1
        except Exception:
            time.sleep(1)
    return f"{code}: wrote {n} contract files"

if __name__=="__main__":
    codes=sys.argv[1:] or list(SPECS)
    ib=IB(); ib.connect("127.0.0.1",4002,clientId=63,timeout=25)
    for code in codes:
        print("  "+fetch(ib,code),flush=True)
    ib.disconnect()
