from app.execution.paper import PaperBroker


def test_paper_buy_and_sell_round_trip() -> None:
    broker = PaperBroker(10_000, fee_rate=0, slippage_bps=0)
    buy = broker.buy(0.1, 50_000)
    assert buy.accepted
    assert broker.position_qty == 0.1

    sell = broker.sell(0.1, 51_000)
    assert sell.accepted
    snapshot = broker.snapshot(51_000)
    assert snapshot.position_qty == 0
    assert snapshot.cash == 10_100
    assert snapshot.realized_pnl == 100


def test_paper_broker_rejects_oversell() -> None:
    broker = PaperBroker(10_000)
    assert not broker.sell(1, 50_000).accepted
