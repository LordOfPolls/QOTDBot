import os
from datetime import datetime
from time import sleep

from source import utilities, bot

log = None


def archiveLog() -> bool:
    """Archives the last bot log"""
    if os.path.isfile("data/logs/bot.log"):
        if open("data/logs/bot.log", encoding="utf8").read() == "":
            # if the log is empty there is no need to archive it
            print("Log empty, not archiving")
            try:
                os.unlink("data/logs/bot.log")
            except PermissionError:
                return False
            return True

        print("Archiving log...")
        try:
            now = datetime.now()
            os.rename(
                "data/logs/bot.log",
                f"data/logs/archive/bot {now.year}-{now.month}-{now.day}--{now.hour}-{now.minute}-{now.second}.log")
            sleep(1)
        except Exception as e:
            print(f"Failed to archive log: {e}")
            return False
        return True


def sanityChecks() -> bool:
    try:
        if not os.path.exists("data"):
            os.makedirs("data")
        if not os.path.exists("data/logs"):
            os.makedirs("data/logs")
        if not os.path.exists("data/logs/archive"):
            os.makedirs("data/logs/archive")

        if archiveLog():
            print("Creating new log file...")
            open("data/logs/bot.log", "w").close()
            sleep(1)

    except Exception as e:
        print(e)
        return False
    return True


def main():
    log.info("ready")
    bot.run()


if __name__ == '__main__':
    sanityChecks()
    log = utilities.getLog("Main")
    log.info("Logging system started")
    main()
