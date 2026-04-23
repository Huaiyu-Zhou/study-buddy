import logging
from ctypes import cast, POINTER
from typing import Optional

logger = logging.getLogger(__name__)


def _get_mic_volume() -> Optional[object]:
    """Get the IAudioEndpointVolume interface for the default microphone.
    Returns None if no microphone is found or pycaw is unavailable.
    """
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        mic = AudioUtilities.GetMicrophone()
        if mic is None:
            logger.warning("No microphone found.")
            return None
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        logger.warning(f"Failed to access microphone: {e}")
        return None


def mute_mic() -> None:
    """Mute the default system microphone. No-op if unavailable."""
    volume = _get_mic_volume()
    if volume is None:
        return
    volume.SetMute(True, None)
    logger.debug("Microphone muted.")


def unmute_mic() -> None:
    """Unmute the default system microphone. No-op if unavailable."""
    volume = _get_mic_volume()
    if volume is None:
        return
    volume.SetMute(False, None)
    logger.debug("Microphone unmuted.")
