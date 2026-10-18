<p align="center"><img src="ha-addon/wattslot/logo.png" alt="WattSlot" width="250"></p>

# WattSlot

*[Version française](README.fr.md)*

**WattSlot finds the right slot to run your household appliances**, so you use your own solar power or the cheapest hours of your electricity contract. It reads your home from Home Assistant, plans the day and the week, and tells you what to start and when: it recommends, you decide.

It works with or without solar panels and a battery: a contract with off-peak hours, colour days (such as EDF Tempo) or dynamic prices is enough to save money.

> **Status: beta.** WattSlot is used every day on its author's home and is now looking for testers. Feedback is very welcome.

## Features

- **Reads your home from Home Assistant**: the Energy dashboard gives the solar production, the grid, the battery and the tracked appliances; past data comes from Home Assistant's statistics. Nothing to type in to get started.
- **Daily plan and seven-day horizon**: when to start each appliance, when to charge or discharge the battery, based on the solar forecast and your electricity prices (single price, off-peak hours, colour days, dynamic prices read from an entity).
- **Your home, your rules**: appliance behaviours, time windows, recurrences, battery settings, and what to optimise (cost, self-consumption, grid draw, CO₂). Ready-made templates, backup and sharing of your settings.
- **An interface made for every day**: Today, Planning (agenda and detailed charts), My home in plain sentences, Assistant, Settings. Phone first, five themes with automatic light and dark, six languages (English, French, German, Dutch, Spanish and Italian).
- **Requests and reminders**: ask for an appliance from the app or from Home Assistant's Assist, get notified at the right time.
- **Assistant (optional)**: a built-in MCP server lets Home Assistant's Assist answer questions about your plan with the language model you already use.
- **Diagnostics in plain words**, with an anonymised report to attach to a bug report.

## Requirements

- **Home Assistant OS or Supervised** to install WattSlot as an app (add-on), on `amd64` or `aarch64` (Raspberry Pi 4 or 5 with an SSD, mini PC…).
- Or **Docker** next to any Home Assistant installation (standalone mode, see below).
- Home Assistant's **Energy dashboard** set up: WattSlot starts from it.

## Installation

### As a Home Assistant app (recommended)

[![Add the WattSlot repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjmcruvellier%2Fwattslot%23addon)

1. Click the button above, or add `https://github.com/jmcruvellier/wattslot#addon` in **Settings → Apps → App store → ⋮ → Repositories**.
2. Install **WattSlot**, tick **Show in sidebar**, then **Start**.
3. Open WattSlot from the sidebar and follow the first steps: they check the connection, the devices found in your Energy dashboard, your contract, and compute a first plan.

Updates arrive like any other app, with Home Assistant's automatic backup.

### Standalone (Docker)

```bash
docker run -d --name wattslot --restart unless-stopped \
  -p 8100:8100 -v wattslot-data:/data \
  -e HA_URL=http://homeassistant.local:8123 \
  ghcr.io/jmcruvellier/wattslot:latest
```

Open `http://<host>:8100` and sign in with Home Assistant from the connection page (or pass a long-lived access token in `HA_TOKEN`). Keep port 8100 on your local network only.

## Documentation

- [User guide](docs/) (installation, first steps, screens, tariffs, battery, assistant, FAQ)
- [Changelog](ha-addon/wattslot/CHANGELOG.md)

## Support and contributing

- **Bugs and ideas**: [open an issue](https://github.com/jmcruvellier/wattslot/issues/new/choose). For a bug, attach the anonymised report from **Settings → App status → Prepare a report**.
- **Contributing** (code, translations): see [CONTRIBUTING.md](CONTRIBUTING.md).
- **Security**: see [SECURITY.md](SECURITY.md).

If WattSlot saves you money, you can support its development on [GitHub Sponsors](https://github.com/sponsors/jmcruvellier) (monthly or one-time) or [Ko-fi](https://ko-fi.com/jmcruvellier) (one-time), also linked from the **Sponsor** button of this page and from **Settings → App status** in the app.

## License

[Apache License 2.0](LICENSE). WattSlot gives recommendations and does not control your devices; it comes with no warranty (see the license).
