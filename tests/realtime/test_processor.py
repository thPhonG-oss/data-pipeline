import pandas as pd
import pytest

from realtime.processor import _transform_message, _validate_message

_VALID_MSG = {
    "symbol": "HPG",
    "time": "2026-03-21T09:01:00+07:00",
    "open": "20800.0",
    "high": "20900.0",
    "low": "20750.0",
    "close": "20850.0",
    "volume": "1234567",
    "resolution": "1",
}


def test_transform_valid_message():
    row = _transform_message(_VALID_MSG)
    assert row["symbol"] == "HPG"
    assert row["resolution"] == 1
    assert row["open"] == 20800
    assert row["close"] == 20850
    assert row["source"] == "dnse_mdds"
    assert "time" in row
    assert "fetched_at" in row


def test_transform_5min_resolution():
    msg = {**_VALID_MSG, "resolution": "5"}
    row = _transform_message(msg)
    assert row["resolution"] == 5


def test_validate_rejects_missing_field():
    for field in ["symbol", "time", "close", "resolution"]:
        bad = {k: v for k, v in _VALID_MSG.items() if k != field}
        assert _validate_message(bad) is False


def test_validate_rejects_non_numeric_resolution():
    msg = {**_VALID_MSG, "resolution": "1H"}   # 1H not supported
    assert _validate_message(msg) is False


def test_validate_rejects_zero_close():
    msg = {**_VALID_MSG, "close": "0"}
    assert _validate_message(msg) is False


def test_transform_price_rounded_to_int():
    msg = {**_VALID_MSG, "close": "20850.7"}
    row = _transform_message(msg)
    assert isinstance(row["close"], int)
