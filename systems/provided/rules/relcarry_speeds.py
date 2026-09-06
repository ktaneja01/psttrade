def relative_carry_smoothed(
    smoothed_carry_this_instrument,
    median_carry_for_asset_class,
    smooth_days=30,
):
    relcarry = smoothed_carry_this_instrument - median_carry_for_asset_class
    return relcarry.ewm(smooth_days, min_periods=1).mean()
