# Web

In some hosting environments, it may not be possible to run the container as a background job (eg [Cloud Run](https://cloud.google.com/run/)).

To account for this, an alternative container is built, which wraps the command in [`webhook`](https://github.com/adnanh/webhook).

To trigger the hook, send a `GET` request to `/hooks/trigger`. The webhook is protected by a token, which can be set using `$WEBHOOK_TOKEN`, and should be sent in the `X-Webhook-Token` header.
