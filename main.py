import os
import sys
import argparse
import asyncio
import logging
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

OUTPUT_DIR = "notion_output"


async def run_sync_job(force: bool = False, skip_analyze: bool = False, with_analyze: bool = False):
    from app.jobs.sync_notion import SyncNotionJob
    from app.services.git_service import GitService
    from app.jobs.analyze_notes import AnalyzeNotesJob

    logger.info("Starting sync job...")
    
    should_run_analyze = True
    last_sync_time = SyncNotionJob.load_state()
    is_full_sync = force or (last_sync_time is None)
    
    if skip_analyze:
        should_run_analyze = False
    elif is_full_sync:
        if with_analyze:
            should_run_analyze = True
        else:
            logger.info("Full sync detected. Analysis is disabled by default to save tokens. Use --with-analyze to enable.")
            should_run_analyze = False
    
    try:
        git_service = GitService(OUTPUT_DIR)
        git_service.init_repo()
        git_service.pull_latest()
    except Exception as e:
        logger.warning(f"Git service initialization failed: {e}")
        git_service = None

    job = SyncNotionJob()
    changed_files = await job.sync_incremental(force=force)
    
    if git_service:
        try:
            git_service.sync_changes()
        except Exception as e:
            logger.warning(f"Git sync failed: {e}")

    if changed_files and should_run_analyze:
        analyze_job = AnalyzeNotesJob()
        try:
            await analyze_job.analyze_changes([str(f) for f in changed_files])
        except Exception as e:
            logger.error(f"Error running analyze job: {e}")
    
    logger.info("Sync job completed.")


async def run_morning_job():
    from app.jobs.routines import DailyRoutines
    
    logger.info("Starting morning routine job...")
    try:
        job = DailyRoutines()
        success = await job.morning_routine()
        if success:
            logger.info("Morning routine completed successfully.")
        else:
            logger.warning("Morning routine completed with issues.")
    except Exception as e:
        logger.error(f"Morning routine failed: {e}")
        sys.exit(1)


async def run_weekly_job():
    from app.jobs.routines import DailyRoutines
    
    logger.info("Starting weekly review job...")
    try:
        job = DailyRoutines()
        success = await job.weekly_review()
        if success:
            logger.info("Weekly review completed successfully.")
        else:
            logger.warning("Weekly review completed with issues.")
    except Exception as e:
        logger.error(f"Weekly review failed: {e}")
        sys.exit(1)


async def run_analyze_job(file_paths: list = None):
    from app.jobs.analyze_notes import AnalyzeNotesJob
    
    logger.info("Starting analyze job...")
    
    if file_paths:
        files_to_analyze = [Path(f) for f in file_paths]
        valid_files = [f for f in files_to_analyze if f.exists() and f.suffix == ".md"]
        if not valid_files:
            logger.warning("No valid markdown files found in provided paths.")
            return
        logger.info(f"Analyzing {len(valid_files)} specified files.")
    else:
        notion_output = Path(OUTPUT_DIR)
        if not notion_output.exists():
            logger.warning(f"Output directory {OUTPUT_DIR} not found.")
            return
        
        valid_files = list(notion_output.glob("**/*.md"))
        if not valid_files:
            logger.info("No markdown files found to analyze.")
            return
        logger.info(f"Found {len(valid_files)} markdown files to analyze.")
    
    job = AnalyzeNotesJob()
    try:
        await job.analyze_changes([str(f) for f in valid_files])
        logger.info("Analyze job completed.")
    except Exception as e:
        logger.error(f"Analyze job failed: {e}")


async def run_review_job(start_date: datetime.date, end_date: datetime.date):
    from app.jobs.periodic_review import PeriodicReviewJob

    logger.info("Starting periodic review job...")

    job = PeriodicReviewJob()
    try:
        report_path = await job.run(start_date=start_date, end_date=end_date)
        logger.info(f"Periodic review completed: {report_path}")
    except Exception as e:
        logger.error(f"Periodic review failed: {e}")
        sys.exit(1)


def _parse_yyyy_mm_dd(date_str: str) -> datetime.date:
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()


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
  python main.py --job analyze                 # Analyze all files in notion_output/
  python main.py --job analyze file1.md file2.md  # Analyze specific files
  python main.py --job review --start-date 2026-03-01 --end-date 2026-03-07  # Periodic diary review
  python main.py --job bot                     # Start Telegram Bot
        """
    )
    
    parser.add_argument(
        "--job",
        choices=["sync", "morning", "weekly", "analyze", "review", "bot"],
        default="sync",
        help="Job type to run: sync (default), morning, weekly, analyze, review, or bot"
    )
    parser.add_argument(
        "--force", "--full",
        action="store_true",
        help="Force full sync (only for sync job)"
    )
    parser.add_argument(
        "--skip-analyze",
        action="store_true",
        help="Skip AI analysis of changed files (only for sync job)"
    )
    parser.add_argument(
        "--with-analyze",
        action="store_true",
        help="Force enable AI analysis even during full sync (only for sync job)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Log level to use (default: INFO)"
    )
    parser.add_argument(
        "--start-date",
        help="Start date for review job in YYYY-MM-DD (local time, Asia/Shanghai)"
    )
    parser.add_argument(
        "--end-date",
        help="End date for review job in YYYY-MM-DD (local time, Asia/Shanghai). Defaults to today."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files to analyze (only for analyze job). If not specified, analyzes all files in notion_output/"
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info(f"Running job: {args.job}")
    
    if args.job == "sync":
        asyncio.run(run_sync_job(
            force=args.force,
            skip_analyze=args.skip_analyze,
            with_analyze=args.with_analyze
        ))
    elif args.job == "morning":
        asyncio.run(run_morning_job())
    elif args.job == "weekly":
        asyncio.run(run_weekly_job())
    elif args.job == "analyze":
        asyncio.run(run_analyze_job(args.files))
    elif args.job == "review":
        if not args.start_date:
            parser.error("--start-date is required for review job (YYYY-MM-DD)")
        try:
            start_date = _parse_yyyy_mm_dd(args.start_date)
        except ValueError:
            parser.error("--start-date must be in YYYY-MM-DD format")
        if args.end_date:
            try:
                end_date = _parse_yyyy_mm_dd(args.end_date)
            except ValueError:
                parser.error("--end-date must be in YYYY-MM-DD format")
        else:
            end_date = datetime.datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if end_date < start_date:
            parser.error("--end-date must be >= --start-date")
        asyncio.run(run_review_job(start_date=start_date, end_date=end_date))
    elif args.job == "bot":
        from app.jobs.bot_runner import TelegramBotRunner
        runner = TelegramBotRunner()
        logger.info("Starting Telegram Bot Polling...")
        runner.start_polling()
    else:
        logger.error(f"Unknown job type: {args.job}")
        sys.exit(1)


if __name__ == "__main__":
    main()
