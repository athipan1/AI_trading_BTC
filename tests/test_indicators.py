from app.features.indicators import atr, ema, rsi


def test_ema_tracks_latest_prices() -> None:
    values = [float(i) for i in range(1, 61)]
    result = ema(values, 20)
    assert 45 < result < 60


def test_rsi_for_only_gains_is_100() -> None:
    values = [float(i) for i in range(1, 20)]
    assert rsi(values, 14) == 100.0


def test_atr_is_positive(trend_candles) -> None:
    assert atr(trend_candles, 14) > 0
