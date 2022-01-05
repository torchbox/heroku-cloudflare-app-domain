# Heroku Cloudflare App Domain

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

These can also be set in a `.env` file.

Then, simply run the `main.py`. To have the application loop for you, specify an interval in seconds with `$INTERVAL`.

## Deployment

For deploying as a webhook, see the [`web/`](./web/) directory.
