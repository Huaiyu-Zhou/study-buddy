import asyncio
import logging
import aiohttp

from watchdog import get_active_window_info, get_idle_seconds, get_browser_url, terminate_process, CHROMIUM_PROCESSES
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("win_watchdog")

SERVER_URL = "http://localhost:7860/activity"

async def run_watchdog():
    logger.info("Windows watchdog client started. Sending updates to %s", SERVER_URL)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                process, title, pid = get_active_window_info()
                idle = get_idle_seconds()
                url = get_browser_url(process)

                # Fallback: if URL extraction failed for a browser, try to
                # match known domain keywords from the window title.
                if not url and process in CHROMIUM_PROCESSES and title:
                    title_lower = title.lower()
                    all_domains = (
                        config.KNOWN_DISTRACTION_DOMAINS
                        | config.KNOWN_STUDY_DOMAINS
                        | config.KNOWN_DUAL_USE_DOMAINS
                    )
                    for domain in all_domains:
                        keyword = domain.split('.')[0]
                        if keyword in title_lower:
                            url = f"https://{domain}"
                            logger.info(
                                "Fallback: extracted URL from title: %r -> %s",
                                title, url,
                            )
                            break

                payload = {
                    "process": process,
                    "window_title": title,
                    "url": url,
                    "idle_seconds": idle,
                    "pid": pid
                }
                
                async with session.post(SERVER_URL, json=payload, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "no_active_session":
                            logger.info("Server running, but no active study session is running.")
                        else:
                            logger.info(
                                "Sent window state: %s | distractions: %d | break: %s",
                                process,
                                data.get("distraction_count", 0),
                                data.get("is_on_break", False)
                            )

                            action = data.get("action")
                            if action == "close_process":
                                target_pid = data.get("target_pid")
                                target_process = data.get("target_process")
                                logger.warning("Server requested to close distracting process: %s (PID: %s)", target_process, target_pid)
                                terminate_process(target_pid, target_process)
                            elif action == "close_tab":
                                target_process = data.get("target_process")
                                current_process, _, _ = get_active_window_info()
                                if current_process == target_process:
                                    logger.warning("Server requested to close distracting tab. Simulating Ctrl+W for: %s", target_process)
                                    try:
                                        import ctypes
                                        import time
                                        # Simulate Ctrl+W
                                        ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
                                        time.sleep(0.05)
                                        ctypes.windll.user32.keybd_event(0x57, 0, 0, 0)  # W down
                                        time.sleep(0.05)
                                        ctypes.windll.user32.keybd_event(0x57, 0, 2, 0)  # W up
                                        time.sleep(0.05)
                                        ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
                                    except Exception as e:
                                        logger.error("Failed to simulate Ctrl+W: %s", e)
                                else:
                                    logger.info("Foreground process changed from %s to %s. Aborting Ctrl+W.", target_process, current_process)
                    else:
                        logger.warning("Failed to send window state: HTTP %d", response.status)
                        
            except aiohttp.ClientConnectorError:
                logger.warning("Failed to connect to Study Buddy Server. Is it running?")
            except Exception as e:
                logger.exception("Error in watchdog loop: %s", e)
                
            await asyncio.sleep(config.WATCHDOG_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        asyncio.run(run_watchdog())
    except KeyboardInterrupt:
        logger.info("Watchdog client stopped by user.")
