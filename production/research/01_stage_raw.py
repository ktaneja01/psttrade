"""Stage 1 — capture raw contract downloads into production/research/data/raw/.

Copies each instrument's raw hourly CSVs from the source vendor (Barchart or
Databento, per config.json vendor_plan) into data/raw/<INSTRUMENT>/, renamed to the
INSTRUMENT code and tz-stripped, so the raw store is self-contained and
vendor-agnostic for every downstream stage. Idempotent: clears each instrument dir
first. Only contracts with year >= data_start_year are captured (warm-up for the
backtest window).

Run:  pst-env/bin/python3 production/research/01_stage_raw.py
"""
import os, glob, re, json, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
RAW = os.path.join(HERE, "data", "raw")
BC = os.path.expanduser("~/data/barchart")
DB = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "databento", "hourly")
VENDOR_DIR = {"BC": BC, "DB": DB}
START = CFG["window"]["data_start_year"]
TZ = CFG["loader"]["tz_strip"]

os.makedirs(RAW, exist_ok=True)
staged = 0; total_files = 0; missing = []
for inst in CFG["universe"]:
    vp = CFG["vendor_plan"].get(inst)
    if not vp or vp["vendor"] == "NONE":
        missing.append(inst); continue
    sdir = VENDOR_DIR[vp["vendor"]]; code = vp["source_code"]
    # per-instrument start override (for instruments with illiquid/flat early years,
    # e.g. ALUMINIUM pre-2020 was 96% flat -> vol->0 sizing blowup). Drops the bad head.
    inst_start = int(vp.get("start_year_override", START))
    dest = os.path.join(RAW, inst)
    shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest)
    n = 0
    for f in glob.glob(f"{sdir}/Hour_{code}_*.csv"):
        base = os.path.basename(f)
        if not base.startswith(f"Hour_{code}_"):
            continue
        m = re.search(r"_(\d{4})\d{2}00?\.csv", base)
        if not m or int(m.group(1)) < inst_start:
            continue
        cid = base[len(f"Hour_{code}_"):]
        out = os.path.join(dest, f"Hour_{inst}_{cid}")
        open(out, "w").write(open(f).read().replace(TZ, ""))
        n += 1
    if n == 0:
        missing.append(inst)
    else:
        staged += 1; total_files += n
    print(f"  {inst:15s} {vp['vendor']}:{code:12s} {n} files")

print(f"\nSTAGED {staged}/{len(CFG['universe'])} instruments, {total_files} raw files -> {RAW}")
if missing:
    print("MISSING (no raw source):", missing)
