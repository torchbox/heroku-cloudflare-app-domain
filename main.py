#!/usr/bin/env python3

import os
import re
import time
from itertools import count

import CloudFlare
import heroku3
import sentry_sdk
from dotenv import load_dotenv
from heroku3.models.app import App


SUCCESS_ACM_STATUS = {
    "cert issued",
    "pending",  # Assume this is ok. It'll be picked up on next iteration if it's not
}


def get_cloudflare_list(api, *args, params=None):
    """
    Hack around Cloudflare's API to get all results in a nice way
    """

    for page_num in count(start=1):
        raw_results = api.get(
            *args, params={"page": page_num, "per_page": 50, **(params or {})}
        )

        yield from raw_results["result"]

        total_pages = raw_results["result_info"]["total_pages"]
        if page_num == total_pages:
            break


def enable_acm(app):
    print("Enabling ACM for", app.name)
    app._h._http_resource(
        method="POST", resource=("apps", app.id, "acm")
    ).raise_for_status()


def get_apps_for_teams(heroku, teams):
    for team in teams:
        yield from heroku._get_resources(("teams", team, "apps"), App)


def main():
    load_dotenv()

    if sentry_dsn := os.environ.get("SENTRY_DSN"):
        sentry_sdk.init(sentry_dsn)

    cf = CloudFlare.CloudFlare(raw=True)

    heroku = heroku3.from_key(os.getenv("HEROKU_API_KEY"))

    interval = int(os.getenv("INTERVAL", 0))
    matcher = re.compile(os.getenv("APP_NAME", r".*"))
    heroku_teams = (
        os.getenv("HEROKU_TEAMS").split(",") if "HEROKU_TEAMS" in os.environ else None
    )

    if interval:
        while True:
            do_create(cf, heroku, matcher, heroku_teams)
            time.sleep(interval)
    else:
        do_create(cf, heroku, matcher, heroku_teams)


def do_create(cf, heroku, matcher, heroku_teams):
    cf_zone = cf.zones.get(os.environ["CF_ZONE_ID"])["result"]

    all_records = {
        record["name"]: record
        for record in get_cloudflare_list(
            cf.zones.dns_records, cf_zone["id"], params={"type": "CNAME"}
        )
    }

    heroku_apps = (
        heroku.apps()
        if heroku_teams is None
        else get_apps_for_teams(heroku, heroku_teams)
    )

    for app in heroku_apps:
        if matcher.match(app.name) is None:
            continue

        app_domain = f"{app.name}.{cf_zone['name']}"
        app_domains = {domain.hostname: domain for domain in app.domains()}

        existing_record = all_records.get(app_domain)

        # Add the domain to Heroku if it doesn't know about it
        if app_domain not in app_domains:
            print(app.name, "domain not set in Heroku")
            new_heroku_domain = app.add_domain(app_domain)
            app_domains[new_heroku_domain.hostname] = new_heroku_domain

        # This saves refreshing for the whole app, which can be noisy
        if app_domains[app_domain].acm_status not in SUCCESS_ACM_STATUS:
            print(app.name, "cycling domain to refresh ACM", app_domains[app_domain].acm_status)
            app.remove_domain(app_domain)
            new_heroku_domain = app.add_domain(app_domain)
            app_domains[new_heroku_domain.hostname] = new_heroku_domain

        cname = getattr(app_domains.get(app_domain), "cname", None)
        cf_record_data = {
            "name": app.name,
            "type": "CNAME",
            "content": cname,
        }

        if existing_record is None:
            print(app.name, "domain not set")
            cf.zones.dns_records.post(cf_zone["id"], data=cf_record_data)
        elif cname == existing_record["content"]:
            print(app.name, "domain set correctly")
        else:
            print(app.name, "incorrect record value")
            cf.zones.dns_records.patch(
                cf_zone["id"], existing_record["id"], data=cf_record_data
            )

        # Enable ACM if not already, so certs can be issued
        has_acm = any(d.acm_status for d in app_domains.values())
        if not has_acm:
            enable_acm(app)


if __name__ == "__main__":
    main()
