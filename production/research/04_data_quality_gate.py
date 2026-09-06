"""Stage 4 — data-quality gate on the curated store.

Thin wrapper: runs production/data_quality_gate.py against the curated store
(via DQ_STORE env). Checks contract-file sanity, implausible jumps, broken/empty
series, price scale, and cross-instrument correlations. Run before trusting a backtest.

Run:  pst-env/bin/python3 production/research/04_data_quality_gate.py
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
GATE = os.path.join(ROOT, "production", "data_quality_gate.py")

# curated store is deliberately truncated at the backtest cutoff; require data to
# reach the cutoff month, not "today".
env = dict(os.environ, DQ_STORE=CUR, DQ_MIN_END="2025-12-01")
rc = subprocess.run([sys.executable, GATE], cwd=ROOT, env=env)
sys.exit(rc.returncode)
