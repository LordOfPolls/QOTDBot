import os
from time import sleep

from source import utilities

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
    from source import bot
    log.info("Ready, calling bot.py")
    bot.run()


if __name__ == '__main__':
    print("""████████▄   ███    █▄     ▄████████    ▄████████ ▄██   ▄   
███    ███  ███    ███   ███    ███   ███    ███ ███   ██▄ 
███    ███  ███    ███   ███    █▀    ███    ███ ███▄▄▄███ 
███    ███  ███    ███  ▄███▄▄▄      ▄███▄▄▄▄██▀ ▀▀▀▀▀▀███ 
███    ███  ███    ███ ▀▀███▀▀▀     ▀▀███▀▀▀▀▀   ▄██   ███ 
███    ███  ███    ███   ███    █▄  ▀███████████ ███   ███ 
███  ▀ ███  ███    ███   ███    ███   ███    ███ ███   ███ 
 ▀██████▀▄█ ████████▀    ██████████   ███    ███  ▀█████▀  
                                      ███    ███           """)
    sleep(1)
    sanityChecks()
    log = utilities.getLog("Main")
    log.info("Logging system started")
    main()
