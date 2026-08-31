from __future__ import annotations

import json
import sys

import requests

TESTNET_TIME_URL = "https://testnet.binance.vision/api/v3/time"


def check_access(timeout_seconds: float = 10.0) -> dict:
    try:
        response = requests.get(TESTNET_TIME_URL, timeout=timeout_seconds)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "endpoint": TESTNET_TIME_URL,
            "reason": f"network_error: {exc.__class__.__name__}",
        }

    body = response.text[:500]
    if response.status_code == 451:
        return {
            "ok": False,
            "status_code": 451,
            "endpoint": TESTNET_TIME_URL,
            "reason": "binance_restricted_location",
            "body": body,
        }

    if not response.ok:
        return {
            "ok": False,
            "status_code": response.status_code,
            "endpoint": TESTNET_TIME_URL,
            "reason": "unexpected_http_status",
            "body": body,
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "status_code": response.status_code,
            "endpoint": TESTNET_TIME_URL,
            "reason": "invalid_json",
            "body": body,
        }

    server_time = payload.get("serverTime")
    if not isinstance(server_time, int) or server_time <= 0:
        return {
            "ok": False,
            "status_code": response.status_code,
            "endpoint": TESTNET_TIME_URL,
            "reason": "missing_server_time",
        }

    return {
        "ok": True,
        "status_code": response.status_code,
        "endpoint": TESTNET_TIME_URL,
        "server_time": server_time,
    }


def main() -> None:
    result = check_access()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
