from apexprime.device import _number


def test_number_parses_decimal_comma():
    assert _number("27,4") == 27.4


def test_number_rejects_missing_and_invalid():
    assert _number(None) is None
    assert _number("N/D") is None


def test_number_parses_rssi_integer():
    assert _number("-67") == -67.0
