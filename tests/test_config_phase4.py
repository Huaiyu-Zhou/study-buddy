def test_elevenlabs_model_is_defined():
    from config import ELEVENLABS_MODEL
    assert isinstance(ELEVENLABS_MODEL, str)
    assert len(ELEVENLABS_MODEL) > 0


def test_tts_output_format_is_defined():
    from config import TTS_OUTPUT_FORMAT
    assert isinstance(TTS_OUTPUT_FORMAT, str)
    assert "pcm" in TTS_OUTPUT_FORMAT


def test_tts_sample_rate_is_defined():
    from config import TTS_SAMPLE_RATE
    assert isinstance(TTS_SAMPLE_RATE, int)
    assert TTS_SAMPLE_RATE > 0
