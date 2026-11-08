# Troubleshooting and FAQ

*[Version française](fr/troubleshooting.md) · [User guide](README.md)*

## Start with App status

**Settings › App status** (or the status dot in the menu) lists what is wrong, by severity: **Blocks the plan**, **Less accurate plan**, **To watch**. Each problem says what to do and has a **Go there** link. **Check again** re-runs the checks.

The **Resources** section shows the processor (average over 15 minutes and peak, as a share of one core), the memory (with its peak, and either the container limit or the machine memory) and the disk (the app's data and the free space on the disk that holds it). Each line opens on its curve over the last 24 hours, one point a minute; hover over it to read a value. The memory limit is the container's when it sets one; otherwise it is the memory of the machine, shared with everything else running on it.

| Problem | What to do |
|---|---|
| The application does not know the Home Assistant address | As an app: restart it. Standalone: set the address and log in (**Settings › Home Assistant connection**) |
| Home Assistant does not respond | Check that Home Assistant is running, and that the access token is still valid (standalone) |
| The Energy dashboard is not set up | Declare your grid meter, and your solar production if any, in Home Assistant: Settings › Dashboards › Energy |
| Your home is not saved yet | **My home**: check the proposed devices, then save |
| No solar forecast | Add a forecast to the Energy dashboard (Forecast.Solar, Solcast, Open-Meteo…), or describe your panels in **My home** |
| A sensor no longer exists / is unavailable / has sent nothing for a day | Replace it in **My home**, or check the device and its integration in Home Assistant |
| No history in Home Assistant for some sensors | They have no statistics (no `state_class`): the plan starts from their live measurements only |
| No plan could be computed for more than 2 hours | Look at the other problems, or **Compute** from the title bar of **Today**, **Planning** or **Curves** |
| Little free space on the data disk (under 2 GB or 10%), or not enough for a backup (twice the size of the database and the main store) | Free up space on this disk; as a Home Assistant app, you can also shorten how long readings are kept in its options |
| WattSlot uses a lot of memory for 15 minutes (75% of its container limit, or 1 GB without a container limit) | If it lasts, restart the application and attach the report to a bug report |
| The last plan computation took 10 minutes or more | If it lasts, attach the report to a bug report |

These resource alerts are also sent as notifications, once a day while they last; switch them off in **Settings › Notifications › Messages**.

## The app does not start: "NumPy was built with baseline optimizations (X86_V2)"

The log ends with `RuntimeError: NumPy was built with baseline optimizations: (X86_V2) but your machine doesn't support: (X86_V2)`, or with a message from WattSlot about **x86-64-v2** instructions.

The processor seen by Home Assistant does not report the instructions that WattSlot's planning engine needs. On almost every PC from the last fifteen years, the processor has them, but a **virtual machine** can hide them: on Proxmox, the CPU types `kvm64` and `qemu64` do.

On Proxmox:

1. Select the Home Assistant virtual machine.
2. Open **Hardware**, then double-click **Processors**.
3. Set **Type** to **host** (or **x86-64-v2-AES** if you move the virtual machine between different servers).
4. Click **OK**.
5. **Stop** the virtual machine completely (a restart from Home Assistant is not enough), then start it.
6. Start the WattSlot app again.

Other hypervisors have the same setting (for example *host-passthrough* with libvirt / virt-manager). It also benefits Home Assistant and the other apps.

## Reporting a bug

1. **Settings › App status › Prepare a report**: a file describing the state of the app, **without device names, sensor identifiers or location**. The preview shows everything it contains.
2. **Download** it and attach it to a [bug report](https://github.com/jmcruvellier/wattslot/issues/new/choose), with the version and what happened.
3. As a Home Assistant app, the log is in **Settings › Apps › WattSlot › Log**; set the **Log level** option to `debug` if asked.

## FAQ

**The plan does not start any appliance today.** A cycle is only placed when something asks for it: a request, a task in your Home Assistant to-do list, or a recurrence (see [Your home and its rules](your-home.md#when-a-cycle-is-due)). Check also that the device is **Scheduled by planning**.

**The plan changes during the day.** It is recomputed every hour with the latest measurements and forecast: a cloudier morning moves an appliance to the afternoon. When the panels produce less (or more) than forecast since the morning, the rest of the day's forecast is scaled by the same ratio, so the plan no longer counts on sun that is not coming. Appliances already started are kept.

**The measured values are empty for the first hours.** On a new installation, today's measurements start when WattSlot starts; the history import fills the past days. Measured data is refreshed every 15 minutes, or with **Refresh actual data**.

**The production forecast is far from what I measured.** Forecasts are better from an integration in the Energy dashboard (Solcast, Forecast.Solar) than from described panels. The **Off plan** notification warns you when the gap passes 25 %.

**The battery does not behave like the plan.** WattSlot simulates the battery; check its settings (floor, maximum powers), see [Battery](battery.md).

**A meter counted thousands of kWh in one hour.** Its sensor probably dropped to zero for an instant. WattSlot no longer counts a short dropout as a reset, and corrects the hours already affected: see **My home › Data**.

**Can WattSlot start my appliances by itself?** Not yet: this version recommends only. Controlling appliances, with your confirmation first, then automatically, device by device, will come in a later version.

**Does it work without solar panels?** Yes: with off-peak hours, colour days or dynamic prices, it places your appliances at the cheapest hours ([Tariffs](tariffs.md)).

**How much does it write to the disk?** A few GB per day at most in normal use; the first history import writes more, once. Use an SSD rather than an SD card.

**How do I give feedback on the beta?** With **Give feedback**, at the bottom of **Settings**, or directly with the [beta feedback form](https://github.com/jmcruvellier/wattslot/issues/new?template=beta_feedback.yml): what works, what bothers you, what you did not understand. English or French.

**Where do I ask a question?** In the [Discussions](https://github.com/jmcruvellier/wattslot/discussions); for a bug, open a [GitHub issue](https://github.com/jmcruvellier/wattslot/issues/new/choose).
