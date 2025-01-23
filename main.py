#!/usr/bin/env python3

import logging
import os
import re
import socket
import time

import heroku3
import sentry_sdk
from cloudflare import Cloudflare
from dotenv import load_dotenv
from heroku3.models.app import App

logger = logging.getLogger("heroku-cloudflare-app-domain")
logging_handler = logging.StreamHandler()
logging_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
)
logger.addHandler(logging_handler)

SUCCESS_ACM_STATUS = {
    "cert issued",
    "pending",  # Assume this is ok. It'll be picked up on next iteration if it's not
}

ALLOWED_CNAME_TARGETS = [
    re.compile(t) for t in os.environ.get("ALLOWED_CNAME_TARGETS", "").split(",")
]


class FakeDomain:
    """
    A fake Domain object to stand in for Heroku's domain.
    """

    acm_status = True

    def __init__(self, hostname):
        self.domain = self.hostname = hostname


def enable_acm(app):
    app._h._http_resource(
        method="POST", resource=("apps", app.id, "acm")
    ).raise_for_status()


def get_apps_for_teams(heroku, teams):
    for team in teams:
        yield from heroku._get_resources(("teams", team, "apps"), App)


def record_exists(record: str) -> bool:
    """
    Determines whether a DNS record exists
    """
    try:
        socket.getaddrinfo(record, None)
    except socket.gaierror:
        return False
    return True


def is_allowed_cname_target(record: str) -> bool:
    """
    Is the record an allowed target
    """
    return any(target.match(record) for target in ALLOWED_CNAME_TARGETS)


def main():
    load_dotenv()

    if sentry_dsn := os.environ.get("SENTRY_DSN"):
        sentry_sdk.init(sentry_dsn)

    logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO")))

    cf = Cloudflare()

    heroku = heroku3.from_key(os.getenv("HEROKU_API_KEY"))

    interval = int(os.getenv("INTERVAL", 0))
    matcher = re.compile(os.getenv("APP_NAME", r".*"))
    heroku_teams = (
        os.getenv("HEROKU_TEAMS").split(",") if "HEROKU_TEAMS" in os.environ else None
    )

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    if interval:
        while True:
            do_create(cf, heroku, matcher, heroku_teams, dry_run)
            time.sleep(interval)
    else:
        do_create(cf, heroku, matcher, heroku_teams, dry_run)


def do_create(cf: Cloudflare, heroku, matcher, heroku_teams, dry_run):
    cf_zone = cf.zones.get(zone_id=os.environ["CLOUDFLARE_ZONE_ID"])

    all_records = {
        record.name: record
        for record in cf.dns.records.list(zone_id=cf_zone.id, type="CNAME")
    }

    heroku_apps = list(
        heroku.apps()
        if heroku_teams is None
        else get_apps_for_teams(heroku, heroku_teams)
    )

    known_records = set()

    logger.info("Checking %d apps", len(heroku_apps))

    for app in heroku_apps:
        if matcher.match(app.name) is None:
            continue

        app_domain = f"{app.name}.{cf_zone.name}"
        app_domains = {domain.hostname: domain for domain in app.domains()}

        existing_record = all_records.get(app_domain)

        # Add the domain to Heroku if it doesn't know about it
        if app_domain not in app_domains:
            logger.info("%s: domain not set in Heroku", app.name)
            if dry_run:
                app_domains[app_domain] = FakeDomain("example.herokudns.com")
            else:
                new_heroku_domain = app.add_domain(app_domain, sni_endpoint=None)
                app_domains[new_heroku_domain.hostname] = new_heroku_domain

        # This saves refreshing for the whole app, which can be noisy
        if not dry_run and app_domains[app_domain].acm_status not in SUCCESS_ACM_STATUS:
            logger.debug("%s: cycling domain to refresh ACM", app.name)
            app.remove_domain(app_domain)
            new_heroku_domain = app.add_domain(app_domain, sni_endpoint=None)
            app_domains[new_heroku_domain.hostname] = new_heroku_domain

        cname = getattr(app_domains.get(app_domain), "cname", None)
        cf_record_data = {
            "name": app.name,
            "type": "CNAME",
            "content": cname,
        }

        if existing_record is None:
            logger.info("%s: domain not set", app.name)
            if not dry_run:
                cf.dns.records.create(zone_id=cf_zone.id, **cf_record_data)
        elif existing_record.content != cname:
            if is_allowed_cname_target(existing_record.content):
                logger.warning(
                    "%s: record is different, but an allowed value", app.name
                )
            else:
                logger.warning("%s: incorrect record value", app.name)
                if not dry_run:
                    cf.dns.records.edit(
                        zone_id=cf_zone.id,
                        dns_record_id=existing_record.id,
                        **cf_record_data,
                    )
        else:
            logger.debug("%s: No action needed", app.name)

        # Enable ACM if not already, so certs can be issued
        has_acm = any(d.acm_status for d in app_domains.values())
        if not has_acm:
            logger.info("Enabling ACM for %s", app.name)
            if not dry_run:
                enable_acm(app)

        known_records.add(app_domain)

    # Delete heroku records which don't exist anymore
    # This intentionally doesn't contain records we just created, so the records propagate
    for existing_record in all_records.values():
        existing_value = existing_record.content
        if (
            existing_record.name not in known_records
            and existing_value.endswith("herokudns.com")
            and not record_exists(existing_value)
        ):
            logger.warning("%s: stale heroku domain", existing_value)
            cf.dns.records.delete(existing_record.id, zone_id=cf_zone.id)


if __name__ == "__main__":
    main()
