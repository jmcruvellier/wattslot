# The screens

*[Version française](fr/screens.md) · [User guide](README.md)*

Six sections, in the menu at the bottom of the screen on a phone, on the left on a computer (it folds into icons with the arrow at its top). Two things are always at hand: the **status dot** (green: all good; orange: needs a look; red: planning is blocked) and **Request an appliance** (the `+` button).

## Today

What you need right now.

![Today on a computer](images/en/today-desktop-light.png)

- **Right now**: the average of the last quarter hour for the panels, the home, the battery (charging or supplying) and the grid (buying or surplus).
- **Next action**: the next appliance to start and its slot, for instance *Start the washing machine: start at 11:15, done around 13:30*; once that time has passed without the cycle being seen, the block says so and asks you to start it as soon as you can. **It's started** tells the app you did it: the block moves on to the next appliance, on every device, for the rest of the day (**Not started yet** takes it back, until the app sees the cycle in the measurements); **Remind me** sends a notification at the right time (see [Notifications](notifications.md)); under the appliance's name, the start time and the reason in a few words (*100% solar*, *off-peak hours*); **Another time** unfolds the full reason, the other starts, picking the hour yourself, as on the timeline, and **Cancel** (do not run it today). When nothing is left to start, the block says why: everything is started, the planning was cancelled for today, or no appliance is planned today.
  - **Other possible starts** (under **Another time**): up to three other starts the plan allows, with what they change to the cost. Choosing one imposes it on today's calculation, which runs again; **Back to the calculation's choice** undoes it. When the battery's full charge is due, the text says why a cheaper start was set aside.
- **Plan indicators**: the cost today, the purchases from the grid, the surplus and the self-consumption.
- **Battery** and **Sun**: the charge now and its level at midnight; the solar energy expected and already produced. The badge in the corner gives the gap with the forecast, or *too early* while no reading allows a comparison (just after midnight).
- **Appliance schedule**: one line per device, with its icon and, under its name, where it stands (running, started at…, planned at…, or the energy measured). What was measured is a filled block with its energy; the planned slot is a bracket above it. A slot still to come also shows a dotted block with its planned energy. Batteries come first, then the appliances in the order of their first start of the day, planned or measured. An appliance set to start after another one (a dryer after a washing machine) sits just below it, and a thin line joins each of its cycles to the cycle it follows: solid once it has started, dashed while it is only planned or not started yet. A line and its time mark the last reading. Tap anywhere on a line to read what was planned and what was measured at that hour. On Today, off-peak hours are shaded behind the lines, a band above them shows solar production hour by hour, and the tap also gives the rate and the production of that hour.

![Today in the dark theme](images/en/today-phone-dark.png)

## Planning

The plan in detail, for **Yesterday**, **Today**, **Tomorrow**, the following days (**D+2** to **D+6**) and the **Week**.

![Planning](images/en/planning-desktop-light.png)

- At the top, **Compute** (recalculate now) and **Refresh** (read the actual data again), each with how long ago it last ran; on a phone, their icons only.
- Warnings, then three tiles for what matters, each with a figure and, at the top right, a badge: the battery at midnight, the sun forecast, the appliances started and planned. Under the figure, the detail line by line: for the battery, the measured level, the one the plan of the day before expected, the gap between them and the last charge to 100%; for the sun, the weather, the best day of the month, what was measured compared with the latest forecast and the hours of peak sun; for the appliances, one line each with its time and energy. On a phone this detail is folded: tap the tile to open it.
- **The day**: what happens and when, one line per event. To the right of an appliance, its planned energy, or *started* and its measured energy once the cycle has been seen; today, a **Now** marker separates what is past from what is to come. For the hours already measured (yesterday, and today up to the last reading), the battery is told from its measurements: when it charged, when it took over, its highest level; after that, from the plan. Tap an appliance to unfold why it was placed there; today, its other possible starts can be chosen there too.
  - An appliance can start in the evening and finish the next day, when the night hours are cheaper (or the battery still covers them): its end time is the next day's, and the next day starts with the end of the cycle.
- **Why this plan**, at the bottom of the day (unfolded on a wide screen, folded on a phone): what the battery does and the full text of the plan.
- **Plan indicators** (cost, purchases, surplus, self-consumption, battery level at the end of the day…): for the whole day, measured for the hours already past, planned for the rest.
  - In its corner, the **forecast quality** (reliable, fair or uncertain) tells how far to trust the planned production and consumption, from the data the calculation had: days of history behind the usual consumption, its regularity, the source of the solar forecast, how many days ahead the weather is forecast. Tap it for the reason behind each criterion.
