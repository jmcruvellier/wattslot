# Privacy

*[Version française](fr/privacy.md) · [User guide](README.md)*

WattSlot runs entirely at home. It has no account, no cloud service and no telemetry.

## What stays at home

Everything: your home's description, your settings, your measurements and your plans are stored in WattSlot's data folder (the app's folder in Home Assistant, or the Docker volume in standalone mode), and included in Home Assistant's backups.

## The only outgoing connections

| Who | To | When | What is sent |
|---|---|---|---|
| WattSlot (the server) | Home Assistant | Always | It reads your sensors, the Energy dashboard and the statistics; it sends notifications |
| WattSlot (the server) | `api.open-meteo.com` | Only if you described your panels and Home Assistant gives no forecast | Your location rounded to about 1 km (0.01°), at most once per hour and per panel array |
| Your browser | `api.github.com` | When the app is open, at most once per hour | Nothing about you: it reads the latest WattSlot version to tell you about updates |
| Home Assistant | your language model | Only if you set up the [voice assistant](assistant.md) | Your questions and the answers WattSlot gives Assist; with a local model (Ollama) this stays at home |

## What leaves only if you choose to

- **Exports** (**My home › Back up or share**): your home and settings as a file. Your Home Assistant connection is never in it.
- **Reports** (**Settings › App status › Prepare a report**): the state of the app, without device names, sensor identifiers or location, to attach to a bug report. You see everything it contains before downloading it.

## Safety

WattSlot only **recommends**: it never starts an appliance and never controls your battery. As a Home Assistant app it is only reachable through Home Assistant; in standalone mode, keep it on your local network.
