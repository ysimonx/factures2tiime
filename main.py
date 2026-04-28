import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import storage
from collector import run_collection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    missing = config.validate_config()
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    storage.init_db()
    log.info("Database initialised at %s", config.DB_PATH)

    scheduler = BlockingScheduler(timezone="Europe/Paris")
    scheduler.add_job(
        run_collection,
        CronTrigger(
            day=config.COLLECTION_DAY,
            hour=config.COLLECTION_HOUR,
            minute=0,
            timezone="Europe/Paris",
        ),
        id="monthly_collection",
        misfire_grace_time=86400,
    )

    log.info(
        "Scheduler started — runs on day %d at %02d:00 (Europe/Paris)",
        config.COLLECTION_DAY,
        config.COLLECTION_HOUR,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")


if __name__ == "__main__":
    main()
