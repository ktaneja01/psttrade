"""Print current positions of the system across all 59 instruments at $1M capital."""
import os
os.environ.setdefault("CAPITAL", "1000000")

import numpy as np
import pandas as pd

print("Building system at $1M (this takes ~5 min)...")
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])
from systems.basesystem import System
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import optimisedPositions
from systems.provided.dynamic_small_system_optimise.accounts_stage import accountForOptimisedStage
system = System(
    [accountForOptimisedStage(), optimisedPositions(), Portfolios(), PositionSizing(),
     myFuturesRawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

CAPITAL = int(os.environ["CAPITAL"])
print(f"\n{'='*80}")
print(f"Latest positions @ CAPITAL=${CAPITAL:,}")
print(f"{'='*80}")

# Asset class lookup
asset_class_lookup = {}
for cls, insts in _raw_asset_classes.items():
    for i in insts:
        asset_class_lookup[i] = cls

results = []
for inst in sorted(config.instruments):
    try:
        pos_series = system.accounts.get_optimised_position(inst).dropna()
        if len(pos_series) == 0:
            continue
        latest_pos = pos_series.iloc[-1]
        latest_date = pos_series.index[-1]

        # Latest price
        price_series = system.rawdata.get_daily_prices(inst).dropna()
        latest_price = price_series.iloc[-1] if len(price_series) > 0 else float('nan')

        # Contract multiplier
        try:
            multiplier = system.data.get_value_of_block_price_move(inst)
        except Exception:
            multiplier = 1.0

        # Currency
        try:
            currency = system.data.get_instrument_currency(inst)
        except Exception:
            currency = "USD"

        # Notional in instrument currency
        notional_inst_ccy = abs(latest_pos) * latest_price * multiplier

        # FX to USD (approximate)
        fx = 1.0
        if currency != "USD":
            try:
                fx_series = system.data.get_fx_for_instrument(inst, "USD")
                fx = fx_series.dropna().iloc[-1]
            except Exception:
                fx = 1.0

        notional_usd = notional_inst_ccy * fx
        results.append({
            "instrument": inst,
            "asset_class": asset_class_lookup.get(inst, "?"),
            "position": latest_pos,
            "price": latest_price,
            "currency": currency,
            "notional_usd": notional_usd,
            "direction": "LONG" if latest_pos > 0 else "SHORT" if latest_pos < 0 else "FLAT",
            "as_of": latest_date,
        })
    except Exception as e:
        results.append({
            "instrument": inst,
            "asset_class": asset_class_lookup.get(inst, "?"),
            "position": float("nan"),
            "price": float("nan"),
            "currency": "?",
            "notional_usd": 0,
            "direction": f"ERR:{type(e).__name__}",
            "as_of": pd.NaT,
        })

df = pd.DataFrame(results)

# Summary
non_zero = df[df["position"] != 0].copy()
non_zero = non_zero.sort_values(["direction", "asset_class", "instrument"])
zero_count = (df["position"] == 0).sum()

print(f"\nAs of {df['as_of'].dropna().max().date()}")
print(f"Total instruments in universe: {len(df)}")
print(f"  Non-zero positions: {len(non_zero)}")
print(f"  Zero positions: {zero_count}")

print(f"\n{'='*100}")
print(f"{'Instrument':<14} {'Class':<18} {'Dir':<6} {'Position':>10} {'Price':>10} {'Ccy':>5} {'Notional USD':>15}")
print("-"*100)
for cls in sorted(non_zero["asset_class"].unique()):
    sub = non_zero[non_zero["asset_class"] == cls]
    cls_total_long = sub[sub["position"] > 0]["notional_usd"].sum()
    cls_total_short = sub[sub["position"] < 0]["notional_usd"].sum()
    for _, r in sub.iterrows():
        print(f"{r['instrument']:<14} {r['asset_class']:<18} {r['direction']:<6} "
              f"{r['position']:>+10.1f} {r['price']:>10.2f} {r['currency']:>5} "
              f"{r['notional_usd']:>+15,.0f}")
    print(f"  Class {cls} total: long ${cls_total_long:,.0f} | short ${cls_total_short:,.0f}")
    print()

# Totals
total_long_notional = non_zero[non_zero["position"] > 0]["notional_usd"].sum()
total_short_notional = non_zero[non_zero["position"] < 0]["notional_usd"].sum()
gross = total_long_notional + total_short_notional
net = total_long_notional - total_short_notional
print(f"\n{'='*60}")
print(f"PORTFOLIO TOTALS:")
print(f"  Long notional:    ${total_long_notional:>14,.0f}  ({total_long_notional/CAPITAL*100:>5.1f}% of capital)")
print(f"  Short notional:   ${total_short_notional:>14,.0f}  ({total_short_notional/CAPITAL*100:>5.1f}% of capital)")
print(f"  Gross exposure:   ${gross:>14,.0f}  ({gross/CAPITAL*100:>5.1f}% of capital)")
print(f"  Net exposure:     ${net:>+14,.0f}  ({net/CAPITAL*100:>+5.1f}% of capital)")
print(f"{'='*60}")
