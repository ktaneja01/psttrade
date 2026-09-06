def spot_trend(spot_price, vol, Lfast, Lslow):
    """
    EWMAC on the spot (front-contract) price instead of the back-adjusted price.

    Isolates directional price trend from the roll-yield component that is
    embedded in back-adjusted prices, so the signal is orthogonal to carry.
    """
    fast_ewma = spot_price.ewm(span=Lfast, min_periods=1).mean()
    slow_ewma = spot_price.ewm(span=Lslow, min_periods=1).mean()
    raw = fast_ewma - slow_ewma
    return raw / vol.ffill()
