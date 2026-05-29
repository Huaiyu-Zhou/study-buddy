import config

def test_config_has_watchdog_settings():
    assert isinstance(config.WATCHDOG_INTERVAL_SECONDS, int)
    assert isinstance(config.IDLE_THRESHOLD_SECONDS, int)
    assert isinstance(config.OFF_TASK_THRESHOLD_SECONDS, int)
    assert isinstance(config.INTERVENTION_COOLDOWN_SECONDS, int)
    assert isinstance(config.FOCUS_STREAK_THRESHOLD_SECONDS, int)
    assert isinstance(config.MAX_SNAPSHOT_HISTORY, int)

def test_config_heuristic_lists_are_sets():
    assert isinstance(config.KNOWN_DISTRACTION_DOMAINS, set)
    assert isinstance(config.KNOWN_STUDY_DOMAINS, set)
    assert isinstance(config.KNOWN_DISTRACTION_PROCESSES, set)
    assert isinstance(config.KNOWN_STUDY_PROCESSES, set)

def test_known_distractions_includes_youtube():
    assert "youtube.com" in config.KNOWN_DUAL_USE_DOMAINS

def test_known_study_includes_khanacademy():
    assert "khanacademy.org" in config.KNOWN_STUDY_DOMAINS

def test_mempalace_palace_path_exists():
    assert hasattr(config, "MEMPALACE_PALACE_PATH")
    assert isinstance(config.MEMPALACE_PALACE_PATH, str)
    assert len(config.MEMPALACE_PALACE_PATH) > 0

# --- Phase 3 & 4 additions ---

def test_deepseek_model_is_defined():
    assert isinstance(config.DEEPSEEK_MODEL, str)
    assert len(config.DEEPSEEK_MODEL) > 0

def test_deepseek_api_key_is_defined():
    assert isinstance(config.DEEPSEEK_API_KEY, str)

def test_fish_audio_reference_id_is_defined():
    assert isinstance(config.FISH_AUDIO_REFERENCE_ID, str)

def test_tts_output_format_is_defined():
    assert isinstance(config.TTS_OUTPUT_FORMAT, str)
    assert "pcm" in config.TTS_OUTPUT_FORMAT

def test_tts_sample_rate_is_defined():
    assert isinstance(config.TTS_SAMPLE_RATE, int)
    assert config.TTS_SAMPLE_RATE > 0
