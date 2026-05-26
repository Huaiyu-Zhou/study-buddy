import logging
import time
import requests

from watchdog import get_active_window_info, get_idle_seconds, get_browser_url
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("win_watchdog")

SERVER_URL = "http://localhost:7860/activity"

def run_watchdog():
    logger.info("Windows watchdog client started. Sending updates to %s", SERVER_URL)
    while True:
        try:
            process, title = get_active_window_info()
            idle = get_idle_seconds()
            url = get_browser_url(process)
            
            payload = {
                "process": process,
                "window_title": title,
                "url": url,
                "idle_seconds": idle
            }
            
            response = requests.post(SERVER_URL, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "no_active_session":
                    logger.info("Server running, but no active study session is running.")
                else:
                    logger.info(
                        "Sent window state: %s | distractions: %d | break: %s",
                        process,
                        data.get("distraction_count", 0),
                        data.get("is_on_break", False)
                    )
            else:
                logger.warning("Failed to send window state: HTTP %d", response.status_code)
                
        except requests.exceptions.ConnectionError:
            logger.warning("Failed to connect to Study Buddy Server. Is it running?")
        except Exception as e:
            logger.exception("Error in watchdog loop: %s", e)
            
        time.sleep(config.WATCHDOG_INTERVAL_SECONDS)

if __name__ == "__main__":
    run_watchdog()
