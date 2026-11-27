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

As a Home Assistant app, WattSlot also runs under its own AppArmor profile: it can only read and write its own folder and the files it needs, and it cannot start any program other than its own. It needs no access to the host, the network configuration or other apps.

It does need Home Assistant's API, which Home Assistant only grants as a whole, with administrator rights. WattSlot uses it to read (states and their changes, Energy dashboard settings and solar forecast, history and statistics, entity and device registries, to-do lists, conversation agents) and to act in two ways only: send the notifications you set up, and pass your questions to the conversation agent you chose. If you switch it on (it is off by default), it also writes its own forecast sensors, named `sensor.wattslot_…` ([Sensors](sensors.md)). It never changes another entity, an automation or a setting of Home Assistant.