- **My requests**: under each day, the requested appliances that run on that day (the day the plan places them, or the day they were started); under **Today**, also those the plan has not placed yet; under **Week**, every request in progress, with its planned day, and the latest closed requests. Each request shows where it stands (started, not placed yet, or not computed yet when it was asked after the last computation), the wished end time if you gave one, and its buttons: **Cancel**, **Edit** as long as the appliance has not started (the request sheet opens with its date and end time, ready to change), and, under **Yesterday** and **Today** only, **Done** (an appliance cannot have run on a day to come). For a new request: **Request an appliance** (the `+` button).
  - The same appliance can run **several times in a day** (two loads of laundry, two heats of the water heater): ask for it again. If it already has a pending request, choose **Add a cycle** rather than **Change the date**. Each cycle gets its own slot, after the previous one; the second one is named with its rank (*Washing machine #2*) in **Next action**, the agenda and the notifications, and has its own departure choice, **Cancel** and **It's started**. A dryer set to start after the washing machine follows the load of the same rank.
  - So that wet laundry does not wait, the settings of the dryer (**My home**, its cycle rules) take a limit next to **Starts after the end of**: **At the latest** so many hours after it ends. The calculation then keeps the two cycles close; if the limit cannot be kept, the dryer is placed as close as it can be and a warning of the plan says so. Empty, there is no limit.
- **Week**: one line per day (its weather and production, the battery from morning to evening through its highest point, the appliances planned); tap a day to open it. On the right, **My requests** and the battery over the week (lowest, highest, sun forecast).

![Planning in the dark theme](images/en/planning-desktop-dark.png)

## Charts

The figures and charts of the plan, with the same tabs as Planning.

![Charts](images/en/curves-desktop-light.png)

- **A day**: summary cards (battery, grid, production, estimated against measured), the appliance schedule, the battery charge, the grid exchanges and the production and consumption curves, planned (dotted) and measured.
  - Tap a planned appliance in the schedule to change its start: one of the other starts the plan offers, or a time of your choice, today, tomorrow or a following day. Cancelling the launch is for today only.
- **Customize** chooses which cards appear and their order (the following days share Tomorrow's).
- A measurement the home cannot reach (a meter counting thousands of kWh in one hour) is set aside: a gap in the curves, nothing in the totals, and a line above the cards with **See the data** (**My home › Data**). The line appears on **Today**, **Planning** and **Charts**, only while the viewed range covers it: on **Yesterday** for a measurement of the day before, on **Week** only while it is today's. The other measurements stay displayed. Correcting the measurement in **My home › Data** (**Estimate** or **Recompute**) fills the gap.
- **Week**: a table with one row per day (weather, production, battery, purchases including peak hours, surplus, appliances); tap a day to unfold its details (appliances and their times, warnings, **See the detail**). On a phone, the table keeps day, production, battery and purchases, the rest is in the details. Then the week's charts.

![The week in Charts](images/en/curves-week-desktop-light.png)

## My home

Your home in plain sentences, in four tabs. Tap a line: its setting opens on its own, with its own **Save settings** button (from the bottom of the screen on a phone, in a window on a computer).

![My home](images/en/home-desktop-light.png)

- **Essentials**: your priority (pay as little as possible, use my own sun…), your contract, your grid connection (single-phase or three-phase), your panels and your battery: see [Tariffs](tariffs.md), [Your home and its rules](your-home.md#three-phase-homes) and [Battery](battery.md).
- **Devices**: the appliances placed at the best time, then, folded, those only monitored (often many plugs, with a search field), the production, grid and battery, and the devices Home Assistant suggests but WattSlot does not follow yet; **Add a device** and **Re-read Home Assistant**. Each device opens its sheet: its rules (see [Your home and its rules](your-home.md)), then, folded, its **sensors, name and type**, with the points to check and **Remove from my home**.
- **Data**: the check of your meters' data. A meter that counts more than the home can draw (a sensor dropout counted as a reset: thousands of kWh in one hour) is corrected automatically: recomputed from the raw readings while they are kept (three days), otherwise set aside, so the calculation and the charts ignore it. Each correction opens in a sheet: what happened, what was done, and the other choices (recompute, estimate from the neighbouring hours, set aside, undo). The original data is never changed. Correcting here also repairs the day's curves: **Recompute** and **Estimate** fill the gap left by an impossible measurement, **Set aside** keeps it; the day's totals follow. **Check a period** analyses one meter or all of them over the days you choose.

  ![The Data tab](images/en/home-data-desktop-light.png)

- **Advanced**: **Import the rules of Home Assistant tasks**, then **Ready-made templates**, **Back up or share** (export or import your home as a file), **Home graph** and **Appliance library** (for the curious), and the glossary.

## Assistant

**Chat with the assistant** and the setup of the **voice assistant**: see [Voice assistant](assistant.md).

![Assistant](images/en/assistant-desktop-light.png)

## Settings

![Settings](images/en/settings-desktop-light.png)

- **Notifications**: which messages, on which device, quiet hours ([Notifications](notifications.md)).
- **Automatic calculation**: every hour at a given minute (59 by default), or by hand; the Home Assistant to-do list whose tasks become requests.
- **Language and display**: six languages, five themes (Ivory, Graphite, Ocean, Meadow, Dusk) or **Automatic**, which follows your device's light or dark mode, and the **currency** of your prices and costs. By default it is Home Assistant's (Settings › System › General); changing it does not convert the prices already entered.
- **App status**: what is wrong, if anything, and how to fix it; the version, and whether a new one exists; links to support the project; the resources the app uses (processor averaged over 15 minutes, memory, its data on disk, the free space on that disk and what it writes to it); a report to attach to a bug report ([Troubleshooting](troubleshooting.md)).
- **Home Assistant connection** (standalone mode).
- At the bottom, **Stable version**, with **Give feedback** (a ready-made form on GitHub), and **Support WattSlot** (GitHub Sponsors and Ko-fi).

![App status](images/en/status-desktop-light.png)
