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
    assert "youtube.com" in config.KNOWN_DISTRACTION_DOMAINS

def test_known_study_includes_khanacademy():
    assert "khanacademy.org" in config.KNOWN_STUDY_DOMAINS

def test_mempalace_palace_path_exists():
    assert hasattr(config, "MEMPALACE_PALACE_PATH")
    assert isinstance(config.MEMPALACE_PALACE_PATH, str)
    assert len(config.MEMPALACE_PALACE_PATH) > 0
