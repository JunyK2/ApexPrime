from apexprime.utils import safe_timezone_name, local_time_label
from datetime import datetime, timezone


def test_unknown_timezone_falls_back_to_sao_paulo():
    assert safe_timezone_name("[REDACTED]") == "America/Sao_Paulo"
    assert safe_timezone_name("not/a-real-timezone") == "America/Sao_Paulo"


def test_timezone_label_keeps_generator_working_on_invalid_setting():
    value = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)
    label = local_time_label(value, "Unknown/Timezone")
    assert label == "21/11 12:00"
