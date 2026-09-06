"""Find where CRUDE_W's P&L goes to -inf under dynamic optimisation."""
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
            csvRollParametersData, csvSpreadCostData,
        ]))


# Minimal universe for speed
instruments = ["CRUDE_W", "GAS_US", "HEATOIL"]
instrument_weights = {i: 1.0 / len(instruments) for i in instruments}

config = Config("systems.provided.futures_chapter15.futuresconfig.yaml")
config.instruments = instruments
config.start_date = "2016-01-01"
config.percentage_vol_target = 20.0
config.notional_trading_capital = 500_000
config.instrument_weights = instrument_weights
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
print("CRUDE_W DIAGNOSTIC")
print("=" * 70)

# Check each layer of the stack
print("\n1. Adjusted prices")
adj = system.rawdata.get_daily_prices("CRUDE_W")
print(f"   length: {len(adj)}, NaN: {adj.isna().sum()}")
print(f"   min: {adj.min():.2f}, max: {adj.max():.2f}")
print(f"   head: {adj.head(2).values}, tail: {adj.tail(2).values}")

print("\n2. Daily returns")
rets = adj.diff()
print(f"   min: {rets.min():.4f}, max: {rets.max():.4f}")
print(f"   inf count: {np.isinf(rets).sum()}")

print("\n3. Vol estimate")
vol = system.rawdata.daily_returns_volatility("CRUDE_W")
print(f"   length: {len(vol)}, NaN: {vol.isna().sum()}")
print(f"   min: {vol.min():.4f}, max: {vol.max():.4f}")
print(f"   zero or near-zero: {(vol.abs() < 1e-6).sum()}")
if (vol.abs() < 1e-6).sum() > 0:
    print(f"   near-zero dates: {vol[vol.abs() < 1e-6].index[:5].tolist()}")

print("\n4. Forecast (ewmac16_64)")
f1 = system.forecastScaleCap.get_capped_forecast("CRUDE_W", "ewmac16_64")
print(f"   length: {len(f1)}, min: {f1.min():.2f}, max: {f1.max():.2f}, NaN: {f1.isna().sum()}")

print("\n5. Subsystem position (target unrounded)")
sub_pos = system.portfolio.get_notional_position_before_risk_scaling("CRUDE_W")
print(f"   min: {sub_pos.min():.2f}, max: {sub_pos.max():.2f}")
print(f"   abs > 1000: {(sub_pos.abs() > 1000).sum()}")

print("\n6. Optimised position")
opt_pos = system.accounts.get_optimised_position("CRUDE_W")
print(f"   min: {opt_pos.min()}, max: {opt_pos.max()}, NaN: {opt_pos.isna().sum()}")
print(f"   sample: {opt_pos.dropna().tail(5).values}")

print("\n7. P&L")
pnl = system.accounts.pandl_for_optimised_instrument("CRUDE_W")
ts = pnl.as_ts
print(f"   len: {len(ts)}, inf: {np.isinf(ts).sum()}, NaN: {ts.isna().sum()}")
if np.isinf(ts).sum() > 0:
    inf_dates = ts[np.isinf(ts)].index
    print(f"   inf dates (first 5): {inf_dates[:5].tolist()}")
    for d in inf_dates[:3]:
        nearby = ts.loc[d - pd.Timedelta(days=3):d + pd.Timedelta(days=3)]
        print(f"   {d}: pnl={ts.loc[d]}")
        print(f"     nearby pnl:\n{nearby}")
        pos_near = opt_pos.asof(d)
        price_near = adj.asof(d)
        print(f"     opt_pos at {d}: {pos_near}, price: {price_near}")
