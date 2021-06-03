import os
import time
from collections import count

import CloudFlare
import heroku3
import sentry_sdk
from dotenv import load_dotenv


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


def refresh_acm(app):
    print("Refreshing ACM for", app.name)
    app._h._http_resource(
        method="PATCH", resource=("apps", app.id, "acm")
    ).raise_for_status()


def main():
    load_dotenv()

    if sentry_dsn := os.environ.get("SENTRY_DSN"):
        sentry_sdk.init(sentry_dsn)

    cf = CloudFlare.CloudFlare(raw=True)

    heroku = heroku3.from_key(os.getenv("HEROKU_API_KEY"))

    interval = int(os.getenv("INTERVAL", 0))

    if interval:
        while True:
            do_create(cf, heroku)
            time.sleep(interval)
    else:
        do_create(cf, heroku)


def do_create(cf, heroku):
    cf_zone = cf.zones.get(os.environ["CF_ZONE_ID"])["result"]

    all_records = list(
        get_cloudflare_list(
            cf.zones.dns_records, cf_zone["id"], params={"type": "CNAME"}
        )
    )
    all_records_dict = {record["name"]: record["content"] for record in all_records}

    for app in heroku.apps():
        app_domain = f"{app.name}.{cf_zone['name']}"
        app_domains = {domain.hostname: domain.cname for domain in app.domains()}

        cname = app_domains.get(app_domain)
        existing_record = all_records_dict.get(app_domain)

        # Add the domain to Heroku if it doesn't know about it
        if not cname:
            new_heroku_domain = app.add_domain(app_domain)
            app_domains.add(new_heroku_domain)
            cname = new_heroku_domain.cname

        cf_record_data = {
            "name": app.name,
            "type": "CNAME",
            "content": cname,
        }
        if cname == existing_record:
            print(app.name, "domain set correctly")
        else:
            if existing_record is None:
                print(app.name, "domain not set")
                cf.zones.dns_records.post(cf_zone["id"], data=cf_record_data)
            else:
                print(app.name, "incorrect record value")
                cf.zones.dns_records.patch(cf_zone["id"], data=cf_record_data)

            if any(d.acm_status for d in app_domains):
                refresh_acm(app)
            else:
                enable_acm(app)


if __name__ == "__main__":
    main()
