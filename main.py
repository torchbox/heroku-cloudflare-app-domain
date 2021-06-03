import os
import time

import CloudFlare
import heroku3
import sentry_sdk
from dotenv import load_dotenv


def main():
    load_dotenv()

    if sentry_dsn := os.environ.get("SENTRY_DSN"):
        sentry_sdk.init(sentry_dsn)

    cf = CloudFlare.CloudFlare(raw=True)

    heroku = heroku3.from_key(os.getenv("HEROKU_API_KEY"))

    interval = int(os.getenv("INTERVAL", 0))

    if interval:
        while True:
            do_updates(cf, heroku)
            time.sleep(interval)
    else:
        do_updates(cf, heroku)


def do_updates(cf, heroku):
    pass


if __name__ == "__main__":
    main()
