#!/usr/bin/env python3

import logging
import os
import re
import socket
import time
from typing import Any, Iterator, cast

import httpx
import sentry_sdk
from cloudflare import Cloudflare
from dotenv import load_dotenv

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


HEROKU_API = "https://api.heroku.com"


def heroku_api(
    session: httpx.Client, method: str, path: str, **kwargs: Any
) -> list[Any] | dict[str, Any]:
    resp = session.request(method, f"{HEROKU_API}{path}", **kwargs)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def heroku_api_list(session: httpx.Client, path: str) -> Iterator[dict[str, Any]]:
    """GET a paginated Heroku list endpoint, yielding all items across pages."""
    next_range = None
    while True:
        headers: dict[str, Any] = {"Range": next_range} if next_range else {}
        resp = session.get(f"{HEROKU_API}{path}", headers=headers)
        resp.raise_for_status()
        yield from resp.json()
        next_range = resp.headers.get("Next-Range")
        if not next_range:
            break


def enable_acm(heroku_session: httpx.Client, app_name: str) -> None:
    heroku_api(heroku_session, "POST", f"/apps/{app_name}/acm")


def get_apps_for_teams(
    heroku_session: httpx.Client, teams: list[str]
) -> Iterator[dict[str, Any]]:
    for team in teams:
        yield from heroku_api_list(heroku_session, f"/teams/{team}/apps")


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


def get_heroku_session() -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(retries=3),
        headers={
            "Accept": "application/vnd.heroku+json; version=3",
            "Authorization": f"Bearer {os.getenv('HEROKU_API_KEY')}",
        },
    )


def main() -> None:
    load_dotenv()

    if sentry_dsn := os.environ.get("SENTRY_DSN"):
        sentry_sdk.init(sentry_dsn)

    logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO")))

    cf = Cloudflare()

    interval = int(os.getenv("INTERVAL", 0))
    matcher = re.compile(os.getenv("APP_NAME", r".*"))
    heroku_teams = os.getenv("HEROKU_TEAMS", "").split(",") or None

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    with get_heroku_session() as heroku_session:
        if interval:
            while True:
                do_create(cf, heroku_session, matcher, heroku_teams, dry_run)
                time.sleep(interval)
        else:
            do_create(cf, heroku_session, matcher, heroku_teams, dry_run)


def do_create(
    cf: Cloudflare,
    heroku_session: httpx.Client,
    matcher: re.Pattern[str],
    heroku_teams: list[str] | None,
    dry_run: bool,
) -> None:
    cf_zone = cf.zones.get(zone_id=os.environ["CLOUDFLARE_ZONE_ID"])

    if cf_zone is None:
        raise ValueError("Unknown zone")

    all_records = {
        record.name: record
        for record in cf.dns.records.list(zone_id=cf_zone.id, type="CNAME")
    }

    if heroku_teams is None:
        heroku_apps = list(heroku_api_list(heroku_session, "/apps"))
    else:
        heroku_apps = list(get_apps_for_teams(heroku_session, heroku_teams))

    known_records = set()

    logger.info("Checking %d apps", len(heroku_apps))

    for app in heroku_apps:
        if matcher.match(app["name"]) is None:
            continue

        app_domain = f"{app['name']}.{cf_zone.name}"
        app_domains: dict[str, dict] = {
            d["hostname"]: d  # type: ignore[index,misc]
            for d in heroku_api(heroku_session, "GET", f"/apps/{app['name']}/domains")
        }

        existing_record = all_records.get(app_domain)

        # Add the domain to Heroku if it doesn't know about it
        if app_domain not in app_domains:
            logger.info("%s: domain not set in Heroku", app["name"])
            if dry_run:
                app_domains[app_domain] = {
                    "hostname": "example.herokudns.com",
                    "acm_status": True,
                    "cname": None,
                }
            else:
                new_heroku_domain = cast(
                    dict,
                    heroku_api(
                        heroku_session,
                        "POST",
                        f"/apps/{app['name']}/domains",
                        json={"hostname": app_domain, "sni_endpoint": None},
                    ),
                )
                app_domains[new_heroku_domain["hostname"]] = new_heroku_domain

        # This saves refreshing for the whole app, which can be noisy
        if (
            not dry_run
            and app_domains[app_domain]["acm_status"] not in SUCCESS_ACM_STATUS
        ):
            logger.debug("%s: cycling domain to refresh ACM", app["name"])
            heroku_api(
                heroku_session, "DELETE", f"/apps/{app['name']}/domains/{app_domain}"
            )
            new_heroku_domain = cast(
                dict,
                heroku_api(
                    heroku_session,
                    "POST",
                    f"/apps/{app['name']}/domains",
                    json={"hostname": app_domain, "sni_endpoint": None},
                ),
            )
            app_domains[new_heroku_domain["hostname"]] = new_heroku_domain

        cname = app_domains.get(app_domain, {}).get("cname")
        cf_record_data = {
            "name": app["name"],
            "type": "CNAME",
            "content": cname,
        }

        if existing_record is None or not existing_record.content:
            logger.info("%s: domain not set", app["name"])
            if not dry_run:
                cf.dns.records.create(zone_id=cf_zone.id, **cf_record_data)
        elif existing_record.content != cname:
            if is_allowed_cname_target(existing_record.content):
                logger.warning(
                    "%s: record is different, but an allowed value", app["name"]
                )
            else:
                logger.warning("%s: incorrect record value", app["name"])
                if not dry_run:
                    cf.dns.records.edit(
                        zone_id=cf_zone.id,
                        dns_record_id=existing_record.id,
                        **cf_record_data,
                    )
        else:
            logger.debug("%s: No action needed", app["name"])

        # Enable ACM if not already, so certs can be issued
        has_acm = any(d["acm_status"] for d in app_domains.values())
        if not has_acm:
            logger.info("Enabling ACM for %s", app["name"])
            if not dry_run:
                enable_acm(heroku_session, app["name"])

        known_records.add(app_domain)

    # Delete heroku records which don't exist anymore
    # This intentionally doesn't contain records we just created, so the records propagate
    for existing_record in all_records.values():
        existing_value = existing_record.content
        if (
            existing_value
            and existing_record.name not in known_records
            and existing_value.endswith("herokudns.com")
            and not record_exists(existing_value)
        ):
            logger.warning("%s: stale heroku domain", existing_value)
            cf.dns.records.delete(existing_record.id, zone_id=cf_zone.id)


if __name__ == "__main__":
    main()
