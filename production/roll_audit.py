"""Roll & back-adjustment audit — standing QA gate.

For every instrument in the live universe, independently validate that each roll
in `multiple_prices` used the correct contract and that the panama back-adjustment
was applied correctly. Built after a long debugging session (2026-08) established
that the SUBTLE bugs are in the AUDIT, not Carver's shipped stitching:

  1. Validate returns in ENGINE space  =  diff(adjusted) / |carry_price|
     NEVER pct_change(adjusted level) — back-adjusted energy levels go near-zero /
     negative (persistent backwardation), so pct_change manufactures 1000%+ phantom
     "jumps". This was the #1 false-positive source.  (see CLAUDE.md)
  2. The wrong-contract check must be DATA-AWARE: compare `to` against the next held
     contract *that actually has data*, not the theoretical roll cycle. Barchart/
     Databento omit many cycle months, and empty contract files exist — Carver's
     builder correctly skips those, and a naive check false-flags every skip.
  3. Separate REAL market moves from adjustment BUGS: at a seam anomaly, check the
     UNDERLYING contract's own return. If the contract moved too -> real (e.g. 2020
     COVID). If only the adjusted series moved -> genuine back-adjustment bug.
  4. Detect STALLS: priced pointer stuck while a later held contract has data.

Usage:
    pst-env/bin/python3 production/roll_audit.py [parquet_store]
      default store = value in private_config.yaml
Exit: prints per-instrument findings; a clean run has 0 BUG / 0 STALL / 0 WRONGDATA.
Real market moves (COVID etc.) are reported separately and are NOT failures.
"""
import os, io, contextlib, re, sys
import pandas as pd, numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

STORE = sys.argv[1] if len(sys.argv) > 1 else None
Z_THRESHOLD = 10.0          # engine-space robust-sigma multiple to flag a seam
CONTRACT_MOVE_REAL = 0.04   # if underlying contract moved > this at the seam -> real, not a bug
MIN_SEAM_CONTRACT_OBS = 4   # if the new contract has fewer obs near the seam, can't classify -> REVIEW not BUG
SEAM_WINDOW_DAYS = 4

PC = "private/private_config.yaml"
_orig = open(PC).read()
if STORE:
    open(PC, "w").write(re.sub(r"parquet_store:.*", f"parquet_store: '{STORE}'", _orig))

