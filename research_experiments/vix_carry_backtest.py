from sysdata.sim.csv_futures_sim_data import csvFuturesSimData
from sysdata.config.configdata import Config
from systems.basesystem import System
from systems.forecasting import Rules
from systems.forecast_scale_cap import ForecastScaleCap
from systems.forecast_combine import ForecastCombine
from systems.rawdata import RawData
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
from systems.accounts.accounts_stage import Account

data = csvFuturesSimData()

my_config = Config(dict(
    trading_rules=dict(
        carry=dict(
            function="systems.provided.rules.carry.carry",
            data=["rawdata.raw_carry"],
            other_args=dict(smooth_days=90),
        ),
    ),
    instruments=["VIX"],
    instrument_weights=dict(VIX=1.0),
    instrument_div_multiplier=1.0,
    forecast_weights=dict(carry=1.0),
    forecast_div_multiplier=1.0,
    forecast_scalars=dict(carry=30),
    percentage_vol_target=25,
    notional_trading_capital=100000,
    base_currency="USD",
))

my_system = System(
    [Account(), Portfolios(), PositionSizing(), ForecastCombine(),
     ForecastScaleCap(), Rules(), RawData()],
    data, my_config
)

print("=== Raw Carry (annualised roll / vol) ===")
print(my_system.rawdata.raw_carry("VIX").tail(10))

print("\n=== Smoothed Carry Forecast (pre-scaling) ===")
raw_carry = my_system.rawdata.raw_carry("VIX")
smoothed = raw_carry.ewm(90).mean()
print(smoothed.tail(10))

print("\n=== Capped Carry Forecast ===")
print(my_system.forecastScaleCap.get_capped_forecast("VIX", "carry").tail(10))

print("\n=== Subsystem Position ===")
print(my_system.positionSize.get_subsystem_position("VIX").tail(10))

print("\n=== Notional Position ===")
print(my_system.portfolio.get_notional_position("VIX").tail(10))

profits = my_system.accounts.portfolio()
print("\n=== Strategy Performance (net of costs) ===")
print(profits.net.percent.stats())

print("\n=== Strategy Performance (gross) ===")
print(profits.gross.percent.stats())

try:
    import matplotlib.pyplot as plt
    profits.net.percent.cumsum().plot(title="VIX Carry Strategy - Cumulative Returns")
    plt.ylabel("Cumulative % Return")
    plt.savefig("vix_carry_backtest.png", dpi=150, bbox_inches="tight")
    plt.show()
    print("\nPlot saved to vix_carry_backtest.png")
except Exception as e:
    print(f"Could not plot: {e}")
