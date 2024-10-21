# Heroku Cloudflare App Domain

[![Main](https://github.com/torchbox/heroku-cloudflare-app-domain/actions/workflows/main.yml/badge.svg)](https://github.com/torchbox/heroku-cloudflare-app-domain/actions/workflows/main.yml)

Creating branded herokuapp.com-like domains using Cloudflare, based on the app name (eg `my-app-prod.example.com`).

## Features

- Set records for domains which don't exist
- Update records which are set incorrectly
- Delete records which aren't referenced any more in Heroku
- Enable / refresh [ACM](https://devcenter.heroku.com/articles/automated-certificate-management) when an app has its domain updated.

## Usage

Install the dependencies listed in `requirements.txt`, ideally into a virtual environment.

Set some environment variables:

- `CF_API_KEY`: A Cloudflare API key, with access to the zone you wish to edit. "DNS Edit" is required for those zones.
- `HEROKU_API_KEY`: API key from Heroku
- `CF_ZONE_ID`: The Cloudflare zone id of the domain to automatically create

Optionally:

- `APP_NAME`: A regex of app names to act on. Any not matching this will be skipped.
- `HEROKU_TEAMS`: A comma separated list of Heroku teams to operate on. By default will use all apps the account has access to.
- `ALLOWED_CNAME_TARGETS`: A comma-separated list of regexes which match CNAMEs. If these CNAMEs are found in place of the correct Heroku CNAME, they won't be overridden.

These can also be set in a `.env` file.

Then, simply run the `main.py`. To have the application loop for you, specify an interval in seconds with `$INTERVAL`.

## Deployment

In some hosting environments, it may not be possible to run the container as a background job (eg [Cloud Run](https://cloud.google.com/run/)).

To account for this, the default container wraps the command in [`webhook`](https://github.com/adnanh/webhook).

To trigger the hook, send a `GET` request to `/hooks/trigger`. The webhook is protected by a token, which can be set using `$WEBHOOK_TOKEN`, and should be sent in the `X-Webhook-Token` header.

To run in a loop instead of a webhook, set `$INTERVAL` in the container.

Alternatively, it's possible to run on Heroku using its [scheduler](https://devcenter.heroku.com/articles/scheduler). Just add a job for `/app/main.py`, and stop the web processes.
