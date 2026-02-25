import os
import sys
import argparse
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent / "app"))

from download_notion import sync_incremental, load_state
from observer import ContentObserver
from services.git_service import GitService
from jobs.routines import DailyRoutines

OUTPUT_DIR = "notion_output"


def run_sync_job(force: bool = False, skip_observer: bool = False, with_observer: bool = False):
    logger.info("Starting sync job...")
    
    should_run_observer = True
    last_sync_time = load_state()
    is_full_sync = force or (last_sync_time is None)
    
    if skip_observer:
        should_run_observer = False
    elif is_full_sync:
        if with_observer:
            should_run_observer = True
        else:
            logger.info("Full sync detected. Observer is disabled by default to save tokens. Use --with-observer to enable.")
            should_run_observer = False
    
    try:
        git_service = GitService(OUTPUT_DIR)
        git_service.init_repo()
        git_service.pull_latest()
    except Exception as e:
        logger.warning(f"Git service initialization failed: {e}")
        git_service = None

    changed_files = sync_incremental(force=force)
    
    if git_service:
        try:
            git_service.sync_changes()
        except Exception as e:
            logger.warning(f"Git sync failed: {e}")

    if changed_files and should_run_observer:
        observer = ContentObserver()
        try:
            asyncio.run(observer.analyze_changes(changed_files))
        except Exception as e:
            logger.error(f"Error running observer: {e}")
    
    logger.info("Sync job completed.")


async def run_morning_job():
    logger.info("Starting morning routine job...")
    try:
        routines = DailyRoutines()
        success = await routines.morning_routine()
        if success:
            logger.info("Morning routine completed successfully.")
        else:
            logger.warning("Morning routine completed with issues.")
    except Exception as e:
        logger.error(f"Morning routine failed: {e}")
        sys.exit(1)


async def run_weekly_job():
    logger.info("Starting weekly review job...")
    try:
        routines = DailyRoutines()
        success = await routines.weekly_review()
        if success:
            logger.info("Weekly review completed successfully.")
        else:
            logger.warning("Weekly review completed with issues.")
    except Exception as e:
        logger.error(f"Weekly review failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Notion Dump - AI-powered knowledge management assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --job sync                    # Run incremental sync
  python main.py --job sync --force            # Force full sync
  python main.py --job morning                 # Run morning routine
  python main.py --job weekly                  # Run weekly review
        """
    )
    
    parser.add_argument(
        "--job",
        choices=["sync", "morning", "weekly"],
        default="sync",
        help="Job type to run: sync (default), morning, or weekly"
    )
    parser.add_argument(
        "--force", "--full",
        action="store_true",
        help="Force full sync (only for sync job)"
    )
    parser.add_argument(
        "--skip-observer",
        action="store_true",
        help="Skip AI analysis of changed files (only for sync job)"
    )
    parser.add_argument(
        "--with-observer",
        action="store_true",
        help="Force enable AI analysis even during full sync (only for sync job)"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Running job: {args.job}")
    
    if args.job == "sync":
        run_sync_job(
            force=args.force,
            skip_observer=args.skip_observer,
            with_observer=args.with_observer
        )
    elif args.job == "morning":
        asyncio.run(run_morning_job())
    elif args.job == "weekly":
        asyncio.run(run_weekly_job())
    else:
        logger.error(f"Unknown job type: {args.job}")
        sys.exit(1)


if __name__ == "__main__":
    main()
