"""Production runner for the rob_system dynamic-optimised strategy.

Carver's shipped `runSystemCarryTrendDynamic` builds with plain RawData/
ForecastScaleCap. Our book needs the rob_system stages (myFuturesRawData +
volAttenForecastScaleCap), which Carver already ships as
`systems.provided.rob_system.run_system.futures_system`. This is the standard
extension point: subclass the shipped dynamic runner and build via that shipped
builder. No config or modelling code is reinvented — the YAML is the single
source of truth and the stages come straight from rob_system.

Wire in private_control_config.yaml:

    process_configuration_methods:
      run_systems:
        <strategy_name>:
          object: sysproduction.strategy_code.run_rob_dynamic_system.runSystemRobDynamic
          backtest_config_filename: production.live.production_config.yaml
          max_executions: 1

and in private_config.yaml strategy_list -> load_backtests -> object: (same class),
function: system_method.
"""
from syscore.constants import arg_not_supplied

from sysproduction.strategy_code.run_dynamic_optimised_system import (
    runSystemCarryTrendDynamic,
)
from sysproduction.data.sim_data import get_sim_data_object_for_production
from systems.provided.rob_system.run_system import futures_system as rob_futures_system


class runSystemRobDynamic(runSystemCarryTrendDynamic):
    # NAME IS REFERENCED IN CONFIG (run_systems + load_backtests) — keep stable.
    def system_method(
        self,
        notional_trading_capital: float = arg_not_supplied,
        base_currency: str = arg_not_supplied,
    ):
        # production sim data (parquet prices + mongo metadata) + the frozen YAML,
        # built with the rob_system stages via the shipped builder.
        sim_data = get_sim_data_object_for_production(self.data)
        system = rob_futures_system(
            sim_data=sim_data,
            config_filename=self.backtest_config_filename,
        )

        # capital / currency are injected by update_strategy_capital at run time;
        # config is read lazily by the stages, so setting it post-build is fine.
        if notional_trading_capital is not arg_not_supplied:
            system.config.notional_trading_capital = notional_trading_capital
        if base_currency is not arg_not_supplied:
            system.config.base_currency = base_currency

        system._log = self.data.log
        return system

    # function_to_call_on_update (-> updated_optimal_positions_for_dynamic_system)
    # is inherited unchanged from runSystemCarryTrendDynamic.
