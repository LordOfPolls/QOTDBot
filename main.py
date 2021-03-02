import os
from datetime import datetime
from time import sleep

from source import utilities, bot

log = None


def sanityChecks() -> bool:
    try:
        if not os.path.exists("data"):
            os.makedirs("data")
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
