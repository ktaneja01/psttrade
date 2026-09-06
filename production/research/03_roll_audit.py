"""Stage 3 — roll & back-adjustment audit on the curated store.

Thin wrapper: runs production/roll_audit.py against the curated_rolladjusted store.
PASS = 0 back-adjustment bugs / 0 wrong-contract / 0 real stalls. Known-benign flags
(frontier stalls, real market moves like 2020 COVID) are reported separately and are
NOT failures. See production/roll_audit.py for the methodology.

Run:  pst-env/bin/python3 production/research/03_roll_audit.py
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
AUDIT = os.path.join(ROOT, "production", "roll_audit.py")

# pysystemtrade's parquet resolver treats the store path as a PACKAGE path and turns
# dots into slashes; the repo path contains a dot (kunal.taneja) -> Permission denied.
# Point the audit at a DOT-FREE symlink alias instead.
ALIAS = "/tmp/curated_store"
if os.path.realpath(ALIAS) != os.path.realpath(CUR):
    if os.path.islink(ALIAS) or os.path.exists(ALIAS):
        os.remove(ALIAS)
    os.symlink(CUR, ALIAS)

rc = subprocess.run([sys.executable, AUDIT, ALIAS], cwd=ROOT)
sys.exit(rc.returncode)
