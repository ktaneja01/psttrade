"""Diagnose COTTON2 -inf P&L under dynamic optimisation."""
import numpy as np
import pandas as pd
from sysdata.config.configdata import Config
from sysdata.data_blob import dataBlob
from sysdata.sim.futures_sim_data_with_data_blob import genericBlobUsingFuturesSimData
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
from sysdata.csv.csv_roll_parameters import csvRollParametersData
from sysdata.csv.csv_spread_costs import csvSpreadCostData
from sysdata.csv.csv_spot_fx import csvFxPricesData
from sysdata.parquet.parquet_multiple_prices import parquetFuturesMultiplePricesData
from sysdata.parquet.parquet_adjusted_prices import parquetFuturesAdjustedPricesData
from syslogging.logger import get_logger
from systems.basesystem import System
from systems.forecasting import Rules
from systems.rawdata import RawData
from systems.forecast_combine import ForecastCombine
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
from systems.provided.attenuate_vol.vol_attenuation_forecast_scale_cap import volAttenForecastScaleCap
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import optimisedPositions
from systems.provided.dynamic_small_system_optimise.accounts_stage import accountForOptimisedStage


class parquetFuturesSimData(genericBlobUsingFuturesSimData):
    def __init__(self):
        super().__init__(data=dataBlob(log=get_logger("p"), class_list=[
            parquetFuturesAdjustedPricesData, parquetFuturesMultiplePricesData,
            csvFuturesInstrumentData, csvFxPricesData,
            csvRollParametersData, csvSpreadCostData]))


instruments = ["COTTON2", "SP500", "GOLD"]
config = Config("systems.provided.futures_chapter15.futuresconfig.yaml")
config.instruments = instruments
config.start_date = "2016-01-01"
config.percentage_vol_target = 20.0
config.notional_trading_capital = 500_000
config.instrument_weights = {i: 1.0/3 for i in instruments}
config.use_instrument_weight_estimates = False
config.use_instrument_div_mult_estimates = False
config.instrument_div_multiplier = 1.0
config.use_forecast_scale_estimates = True
config.use_forecast_weight_estimates = False
config.forecast_weights = {"ewmac16_64": 0.5, "ewmac32_128": 0.5}
config.use_attenuation = []
config.forecast_post_ceiling_cost_SR = 999

system = System(
    [accountForOptimisedStage(), optimisedPositions(), Portfolios(),
     PositionSizing(), RawData(), ForecastCombine(),
     volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

print("=" * 70)
print("COTTON2 diagnostic")
print("=" * 70)

# The underlying price used for P&L
price = system.rawdata.get_daily_prices("COTTON2")
print(f"\nDaily prices: {len(price)} rows, min={price.min():.2f}, max={price.max():.2f}")
print(f"  NaN: {price.isna().sum()}, zeros: {(price==0).sum()}, negative: {(price<0).sum()}")

# Position
pos = system.accounts.get_optimised_position("COTTON2")
print(f"\nOptimised position: {len(pos)} rows, min={pos.min()}, max={pos.max()}")

# Raw instrument price used in P&L calc
try:
    raw_price = system.accounts.get_instrument_prices_for_position_or_forecast(
        "COTTON2", position_or_forecast=pos)
    print(f"\nRaw price for P&L calc: {len(raw_price)} rows")
    print(f"  min={raw_price.min():.2f}, max={raw_price.max():.2f}")
    print(f"  NaN: {raw_price.isna().sum()}, zeros: {(raw_price==0).sum()}")
    # Find where diff explodes
    diff = raw_price.diff()
    print(f"  diff min: {diff.min():.2f}, max: {diff.max():.2f}")
    inf_diffs = np.isinf(diff).sum()
    print(f"  inf diffs: {inf_diffs}")
    large_diffs = (diff.abs() > 100).sum()
    print(f"  large diffs (|>100|): {large_diffs}")
except Exception as e:
    print(f"  ERROR: {e}")

# Full P&L
pnl = system.accounts.pandl_for_optimised_instrument("COTTON2")
ts = pnl.as_ts
print(f"\nP&L: {len(ts)} rows, inf count: {np.isinf(ts).sum()}, NaN: {ts.isna().sum()}")
if np.isinf(ts).sum() > 0:
    inf_dates = ts[np.isinf(ts)].index
    print(f"Inf dates first 5: {list(inf_dates[:5])}")
    for d in inf_dates[:3]:
        p_near = price.asof(d)
        pos_near = pos.asof(d)
        print(f"  {d}: pnl={ts.loc[d]}, price={p_near:.2f}, pos={pos_near}")

# Check cost deflator
from syscore.pandas.strategy_functions import calculate_cost_deflator
deflator = calculate_cost_deflator(price)
print(f"\nCost deflator: {len(deflator)} rows, min={deflator.min():.4f}, max={deflator.max():.4f}")
print(f"  inf: {np.isinf(deflator).sum()}, NaN: {deflator.isna().sum()}")
