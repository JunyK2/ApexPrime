import unittest

from apexprime.risk import size_position, validate_apex_table


class RiskTests(unittest.TestCase):
    def test_position_size_never_exceeds_risk_budget(self):
        result = size_position(balance=20, available_margin=20, entry=60000,
                               stop=59400, risk_pct=2, leverage=20, taker_fee=0.0005)
        self.assertLessEqual(result["risk_pct"], 2.0)
        self.assertLessEqual(result["margin_used"], 20)
        self.assertGreater(result["quantity"], 0)

    def test_maker_entry_fee_is_used_in_risk_budget(self):
        maker_entry = size_position(balance=20, available_margin=20, entry=60000,
                                    stop=59400, risk_pct=2, leverage=20,
                                    taker_fee=0.0005, entry_fee_rate=0.0002)
        taker_entry = size_position(balance=20, available_margin=20, entry=60000,
                                    stop=59400, risk_pct=2, leverage=20,
                                    taker_fee=0.0005, entry_fee_rate=0.0005)
        self.assertGreater(maker_entry["quantity"], taker_entry["quantity"])
        self.assertLessEqual(maker_entry["risk_pct"], 2.0)
        self.assertLessEqual(taker_entry["risk_pct"], 2.0)

    def test_valid_long_table(self):
        data = validate_apex_table({
            "signal": "LONG", "entry_type": "IMEDIATA", "direction": "LONG",
            "entry": 100, "stop_loss": 99, "tp1": 101.5, "tp2": 103,
            "risk_reward_tp1": 1.5, "confidence": "MEDIA", "score": 7,
            "regime": "TENDENCIA", "strategy_name": "teste", "analysis_summary": "ok",
        })
        self.assertAlmostEqual(data["calculated_rr_tp1"], 1.5)

    def test_rejects_invalid_short_geometry(self):
        with self.assertRaises(ValueError):
            validate_apex_table({
                "signal": "SHORT", "entry_type": "IMEDIATA", "direction": "SHORT",
                "entry": 100, "stop_loss": 99, "tp1": 98, "tp2": 97,
                "risk_reward_tp1": 2, "confidence": "ALTA", "score": 8,
                "regime": "TENDENCIA",
            })


if __name__ == "__main__":
    unittest.main()
