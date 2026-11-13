# WattSlot

WattSlot plans when to run your household appliances and how to use your home battery, around your solar production and your electricity contract.

**Full user guide**: [in English](https://github.com/jmcruvellier/wattslot/blob/main/docs/README.md) · [en français](https://github.com/jmcruvellier/wattslot/blob/main/docs/fr/README.md) (installation, first steps, screens, tariffs, battery, notifications, voice assistant, troubleshooting, privacy).

**Experimental.** The add-on is in active development: expect changes between versions, and keep Home Assistant's automatic backup before updates.

## Requirements

The add-on keeps a detailed history of your energy data, written continuously. Plan for:

- **an SSD, not an SD card**, on a Raspberry Pi (USB 3 or NVMe): SD cards are too slow and wear out under continuous writes;
- **128 GB recommended (64 GB minimum)** for Home Assistant OS with this add-on;
- **a Raspberry Pi 5 with 8 GB of memory recommended.**

A mini PC or a virtual machine with an SSD has no particular constraint.

One exception: in a **virtual machine** (Proxmox…), give it a processor of type **host** (or **x86-64-v2-AES**): the default types `kvm64` and `qemu64` hide instructions the planning engine needs, and the app stops at start-up. See [Troubleshooting](https://github.com/jmcruvellier/wattslot/blob/main/docs/troubleshooting.md).

## Installation

1. Install the add-on and start it.
2. Open **WattSlot** in the sidebar.

The add-on connects to Home Assistant by itself: no token or address to enter.

## Using the app

- **First steps**: until setup is complete, the app guides you in four screens: connection, the appliances found in Home Assistant's Energy dashboard, your electricity contract, then your first plan.
- **Today**: what is happening right now, the next appliance to start (with "It's started" and "Remind me"), and the day ahead.
- **Planning**: yesterday, today, tomorrow and the week as an agenda; detailed charts are one click away.
- **My home**: your home in plain sentences, in four tabs (Essentials, Devices, Data, Advanced); each line opens its setting, each device its sheet (rules, sensors, name and type). Expert screens (templates, backup, graph, library) are in "Advanced".
- **Assistant** and **Settings**: your requests, the voice assistant, notifications, language and theme.
- **Themes**: "Automatic" follows the light or dark setting of your phone, browser or computer; five themes are available in Settings › Language and display. The choice is kept on each device.

## Voice assistant

Ask Home Assistant's Assist about your plan, with the language model you already use in Home Assistant (Ollama on your network, or an online service). Open **Settings › Voice assistant** in the add-on: it gives the address to enter in the **Model Context Protocol** integration, the settings for the conversation agent and a prompt to paste. The assistant reads the plan; the only thing it does on its own is file a request, after confirming it with you.

## Configuration

On the add-on's **Configuration** tab:

| Option | Default | Meaning |
|---|---|---|
| Log level | `info` | Detail of the add-on log; `debug` is only useful to investigate a problem. |
| Raw readings (days) | 3 | How long detailed readings are kept, from 1 to 30 days. |
| Quarter-hours (days) | 35 | How long the quarter-hour history is kept, from 31 to 3660 days (appliance cycles are learnt from the last 30 days). |

Changes apply when the add-on restarts. The hourly history is kept without limit.

## Data and backups

Everything stays local, in the add-on folder. A nightly maintenance (3:30, local time) removes
expired data; the store is compacted when a whole month of quarter-hours is removed.

Home Assistant backups include the house model, the aggregated history (quarter-hours and hours)
and the settings. Raw readings are left out: they are large and change all the time. Backups are
taken while the add-on runs: just before, the add-on freezes a consistent copy of its data, which
is the only thing saved, then removes it. Nothing is paused and no reading is lost. When you
restore a backup, the add-on puts the copy back in place at startup.

## Monitoring

The add-on checks itself every 30 seconds. With **Watchdog** turned on (add-on page), Home
Assistant restarts it if it stops answering. When stopped or updated, the add-on has 30 seconds
to write everything to disk.

## Security

The add-on runs under its own AppArmor profile: it can only read and write its own folder and the files it needs, and cannot start any program other than its own. It needs no access to the host, the network configuration or other add-ons, and its interface is only reachable through Home Assistant (ingress).

**Home Assistant API.** The add-on asks for access to Home Assistant's API (`homeassistant_api`), which Home Assistant grants as a whole, with administrator rights: there is no narrower option. WattSlot uses it to:

- **read**: the states of your entities and their changes, the Energy dashboard settings and solar forecast, the history and statistics, the entity and device registries (to find your appliances), your to-do lists, and the list of conversation agents;
- **act**, in two ways only: send the notifications you set up (`notify` services), and pass your questions to the conversation agent you chose for the voice assistant.

It never starts an appliance, never controls your battery and never changes an entity, an automation or a setting of Home Assistant.

## Help

Something wrong? Open **Settings › App status** in the app: it explains each problem and how to fix it, and prepares an anonymised report to attach to a [bug report](https://github.com/jmcruvellier/wattslot/issues/new/choose). See also [Troubleshooting and FAQ](https://github.com/jmcruvellier/wattslot/blob/main/docs/troubleshooting.md).

## Support the project

If WattSlot saves you money, you can support its development on [GitHub Sponsors](https://github.com/sponsors/jmcruvellier) or [Ko-fi](https://ko-fi.com/jmcruvellier).
