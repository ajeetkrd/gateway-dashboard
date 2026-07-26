# Gateway Users & Spend dashboard

A small Streamlit app that reads the Claude Apps Gateway's Postgres and shows
users and their spend (in USD), plus configured limits vs. actual usage.

It is built for this exact schema:

- `spend(principal, period, cents, updated_at)` — money is in **cents**; `period`
  encodes the window and its granularity: `YYYY-MM` = monthly, `YYYY-Www` =
  weekly, `YYYY-MM-DD` = daily.
- `principal_emails(principal, email, name, groups jsonb, updated_at)`
- `spend_limits(id, scope_type, scope_id, amount, period, currency, ...)` —
  `amount` is a cap in **cents**; `scope_type` is user / rbac_group / organization.

All amounts are shown in dollars. Monthly/weekly/daily totals overlap (same
usage, different buckets) — they are not additive.

## Why it runs as a container

The gateway's Postgres port (5432) is **not** published to the EC2 host — it's
only reachable on the gateway's internal Docker network. So the dashboard runs
as another container joined to that same network, where the DB is reachable at
host `postgres`.

## Deploy on the EC2 instance (via SSM)

1. Copy this folder to the instance, e.g. `/opt/gateway-dashboard`. From your
   SSM shell you can just create the four files there, or `scp`/`git` them in.

2. Find the gateway's docker network name and confirm it matches the compose:

   ```
   docker network ls
   ```

   Look for the one ending in `_gw` (with the stack in `/opt/gateway` it is
   normally `gateway_gw`). If it differs, edit `name:` under `networks:` in
   `docker-compose.yaml`.

3. Build and start:

   ```
   cd /opt/gateway-dashboard
   docker compose up -d --build
   ```

4. Check it's healthy:

   ```
   docker compose logs -f dashboard
   ```

## Reaching the UI

The app listens on port **8501**. The instance's security group only allows
443 inbound, so port 8501 is **not** open to you directly. Two clean options:

**A. SSM port forwarding (recommended — no SG change):**

```
aws ssm start-session \
  --target <instance-id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}' \
  --region <region>
```

Then open http://localhost:8501 in your browser.

**B. Open port 8501** in the security group to your IP and browse to the
instance's IP:8501. Less tidy; only do this on a lab box.

## Notes

- Read-only: the app only runs SELECTs. It never writes to the gateway DB.
- Credentials default to `gw`/`gw` (the lab defaults) and can be overridden via
  the `PG*` environment variables in `docker-compose.yaml`.
- To update after editing `app.py`: `docker compose up -d --build`.
