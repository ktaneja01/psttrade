# research_experiments/

One-off research, diagnostics, and data-repair scripts from the strategy-development
sessions (2026-06 to 2026-08). **NOT part of the production path.** Kept for reference.

Most scripts read the master config via `open("signals.py")` with a RELATIVE path,
so they must be run from the repo ROOT, e.g.:

    cd /Users/kunal.taneja/pysystemtrade
    pst-env/bin/python3 research_experiments/<script>.py

## Rough map (not exhaustive)

**Allocation experiments** (superseded by the real handcraft — see memory
`handcraft-beats-hand-dm-tree`): block_handcraft_dm.py, block_handcraft.py,
handcraft_deep_tree.py, handcraft_manual_tree.py, handcraft_tree*.py, herc_*.py,
show_*_weights.py, compare_optimisers.py, hierarchical_clusters.py, block_dendro.py,
dendro_weights.py, plot_handcraft_dendrogram.py.

**Backtest / attribution**: bt_breadth.py, oos_by_rule.py, family_by_year.py,
ytd_*.py, subperiod_check.py, compare_strategies.py, equity_curves.py,
diagnose_*.py, strategy_stats.py, four_sleeve_portfolio.py, three_sleeve_portfolio.py,
two_sleeve_spy.py, vix_*.py, margin_*.py, current_positions.py, idm_timeseries.py.

**Data fetch / rebuild** (Databento + bc-utils — got the BACKTEST data; production
will use IBKR fresh, see ../production/): download_databento.py, load_*.py,
rebuild_*.py, fetch_*.py, build_*.py, derive_daily_from_hourly.py,
repair_databento_misdating.py, fix_databento_filenames.py, redownload_crude.py.

**Diagnostics**: duplicate_detector.py, corr_*.py, system_correlations.py,
reestimate_scalars.py, skew_*.py, forecast_matrix.py, turnover_accel8.py,
relcarry_diagnostic.py, oj_risk_diagnostic.py, compute_dsr.py, block_bootstrap_sharpe.py.
