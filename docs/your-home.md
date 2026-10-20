# Your home and its rules

*[Version française](fr/your-home.md) · [User guide](README.md)*

Everything here is in **My home**: the rules of each appliance in the **Devices** tab, your priority, contract, panels and battery in **Essentials**. A ready-made template sets most of it in one go; then adjust what differs in your home.

## What WattSlot does with each device

The **type** of a device decides what the plan can do with it, through its **behaviour**:

| Behaviour | Typical devices | What the plan does |
|---|---|---|
| **Cycle to start** | Washing machine, dryer, dishwasher | Picks the best start for one program, knowing its usual energy and length (learned from the history) |
| **Energy needed by a deadline** | Water heater, electric car | Delivers a given energy before an hour, without exceeding a power (all at once or in steps) |
| **Runtime to schedule** | Pool pump | Places a number of hours per day, by season, when the sun produces the most |
| **Storage** | Home battery | Charges and discharges around the plan (see [Battery](battery.md)) |
| **Production** | Solar panels | Gives the forecast |
| **Grid exchange** | Your meter | Measures what you buy and the surplus |
| **Tracked consumption only** | Fridge, TV, anything else | Measured, counted in the consumption, never placed |

Untick **Scheduled by planning** on a device to keep it only monitored.

## When a cycle is due

A cycle (washing machine…) is placed on a day when something asks for it:

- **A request**: **Request an appliance** (`+`), *as soon as possible* or *at the latest on* a date. The plan picks the best time before that date. **Planning › My requests** lists them.
- **A Home Assistant to-do list**: choose the list in **Settings › Automatic calculation**; a task such as "run the washing machine", with a due date, becomes a request.
- **A recurrence**, in the device's **Cycle rules**: every N days since the last cycle, on some days of the week, or an advanced rule (iCalendar format). The recurring Home Assistant tasks of that device are then ignored.

Other cycle rules:

- **Starts after the end of** another device: the dryer after the washing machine, the same day.
- **May be postponed by** N days at most (2 by default): a waiting cycle can move to a sunnier day.

## Time constraints

For any placed device, in its **Time constraints**:

| Constraint | Example |
|---|---|
| **Forbidden** from … to … | No washing machine between 10 pm and 7 am (noise) |
| **Not before** … | Dishwasher not before 9 am |
| **Finished before** … | Car charged before 7 am |

A constraint is strict by default. Tick **Soft** to have it met if possible: otherwise the plan places the device anyway and says so.

## Energy needs and runtimes

- **Energy needed by a deadline**: the energy to deliver, the maximum power, **Not before** and **Before** hours, **In steps** (all or nothing at full power, for a simple on/off plug), and **Every day** or only when a task asks for it.
- **Runtime to schedule**: one or more **speeds** with their power (eco, silent… for a variable-speed pump), the **minimum hours per day** in summer, mid-season and winter, the days that can be skipped when the battery needs its full charge, and the maximum number of starts per day. With no speed set, a single one is used, at the power measured over the last 30 days.

## Panels

Needed only if Home Assistant's Energy dashboard has no solar forecast: describe each **array** (one per orientation) with its **peak power** (kWp, on the installer's invoice), its **tilt** and its **orientation**, plus the inverter's maximum power if it caps the production. WattSlot then computes a forecast with Open-Meteo, at your Home Assistant's location (rounded). A forecast integration in Home Assistant (Forecast.Solar, Solcast…) is usually more accurate.

## Objective

**The planner aims for**:

| Choice | In short |
|---|---|
| **The lowest cost** (default) | The lowest bill: buy at the cheapest hours, use the surplus rather than selling it cheap |
| **Autonomy** | Buy the least energy from the grid, even if a bit more expensive |
| **Self-consumption** | Use as much of your production on site, even if it means buying at peak hours |
| **The least CO₂** | Buy when grid electricity emits the least (needs a carbon intensity sensor) |
| **A compromise** | Free weights between cost, buying, surplus, CO₂ and battery care |

## Templates, backup and sharing

- **Ready-made templates** sets behaviours, tariff, objective and battery at once. **See what would change** before **Apply the template**: devices it does not know stay as they are.
- **Back up or share** exports your home and its settings as a readable file, and imports one back: to keep a copy, move to a new installation, or attach to a bug report. Your Home Assistant connection is never in it.
