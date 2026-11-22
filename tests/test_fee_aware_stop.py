from apexprime.execution import PaperExecutor


def test_long_protective_stop_covers_booked_costs_and_buffer():
    trade = {
        "direction": "LONG", "entry_price": 100.0, "remaining_quantity": 1.0,
        "entry_fee": 0.05, "exit_fees": 0.0, "funding_paid": 0.0,
        "realized_pnl_gross": 0.0, "tp1_price": 110.0,
    }
    stop, meta = PaperExecutor.fee_covered_protective_stop(
        trade, {"taker_fee_rate": 0.0005, "profit_stop_buffer_bps": 5}
    )
    assert meta["fee_covered"] is True
    assert stop > 100.0
    assert stop < 110.0


def test_short_protective_stop_is_below_entry_and_above_tp1():
    trade = {
        "direction": "SHORT", "entry_price": 100.0, "remaining_quantity": 1.0,
        "entry_fee": 0.05, "exit_fees": 0.0, "funding_paid": 0.0,
        "realized_pnl_gross": 0.0, "tp1_price": 90.0,
    }
    stop, meta = PaperExecutor.fee_covered_protective_stop(
        trade, {"taker_fee_rate": 0.0005, "profit_stop_buffer_bps": 5}
    )
    assert meta["fee_covered"] is True
    assert 90.0 < stop < 100.0


def test_fee_aware_stop_does_not_claim_coverage_if_target_is_too_close():
    trade = {
        "direction": "LONG", "entry_price": 100.0, "remaining_quantity": 1.0,
        "entry_fee": 0.2, "exit_fees": 0.0, "funding_paid": 0.0,
        "realized_pnl_gross": 0.0, "tp1_price": 100.1,
    }
    stop, meta = PaperExecutor.fee_covered_protective_stop(
        trade, {"taker_fee_rate": 0.0005, "profit_stop_buffer_bps": 5}
    )
    assert meta["fee_covered"] is False
    assert stop == 100.0
