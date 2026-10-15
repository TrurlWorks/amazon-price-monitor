# Amazon Price Monitor

**Version: 0.8.5** · Self-hosted Amazon.pl price tracking for a trusted local network.

Amazon Price Monitor is a web application for recording product price observations, reviewing price history and scheduling checks of product pages on Amazon.pl. It uses **Python/FastAPI**, **React/TypeScript**, **SQLite** and **Docker Compose**.

> **Independent project.** This application is not affiliated with, endorsed by or sponsored by Amazon. Review the applicable website terms and laws before using the page acquisition provider.

## Features

- Add Amazon.pl products and inspect their recorded prices and historical charts.
- Browse tracked products in dashboard tile or table views; inspect product details.
- Run scheduled checks through a persistent SQLite acquisition queue, with configurable pacing and retry intervals.
- Request immediate checks and view queue diagnostics in Settings.
- Use an offline `mock` provider for demonstrations and tests.
- Access a Polish-language information page in the application.

**Not included:** user authentication, built-in HTTPS/TLS, email alerts or push notifications. Price acquisition may fail due to changes in page layout, CAPTCHA, access controls or other issues; the application does not bypass these restrictions. Observed prices may omit personalization, coupons and delivery costs.



<h2>📸 Screenshots</h2>

<p>Click any screenshot to view it in full resolution.</p>

<table>
  <tr>
    <th>01 — Table Dashboard</th>
    <th>02 — Tile Dashboard</th>
    <th>03 — Price History</th>
  </tr>
  <tr>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/8989a555-4afd-4afb-afa9-e135935dde4e">
        <img src="https://github.com/user-attachments/assets/8989a555-4afd-4afb-afa9-e135935dde4e" height="130" alt="Table Dashboard">
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/6beaf96a-822b-4ba8-a801-16a3b43f6c25">
        <img src="https://github.com/user-attachments/assets/6beaf96a-822b-4ba8-a801-16a3b43f6c25" height="130" alt="Tile Dashboard">
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/a1146b43-e5c3-4076-9cfc-2119458b8333">
        <img src="https://github.com/user-attachments/assets/a1146b43-e5c3-4076-9cfc-2119458b8333" height="130" alt="Price History">
      </a>
    </td>
  </tr>
  <tr>
    <th>04 — Queue Diagnostics</th>
    <th>05 — Mobile View</th>
    <th></th>
  </tr>
  <tr>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/d68407ae-8fe1-4161-8575-11e0176defa2">
        <img src="https://github.com/user-attachments/assets/d68407ae-8fe1-4161-8575-11e0176defa2" height="130" alt="Queue Diagnostics">
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/f6b7f1d2-5609-4b64-842c-6300ecef17f2">
        <img src="https://github.com/user-attachments/assets/f6b7f1d2-5609-4b64-842c-6300ecef17f2" height="130" alt="Mobile View">
      </a>
    </td>
    <td></td>
  </tr>
</table>




## Quick start (Docker)

**Requirements:** Git, Docker Engine with Docker Compose v2, a free TCP port (8080 by default) and local disk space for SQLite data.

1. On GitHub, select **Code → HTTPS** to obtain the repository clone URL. Clone it with `git clone <repository-url>` and open the cloned `amazon-price-monitor` directory.
2. Copy the sample configuration and review its values:

   ```sh
   cp .env.example .env
   ```

3. For an offline first run, set `PRODUCT_PROVIDER=mock` in `.env`. To enable page acquisition instead, use the documented `amazon_page` provider only after reviewing its limitations.
4. Validate and start the application:

   ```sh
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   ```

5. When running with the default port, open **http://localhost:8080** from the machine hosting Docker. If accessing it from another machine, set `BIND_ADDRESS` appropriately and restrict access to a trusted LAN.

See the [Polish installation and maintenance guide](docs/INSTALLATION.md) for configuration, logs, backups and updates.

## Configuration

Configuration is read from `.env` (copy `.env.example`; do not commit `.env`). The main keys are:

| Variable | Description |
| --- | --- |
| `HTTP_PORT` | Published web port (8080 in the standard configuration) |
| `BIND_ADDRESS` | Interface/IP address on the host for the web port |
| `PRODUCT_PROVIDER` | `mock` for offline checks or `amazon_page` for page acquisition |
| `MONITOR_MOCK_SCENARIO` | Scenario for the mock provider |
| `POLL_INTERVAL_SECONDS` | Interval between regular checks |
| `FAILED_RETRY_SECONDS` | Base delay used when retrying failed checks |
| `QUEUE_GAP_SECONDS` | Pacing between scheduled acquisition starts |

Consult `.env.example` for the exact shipped defaults. The application persists certain monitoring settings in SQLite; effective values can depend on existing saved settings.

## Architecture

Docker Compose orchestrates five services:

| Service | Role |
| --- | --- |
| `data-init` | Prepares the persistent data directory and ownership |
| `migrate` | Applies Alembic database migrations |
| `api` | FastAPI service and HTTP endpoints |
| `worker` | Scheduled product checks and queue processing |
| `web` | Nginx-hosted React frontend and API reverse proxy |

The database is stored under `./data/` (typically `./data/monitor.sqlite3`); do not add it to Git or store it on a network filesystem. Run **one worker instance only**. Alembic revision **0008** is included in version 0.8.4.

## Operations

```sh
docker compose ps
docker compose logs --tail=100
docker compose down
docker compose up -d --build
```

Before upgrades, **back up the SQLite database and `.env`**. Stop the application before copying SQLite files so the database and its WAL files are consistent. `docker compose down` without `-v` does not intentionally delete the bind-mounted `./data` directory. Never use `down -v` as a routine backup method.

## Development and testing

Python dependencies are pinned in `requirements.lock`; test/lint configuration is in `pyproject.toml`. Frontend dependencies and their resolved versions are in `frontend/package.json` and `frontend/package-lock.json`.

A local backend test environment can be prepared as follows:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest -q
```

The frontend image runs lint, Vitest and the production build as part of its Docker build:

```sh
docker compose build web
```

## Security and usage limitations

**LAN-only by design.** Version 0.8.4 has no built-in authentication or HTTPS. Do not publish its port directly to the internet. For local-host-only use, set `BIND_ADDRESS=127.0.0.1` in `.env` before starting Docker Compose.

The `amazon_page` provider reads server-rendered product pages. Its availability and suitability depend on Amazon's access restrictions and terms. The application does not offer official Amazon integration credentials or CAPTCHA circumvention. Users are responsible for ensuring that data collection, processing and retention are permitted.

## License

A license must be selected and added as `LICENSE` before the repository is publicly released. No open-source license is granted merely by making code available.
