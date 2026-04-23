def test_deepseek_model_is_defined():
    from config import DEEPSEEK_MODEL
    assert isinstance(DEEPSEEK_MODEL, str)
    assert len(DEEPSEEK_MODEL) > 0


def test_deepseek_api_key_is_defined():
    from config import DEEPSEEK_API_KEY
    assert isinstance(DEEPSEEK_API_KEY, str)
