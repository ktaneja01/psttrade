def carry_accel(raw_carry, smooth_days=30):
    smoothed = raw_carry.ewm(smooth_days, min_periods=1).mean()
    return smoothed - smoothed.shift(smooth_days)
