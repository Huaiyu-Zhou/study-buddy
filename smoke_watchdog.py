"""
Temporary smoke test — run this manually to verify the watchdog works on your machine.
Polls every 5 seconds for 60 seconds and prints a log of every window snapshot.
Delete this file after you're satisfied.

Usage: python smoke_watchdog.py
"""
import asyncio
import logging
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

config.WATCHDOG_INTERVAL_SECONDS = 5  # speed up for smoke test


async def print_off_task(snapshot, session):
    print(f"  [OFF-TASK] {snapshot.process} | {snapshot.window_title} | url={snapshot.url}")


async def main():
    from watchdog import watchdog_loop
    from session import Session

    session = Session(plan="calculus revision")
    print("Watching for 60 seconds. Switch windows to test classifications.")
    print("On-task processes include: code.exe, pycharm64.exe, acrobat.exe")
    print("Off-task domains include: youtube.com, reddit.com, netflix.com\n")

    try:
        await asyncio.wait_for(watchdog_loop(session, print_off_task), timeout=60)
    except asyncio.TimeoutError:
        pass

    print(f"\nDone. {len(session.snapshot_history)} snapshots captured.")
    for s in session.snapshot_history:
        label = {True: "ON ", False: "OFF", None: "???"}[s.is_on_task]
        print(f"  {s.timestamp:%H:%M:%S} | {label} | {s.process:20s} | {s.window_title[:50]}")


asyncio.run(main())
