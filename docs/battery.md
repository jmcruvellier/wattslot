# Battery

*[Version française](fr/battery.md) · [User guide](README.md)*

WattSlot does not control your battery: it simulates how it behaves (it charges on any surplus and discharges on any deficit, like most home batteries in self-consumption mode) to place your appliances where they are most useful. Several batteries are seen as one, and each can have its own settings (see [Several batteries](#several-batteries)). Settings are in **My home › Essentials › Battery**.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| **Never discharge below** | 10 % | The floor: a reserve for the night or a power cut |
| **Higher floor over some ranges** | none | A higher reserve at some hours, for instance 30 % from 6 pm to 10 pm |
| **Maximum charge power** / **discharge power** | enough to charge or empty half the battery in one hour | Your battery's limits, on its datasheet |
| **The battery charges and discharges from … to …** | all day | For batteries that only work at some hours |
| **Aim for a full charge regularly**, at least every N days | off | Lithium batteries recalibrate their charge measure when they reach 100 %: the plan then keeps enough surplus for it, and may skip some pool hours on those days |

The capacity comes from Home Assistant when a sensor gives it, otherwise from its sheet in **My home › Devices** (**Sensors, name and type**).

## Several batteries

The settings above apply to all your batteries. When the home has several, the **Battery** sheet lists each one under **Settings per battery**: **Give this battery its own settings** opens the same settings for that battery alone; **Go back to the home's settings** removes them.

The calculation still sees your batteries as one:

- the **powers** add up (with no setting, each counts for half its capacity per hour);
- the **floor** follows each battery's capacity: 30 % of a 2 kWh battery and 10 % of a 6 kWh battery keep 1.2 kWh in reserve, hour by hour with the ranges;
- the **active range** is when at least one battery runs, and the **full charge** follows the battery that asks for it most often.

This is exact for batteries connected at the same place. Two batteries that do not see the same surplus (one per phase in a three-phase home, for instance) may fill differently: the plan is then slightly optimistic.

In a **three-phase** home (see [Your home and its rules](your-home.md#three-phase-homes)), a box asks whether **the battery offsets the total of the three phases** (it follows a three-phase meter) or only its own phase. The plan does not use it yet.

## What you see

- **Today**: the charge now, its highest point and its level at midnight.
- **Planning**: the planned charge (dotted) against the measured one, the floor line, and the battery's charge and discharge in the appliance schedule.
- **Battery full before noon** ([notification](notifications.md)): the next surplus would go to the grid, a good time to start an appliance.

## Good to know

- WattSlot only **recommends**. Controlling the battery (slowing its charge in the morning so that it is not full before the solar peak, charging it at off-peak hours) is planned for a later version, device by device.
- The battery's real behaviour is measured: if it differs from the settings (a lower power, a different floor), the measured curve shows it.
