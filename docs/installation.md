# Installation

*[Version française](fr/installation.md) · [User guide](README.md)*

WattSlot installs in two ways. Both run the same application.

| | Home Assistant app (add-on) | Standalone (Docker) |
|---|---|---|
| For | Home Assistant OS or Supervised | Any Home Assistant (Container, Core…) |
| Connection to Home Assistant | Automatic | Sign in with Home Assistant, or a long-lived access token |
| Opens from | Home Assistant's sidebar | `http://<host>:8100` |
| Updates | From Home Assistant, with its automatic backup | `docker compose pull` |

**Hardware**: `amd64` or `aarch64`. WattSlot keeps a detailed history, written continuously: use an **SSD, not an SD card** (USB 3 or NVMe on a Raspberry Pi), 128 GB recommended (64 GB minimum) for Home Assistant OS with WattSlot. On a Raspberry Pi, a **Pi 5 with 8 GB** is recommended: the first history import needs up to about 1 GB of memory for the app. A mini PC or a virtual machine with an SSD has no particular constraint.

**Before you start**: set up Home Assistant's **Energy dashboard** (Settings › Dashboards › Energy) with at least your grid meter, and your solar production if you have panels. WattSlot starts from it.

## As a Home Assistant app (recommended)

1. Add the repository to your Home Assistant:

   [![Add the WattSlot repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjmcruvellier%2Fwattslot%23addon)

   Or by hand: **Settings › Apps › App store › ⋮ › Repositories**, add `https://github.com/jmcruvellier/wattslot#addon`, then **Close**.
2. Refresh the store (**⋮ › Check for updates**), open **WattSlot**, click **Install**.
3. Tick **Show in sidebar**, then **Start**.
4. Open **WattSlot** from the sidebar and follow [Getting started](getting-started.md).

### Options

In **Settings › Apps › WattSlot › Configuration**:

| Option | Default | Meaning |
|---|---|---|
| Log level | info | `debug` when asked for a bug report |
| Raw readings kept | 3 days | Every individual measurement (1 to 30 days) |
| Quarter-hour data kept | 35 days | Averages per quarter hour (31 to 3,660 days); hourly averages are kept forever |

### Updates and backups

- **Updates**: Home Assistant offers **Update** when a new version is published, and makes a backup first if you leave that option ticked. **Settings › App status** also tells you when a new version exists.
- **Backups**: Home Assistant backups include WattSlot. The app freezes a consistent copy of its data during the backup, without stopping. Raw readings are left out (they are rebuilt from Home Assistant's history after a restore).

### Uninstalling

**Settings › Apps › WattSlot › Uninstall** removes the app **and its data**. Make a backup first if you may come back, or export your home (**My home › Advanced › Back up or share**).

## Standalone (Docker)

```bash
docker run -d --name wattslot --restart unless-stopped \
  -p 8100:8100 -v wattslot-data:/data \
  -e HA_URL=http://homeassistant.local:8123 \
  ghcr.io/jmcruvellier/wattslot:latest
```

Or with Docker Compose:

```yaml
services:
  wattslot:
    image: ghcr.io/jmcruvellier/wattslot:latest
    restart: unless-stopped
    ports: ["8100:8100"]
    volumes: ["wattslot-data:/data"]
    environment:
      HA_URL: http://homeassistant.local:8123
volumes:
  wattslot-data:
```

Then open `http://<host>:8100`:

- **Settings › Home Assistant connection** (recommended): enter your Home Assistant address, click **Log in with Home Assistant**, confirm on your Home Assistant's own page; you come back connected.
- Or create a **long-lived access token** in Home Assistant (Profile › Security) and pass it in `HA_TOKEN`.

**Security**: in standalone mode WattSlot has no login of its own. Keep port 8100 on your local network; never expose it to the Internet.

**Updating**: `docker compose pull && docker compose up -d` (or pull the image and recreate the container). Pin a version (`ghcr.io/jmcruvellier/wattslot:0.9.0`) if you prefer to update by hand.

| Variable | Meaning |
|---|---|
| `HA_URL` | Your Home Assistant's address, as you open it in a browser |
| `HA_TOKEN` | Long-lived access token (optional with the sign-in page) |
| `HA_TOKEN_FILE` | Or the path of a file containing the token (Docker secret) |
| `WATTSLOT_DATA_DIR` | Data folder, `/data` in the image |
| `TZ` | Time zone of the logs; the plan follows Home Assistant's |
