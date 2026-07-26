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

## Files

- `app.py` — the Streamlit dashboard.
- `requirements.txt` — Python deps (installed at container start).
- `docker-compose.yaml` — runs the app on a **stock `python:3.12-slim`** image
  and installs the deps on startup. No image build, so it works with the older
  Docker Compose plugin already on the gateway instance.
- `Dockerfile` — **not used** by the compose file. Kept only for reference / if
  you later upgrade buildx and prefer a prebuilt image. Ignore it otherwise.

## Deploy on the EC2 instance (via SSM)

1. Copy this folder to the instance, e.g. `/opt/gateway-dashboard`. From your
   SSM shell you can just create the files there, or `scp`/`git` them in. Only
   `app.py`, `requirements.txt`, and `docker-compose.yaml` are needed.

2. Find the gateway's docker network name and confirm it matches the compose:

   ```
   docker network ls
   ```

   Look for the one ending in `_gw` (with the stack in `/opt/gateway` it is
   normally `gateway_gw`). If it differs, edit `name:` under `networks:` in
   `docker-compose.yaml`.

3. Start it (no `--build` — the compose uses a stock image and pip-installs on
   startup):

   ```
   cd /opt/gateway-dashboard
   docker compose up -d
   ```

   > First boot takes ~30–60s while pip installs Streamlit/pandas/psycopg2.

4. Check it's healthy — wait for Streamlit's "You can now view your Streamlit
   app" line:

   ```
   docker compose logs -f dashboard
   docker compose ps        # should show the container up, listening on 8501
   ```

### Note on `--build` / buildx

The gateway instance ships an older Docker Compose plugin, so `docker compose
up -d --build` fails with `compose build requires buildx 0.17.0 or later`. The
compose file avoids this entirely by running a stock image and installing deps
at runtime — so **do not** pass `--build`. (If you'd rather build a real image,
first upgrade the plugin, then switch the compose `image:`/`command:` back to a
`build: .` stanza.)

## Reaching the UI

The app listens on port **8501**. The instance's security group only allows
443 inbound, so port 8501 is **not** open to you directly. Two options:

**A. SSM port forwarding (recommended — no SG change):**

This requires the **Session Manager plugin** installed locally *in addition to*
the AWS CLI. If you see `SessionManagerPlugin is not found`, install it:

- macOS (Homebrew): `brew install --cask session-manager-plugin`
- macOS (manual, Apple Silicon):
  ```
  curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/mac_arm64/session-manager-plugin.pkg" -o "session-manager-plugin.pkg"
  sudo installer -pkg session-manager-plugin.pkg -target /
  sudo ln -sf /usr/local/sessionmanagerplugin/bin/session-manager-plugin /usr/local/bin/session-manager-plugin
  ```
  (Intel Mac: use `mac` instead of `mac_arm64`.)

Then start the tunnel and leave the terminal running:

```
aws ssm start-session --target <ec2-instance-id> --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}' --region ap-south-1
```

Example (this deployment):

```
aws ssm start-session --target i-04f6e0c3f8f1d --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}' --region ap-south-1
```

Then open http://localhost:8501 in your browser.

**B. Open port 8501** in the security group to your IP and browse to the
instance's IP:8501. Less tidy; only do this on a lab box.

## Notes

- Read-only: the app only runs SELECTs. It never writes to the gateway DB.
- Credentials default to `gw`/`gw` (the lab defaults) and can be overridden via
  the `PG*` environment variables in `docker-compose.yaml`.
- To pick up edits to `app.py` (it's bind-mounted): `docker compose restart
  dashboard`. To pick up new dependencies in `requirements.txt`: `docker
  compose up -d --force-recreate` (re-runs the pip install).
- No authentication: anyone who can reach port 8501 can see spend data. Keep it
  behind the SSM tunnel, or put it behind the gateway's nginx/TLS.
