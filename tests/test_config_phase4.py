def test_fish_audio_reference_id_is_defined():
    from config import FISH_AUDIO_REFERENCE_ID
    assert isinstance(FISH_AUDIO_REFERENCE_ID, str)


def test_tts_output_format_is_defined():
    from config import TTS_OUTPUT_FORMAT
    assert isinstance(TTS_OUTPUT_FORMAT, str)
    assert "pcm" in TTS_OUTPUT_FORMAT


def test_tts_sample_rate_is_defined():
    from config import TTS_SAMPLE_RATE
    assert isinstance(TTS_SAMPLE_RATE, int)
    assert TTS_SAMPLE_RATE > 0
