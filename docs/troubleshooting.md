# Troubleshooting and FAQ

*[Version française](fr/troubleshooting.md) · [User guide](README.md)*

## Start with App status

**Settings › App status** (or the status dot in the menu) lists what is wrong, by severity: **Blocks the plan**, **Less accurate plan**, **To watch**. Each problem says what to do and has a **Go there** link. **Check again** re-runs the checks.

| Problem | What to do |
|---|---|
| The application does not know the Home Assistant address | As an app: restart it. Standalone: set the address and log in (**Settings › Home Assistant connection**) |
| Home Assistant does not respond | Check that Home Assistant is running, and that the access token is still valid (standalone) |
| The Energy dashboard is not set up | Declare your grid meter, and your solar production if any, in Home Assistant: Settings › Dashboards › Energy |
| Your home is not saved yet | **My home**: check the proposed devices, then save |
| No solar forecast | Add a forecast to the Energy dashboard (Forecast.Solar, Solcast, Open-Meteo…), or describe your panels in **My home** |
| A sensor no longer exists / is unavailable / has sent nothing for a day | Replace it in **My home**, or check the device and its integration in Home Assistant |
| No history in Home Assistant for some sensors | They have no statistics (no `state_class`): the plan starts from their live measurements only |
| No plan could be computed for more than 2 hours | Look at the other problems, or **Compute** from **Planning** |

## Reporting a bug

1. **Settings › App status › Prepare a report**: a file describing the state of the app, **without device names, sensor identifiers or location**. The preview shows everything it contains.
2. **Download** it and attach it to a [bug report](https://github.com/jmcruvellier/wattslot/issues/new/choose), with the version and what happened.
3. As a Home Assistant app, the log is in **Settings › Apps › WattSlot › Log**; set the **Log level** option to `debug` if asked.

## FAQ

**The plan does not start any appliance today.** A cycle is only placed when something asks for it: a request, a task in your Home Assistant to-do list, or a recurrence (see [Your home and its rules](your-home.md#when-a-cycle-is-due)). Check also that the device is **Scheduled by planning**.

**The plan changes during the day.** It is recomputed every hour with the latest measurements and forecast: a cloudier morning moves an appliance to the afternoon. Appliances already started are kept.

**The measured values are empty for the first hours.** On a new installation, today's measurements start when WattSlot starts; the history import fills the past days. Measured data is refreshed every 15 minutes, or with **Refresh actual data**.

**The production forecast is far from what I measured.** Forecasts are better from an integration in the Energy dashboard (Solcast, Forecast.Solar) than from described panels. The **Off plan** notification warns you when the gap passes 25 %.

**The battery does not behave like the plan.** WattSlot simulates the battery; check its settings (floor, maximum powers), see [Battery](battery.md).

**Can WattSlot start my appliances by itself?** Not yet: this version recommends only. Controlling appliances, with your confirmation first, then automatically, device by device, will come in a later version.

**Does it work without solar panels?** Yes: with off-peak hours, colour days or dynamic prices, it places your appliances at the cheapest hours ([Tariffs](tariffs.md)).

**How much does it write to the disk?** A few GB per day at most in normal use; the first history import writes more, once. Use an SSD rather than an SD card.

**Where do I ask a question?** In the [Discussions](https://github.com/jmcruvellier/wattslot/discussions); for a bug, open a [GitHub issue](https://github.com/jmcruvellier/wattslot/issues/new/choose).
