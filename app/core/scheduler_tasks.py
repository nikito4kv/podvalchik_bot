import logging
from app.scripts.migrate_seasons import migrate_seasons

async def scheduled_season_rotation():
    """
    Task to rotate seasons.
    Checks dates, creates new seasons if needed, calculates results.
    """
    logging.info("⏳ Scheduled Task: Rotating Season...")
    await migrate_seasons()
    logging.info("✅ Scheduled Task: Season Rotation Complete.")
