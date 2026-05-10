import asyncio
import logging
import sys
import os
from voice_pipeline import StudyBuddyVoicePipeline
from watchdog import watchdog_loop
from session import Session
import config

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("study_buddy")

async def main():
    # Check for critical API keys before starting
    missing_keys = []
    if not config.DEEPSEEK_API_KEY:
        missing_keys.append("DEEPSEEK_API_KEY")
    if not config.FISH_AUDIO_API_KEY:
        missing_keys.append("FISH_AUDIO_API_KEY")
    if not config.DEEPGRAM_API_KEY:
        missing_keys.append("DEEPGRAM_API_KEY")
    
    if missing_keys:
        logger.error(f"Missing API keys in .env: {', '.join(missing_keys)}")
        logger.error("Please fill in these keys before starting the coach.")
        return

    logger.info("Initializing Study Buddy Session...")
    session = Session()
    pipeline = StudyBuddyVoicePipeline(session)

    logger.info("Starting Activity Watchdog...")
    # The watchdog loop calls the pipeline's intervention logic when off-task
    watchdog_task = asyncio.create_task(
        watchdog_loop(session, on_off_task=lambda snap, sess: pipeline.maybe_intervene())
    )

    try:
        logger.info("Starting Voice Pipeline. The coach will greet you shortly...")
        # Start the voice pipeline (blocks until session ends)
        await pipeline.start()
    except KeyboardInterrupt:
        logger.info("Session interrupted by user.")
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
    finally:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        logger.info("Session ended. Good job studying!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
