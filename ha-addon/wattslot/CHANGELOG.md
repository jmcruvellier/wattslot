# Changelog

## 0.9.2

Fixes found while installing the beta on a fresh Home Assistant.

- First steps: when something required is missing before the first plan (a solar forecast, for instance), the last step says what and opens the right setting, instead of "All set" and a calculation that silently did nothing. A calculation that fails is now reported.
- Standalone (Docker): the Home Assistant address given in `HA_URL` is filled in on the connection page.

## 0.9.1

Public beta for testers: clearer screens, data you can trust, and an easy way to give feedback.

- Beta: a "Beta" badge, a **Give feedback** button at the bottom of Settings (a ready-made form on GitHub), and a **Support WattSlot** card (GitHub Sponsors, Ko-fi).
- New **Charts** section: the figures and charts of the plan, moved out of Planning. The week is a table with one row per day.
- **My home** in four tabs (Essentials, Devices, Data, Advanced), one setting per sheet, and a complete sheet for each device.
- **Data quality**: WattSlot checks your meters, corrects impossible readings (a sensor dropout counted as a reset) and lets you choose another correction or undo it. One wrong reading no longer hides the others in the charts. The original data is never changed.
- **Other possible starts**: up to three other starts proposed by the plan, with their effect on the cost; choose one, or go back to the calculation's choice.
- Planning: **My requests** under the plan; Compute and Refresh next to the tabs; plan indicators for the whole day.
- **Assistant**: chat with Home Assistant's assistant (or Open WebUI) from the app, with the conversation kept; the internal address of the MCP server is remembered and can be changed.
- Your contract: subscription and subscribed power; the currency of your prices, shown everywhere.
- Week: where the horizon stops is explained, and missing days are shown.
- Fixes: a clear message when the expected consumption is impossible; the forecast production axis of the week starts at 0; no more tiny negative values or duplicated hours; no more occasional "Unable to read the plan".
- New README and user guide in English and French, with new screenshots.

## 0.9.0

Public beta, under the new name WattSlot.

- New name, icon and logo: WattSlot is a new app in Home Assistant (`wattslot`), installed from a public repository without any token.
- Homes without solar panels: off-peak, day colour or dynamic tariffs work on their own, without solar forecast.
- New version notice in Settings and Application status.
- Planning of appliances: taller tracks without legend, planned above and measured below, energy written in each block.
- History import writes about 5 times less to disk.
- Solver retries once differently when it wrongly reports a plan as impossible; the "battery full" bonus only breaks ties.
- Fixes: first-step "Notification" check, today's real data right after the update, start times of today's real cycles, hour axis of daily charts, stale warning of an appliance already placed in today's plan.
- The old v1 dashboard is removed.
- User documentation in English and French, links to support the project.

## 0.8.0

Home Assistant app quality: updates, backups and options.

- Updates from the app store: the app is published on its own branch, only once its image is online, so Home Assistant offers "Update" for each new version.
- Hot backups: before Home Assistant copies the app's folder, the app freezes a consistent copy of its database and graph; only that copy is backed up, and it is put back in place after a restore. Raw readings are left out (kept 3 days, rebuilt from Home Assistant's history).
- Options, in English and French: log level, how long raw readings (1 to 30 days) and quarter-hour data (31 to 3660 days) are kept.
- Clean stop: 30 seconds to write pending data before stopping; watched by the image's health check, so Home Assistant's watchdog restarts the app if it stops answering.
- Icon, logo and updated documentation.

## 0.7.0

First version planned for everyday use (development phases 0 to 6 bis).

- Reads your home from Home Assistant's Energy dashboard: solar production, grid, battery and appliances; history imported from Home Assistant's statistics.
- Daily plan and seven-day horizon: when to start each appliance, when to charge and discharge the battery, around solar forecast and electricity prices (single, off-peak, day colour or dynamic).
- Your home, your rules: appliance behaviours, time constraints, recurrences, battery settings, objective (cost, self-consumption, grid, CO₂), ready-made templates, backup and sharing.
- New interface: Today, Planning (agenda and detailed charts), My home in plain sentences, Assistant, Settings; guided first steps; five themes with automatic light and dark; six languages (German, Dutch, Spanish and Italian to be reviewed).
- Requests from the app or Home Assistant's Assist, reminders, configurable notifications.
- MCP server for Home Assistant's Assist (`/mcp`).
- Application status: problems explained in plain words, anonymised report.

## 0.0.1

- First development build: application state and connection to Home Assistant.
