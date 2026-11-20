import pytest

from apexprime.config import Config


def make_config(**overrides):
    values = {
        "supabase_url": "",
        "supabase_service_role_key": "",
        "gemini_api_key": "",
        "groq_api_key": "",
        "chart_img_api_key": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
    }
    values.update(overrides)
    return Config(**values)


def test_paper_trading_configuration_is_allowed():
    make_config(paper_trading_only=True, real_trading_enabled=False).validate_paper_only()


@pytest.mark.parametrize(
    "overrides",
    [
        {"paper_trading_only": False, "real_trading_enabled": False},
        {"paper_trading_only": True, "real_trading_enabled": True},
    ],
)
def test_real_trading_configuration_is_blocked(overrides):
    config = make_config(**overrides)
    with pytest.raises(RuntimeError, match="Modo real bloqueado"):
        config.validate_paper_only()
