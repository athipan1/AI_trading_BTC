from scripts.check_binance_testnet_access import check_access


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_access_accepts_testnet_server_time(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.check_binance_testnet_access.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"serverTime": 123456789}),
    )
    result = check_access()
    assert result["ok"] is True
    assert result["server_time"] == 123456789


def test_access_fails_closed_on_restricted_location(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.check_binance_testnet_access.requests.get",
        lambda *args, **kwargs: FakeResponse(451, text="restricted location"),
    )
    result = check_access()
    assert result["ok"] is False
    assert result["status_code"] == 451
    assert result["reason"] == "binance_restricted_location"


def test_access_rejects_invalid_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.check_binance_testnet_access.requests.get",
        lambda *args, **kwargs: FakeResponse(200, {"serverTime": 0}),
    )
    result = check_access()
    assert result["ok"] is False
    assert result["reason"] == "missing_server_time"