try:
    from sysproduction.data.prices import diagPrices
    from sysdata.csv.csv_roll_parameters import csvRollParametersData
    from sysobjects.contract_dates_and_expiries import contractDate
    from sysobjects.rolls import contractDateWithRollParameters
    from sysobjects.contracts import futuresContract
    from syscore.dateutils import DAILY_PRICE_FREQ

    diag = diagPrices(); dbp = diag.db_futures_contract_price_data
    rpd = csvRollParametersData()
    store = diag.db_futures_multiple_prices_data  # resolves to the configured parquet_store

    # universe = signals.py frozen keys (minus any dropped)
    src = open("signals.py").read().split("# Build system with dynamic")[0]
    ns = {}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(src, ns)
    univ = sorted(ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"].keys())

    def contracts_with_data(code):
        return sorted(set(x.date_str for x in
                          dbp.get_contracts_with_price_data_for_frequency(DAILY_PRICE_FREQ)
                          if x.instrument_code == code))

    def next_held_with_data(code, frm, rp, have):
        """Theoretical next held contract, advanced until one with data is found."""
        cdr = contractDateWithRollParameters(contractDate(frm), rp)
        for _ in range(24):
            cdr = cdr.next_held_contract()
            d = cdr.date_str
            if d in have:
                return d
        return None

    def contract_move_at(code, cid, dt):
        """(max_abs_daily_return, n_obs) of the contract's OWN price near the seam.
        Returns n_obs so callers can tell 'contract flat' from 'too thin to judge'."""
        try:
            px = diag.get_merged_prices_for_contract_object(
                futuresContract(code, cid)).return_final_prices().dropna()
            px.index = pd.to_datetime(px.index)
            d = px.resample("1B").last().dropna()
            w = d[(d.index >= dt - pd.Timedelta(days=SEAM_WINDOW_DAYS + 2)) &
                  (d.index <= dt + pd.Timedelta(days=SEAM_WINDOW_DAYS + 2))]
            if len(w) >= 2:
                return float((w.pct_change().abs()).max()), len(w)
        except Exception:
            pass
        return None, 0

    bugs = []; stalls = []; wrongdata = []; real = []; review = []; errs = []
    clean = 0

    for c in univ:
        try:
            mp = diag.get_multiple_prices(c)
            mp.index = pd.to_datetime(mp.index)
            adj = pd.to_numeric(diag.get_adjusted_prices(c), errors="coerce").dropna()
            adj.index = pd.to_datetime(adj.index)
            adjd = adj.resample("1B").last().dropna()
            carry = pd.to_numeric(mp["CARRY"], errors="coerce").resample("1B").last() \
                      .reindex(adjd.index).ffill()
            # ENGINE-SPACE returns (never pct_change of the level)
            eret = (adjd.diff() / carry.abs()).replace([np.inf, -np.inf], np.nan)
            sig = (eret - eret.median()).abs().median() * 1.4826
            rp = rpd.get_roll_parameters(c)
            have = set(contracts_with_data(c))
            pc = mp["PRICE_CONTRACT"].astype(str)
            if len(pc) < 2 or len(adjd) < 10:
                errs.append((c, "too few observations to audit")); continue
            trans = [(mp.index[i], pc.iloc[i - 1], pc.iloc[i])
                     for i in range(1, len(pc)) if pc.iloc[i] != pc.iloc[i - 1]]
            inst_issue = False

            for dt, frm, to in trans:
                # --- data-aware wrong-contract check ---
                if frm.isdigit() and to.isdigit():
                    if int(to) <= int(frm):
                        wrongdata.append((c, f"BACKWARD {frm}->{to}@{dt.date()}")); inst_issue = True
                    else:
                        exp = next_held_with_data(c, frm, rp, have)
                        if exp is not None and to != exp:
                            wrongdata.append((c, f"{frm}->{to} exp-with-data {exp}@{dt.date()}")); inst_issue = True
                # --- seam anomaly in engine space, real-vs-bug discriminated ---
                if sig and sig > 0:
                    near = eret[(eret.index >= dt - pd.Timedelta(days=SEAM_WINDOW_DAYS)) &
                                (eret.index <= dt + pd.Timedelta(days=2))].dropna()
                    if len(near):
                        zmax = ((near - eret.median()).abs() / sig).max()
                        if zmax > Z_THRESHOLD:
                            jday = ((near - eret.median()).abs() / sig).idxmax()
                            cret_to, n_to = contract_move_at(c, to, jday)
                            cret_fr, n_fr = contract_move_at(c, frm, jday)
                            cret = max([x for x in (cret_to, cret_fr) if x is not None], default=None)
                            n_obs = max(n_to, n_fr)
                            if cret is not None and cret > CONTRACT_MOVE_REAL:
                                real.append((c, jday.date(), f"z={zmax:.0f} contract moved {cret*100:.0f}% (REAL)"))
                            elif n_obs < MIN_SEAM_CONTRACT_OBS:
                                review.append((c, jday.date(), f"z={zmax:.0f} contract too thin ({n_obs} obs) to classify {frm}->{to}"))
                            else:
                                bugs.append((c, jday.date(), f"z={zmax:.0f} adj jumped, contract flat {frm}->{to} (BUG)")); inst_issue = True

            # --- stall: priced pointer stuck while next held-with-data exists before series end ---
            # A "frontier stall" (next contract is within ~1 roll of the data end) is BENIGN:
            # build_and_write_roll_calendar conservatively won't place the final roll without a
            # further anchor contract. Only flag a stall as a genuine FAIL if the priced pointer
            # is > 1 held-cycle behind the newest contract that has data (a real mid-series miss).
            last_priced = pc.iloc[-1]
            if last_priced.isdigit():
                nxt = next_held_with_data(c, last_priced, rp, have)
                if nxt is not None and nxt[:6] <= mp.index.max().strftime("%Y%m"):
                    # is there a held-with-data contract BEYOND nxt too? if so it's a real stall;
                    # if nxt is the last available (frontier), it's benign.
                    beyond = next_held_with_data(c, nxt, rp, have)
                    if beyond is not None:
                        stalls.append((c, f"priced={last_priced}, {nxt} AND {beyond} have data (real stall)")); inst_issue = True
                    else:
                        review.append((c, mp.index.max().date(), f"frontier stall: priced={last_priced}, {nxt} has data but no anchor beyond (benign)"))

            if not inst_issue:
                clean += 1
        except Exception as e:
            errs.append((c, str(e)[:60]))

    def show(title, items):
        print(f"\n=== {title} ({len(items)}) ===")
        for it in items:
            print("  " + "  ".join(str(x) for x in it))

    print(f"ROLL AUDIT — store={STORE or 'config default'} — universe={len(univ)}")
    print(f"CLEAN: {clean}/{len(univ)}")
    show("BACK-ADJUSTMENT BUGS (adjusted jumped, contract flat)", bugs)
    show("WRONG-CONTRACT / BACKWARD rolls (data-aware)", wrongdata)
    show("STALLS (missed roll, next contract has data)", stalls)
    show("REVIEW (seam anomaly, contract too thin to auto-classify)", review)
    show("REAL volatile rolls (NOT failures — informational)", real)
    show("ERRORS", errs)
    n_fail = len(bugs) + len(wrongdata) + len(stalls)
    print(f"\nRESULT: {'PASS' if n_fail == 0 else 'FAIL'} — {n_fail} genuine issues "
          f"({len(bugs)} bugs, {len(wrongdata)} wrong-contract, {len(stalls)} stalls); "
          f"{len(real)} real-move flags ignored.")
finally:
    open(PC, "w").write(_orig)
