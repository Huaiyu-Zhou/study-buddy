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


# --- Dynamic Classification Tests ---

from config import (
    strip_www,
    add_dynamic_classification,
    delete_dynamic_classification,
    load_dynamic_rules,
    _save_rules,
    DYNAMIC_RULES_PATH,
    KNOWN_STUDY_DOMAINS,
    KNOWN_DISTRACTION_PROCESSES,
    KNOWN_STUDY_PROCESSES
)

def test_strip_www():
    assert strip_www("www.google.com") == "google.com"
    assert strip_www("google.com") == "google.com"
    assert strip_www("www.com") == "com"
    assert strip_www("ww.google.com") == "ww.google.com"


def test_add_dynamic_classification():
    import os
    # Backup current rules if file exists
    backup_exists = os.path.exists(DYNAMIC_RULES_PATH)
    backup_content = None
    if backup_exists:
        with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
            backup_content = f.read()

    try:
        # Test add classification for a domain with www.
        add_dynamic_classification("www.test-domain.com", is_domain=True, status="study")
        assert "test-domain.com" in KNOWN_STUDY_DOMAINS
        assert "www.test-domain.com" not in KNOWN_STUDY_DOMAINS

        # Test add classification for process (which shouldn't strip www. if it's a process name)
        add_dynamic_classification("www.exe", is_domain=False, status="distraction")
        assert "www.exe" in KNOWN_DISTRACTION_PROCESSES
    finally:
        # Restore backup
        if backup_exists and backup_content is not None:
            with open(DYNAMIC_RULES_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)
            load_dynamic_rules()


def test_delete_dynamic_classification():
    import os
    backup_exists = os.path.exists(DYNAMIC_RULES_PATH)
    backup_content = None
    if backup_exists:
        with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
            backup_content = f.read()

    try:
        add_dynamic_classification("www.test-domain.com", is_domain=True, status="study")
        delete_dynamic_classification("WWW.TEST-DOMAIN.COM", is_domain=True)
        assert "test-domain.com" not in KNOWN_STUDY_DOMAINS

        add_dynamic_classification("www.exe", is_domain=False, status="distraction")
        delete_dynamic_classification("www.exe", is_domain=False)
        assert "www.exe" not in KNOWN_DISTRACTION_PROCESSES
    finally:
        # Restore backup
        if backup_exists and backup_content is not None:
            with open(DYNAMIC_RULES_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)
            load_dynamic_rules()


def test_load_dynamic_rules():
    import os
    backup_exists = os.path.exists(DYNAMIC_RULES_PATH)
    backup_content = None
    if backup_exists:
        with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
            backup_content = f.read()

    try:
        add_dynamic_classification("testprocess.exe", is_domain=False, status="study")
        load_dynamic_rules()
        assert "testprocess.exe" in KNOWN_STUDY_PROCESSES
    finally:
        # Restore backup
        if backup_exists and backup_content is not None:
            with open(DYNAMIC_RULES_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)
            load_dynamic_rules()


def test_save_rules():
    import os
    import json
    backup_exists = os.path.exists(DYNAMIC_RULES_PATH)
    backup_content = None
    if backup_exists:
        with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
            backup_content = f.read()

    try:
        KNOWN_STUDY_PROCESSES.add("save-test-process.exe")
        _save_rules()
        assert os.path.exists(DYNAMIC_RULES_PATH)
        with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
            rules = json.load(f)
        assert "save-test-process.exe" in rules.get("study_processes", [])
    finally:
        # Restore backup
        if backup_exists and backup_content is not None:
            with open(DYNAMIC_RULES_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)
            load_dynamic_rules()



