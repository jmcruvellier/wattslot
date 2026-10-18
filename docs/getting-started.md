# Getting started

*[Version française](fr/getting-started.md) · [User guide](README.md)*

The first time you open WattSlot, a guided path of four screens replaces the home page until the essential steps are done. Everything can be changed afterwards.

## The four first steps

1. **Connect the app to Home Assistant.** As a Home Assistant app there is nothing to do. In standalone mode, enter your Home Assistant address and log in (see [Installation](installation.md#standalone-docker)).
2. **Here is what we found in your home.** WattSlot reads Home Assistant's Energy dashboard and proposes your devices: solar production, grid, battery, water heater, washing machine, dryer, dishwasher, pool pump… Untick anything that should not be taken into account. A device missing from the Energy dashboard (a smart plug, a heat pump) can be added later in **My home › Appliances and sensors › Add a device**.
3. **What is your electricity contract?** Pick the closest template: tariff, battery and appliances are set in one go, with indicative prices to replace with yours (see [Tariffs](tariffs.md)).

   | Template | For |
   |---|---|
   | Solar, single price | The same price all day |
   | Solar, off-peak hours | Cheaper hours at night (indicative: midnight to 6 am and 10 pm to midnight) |
   | Solar, Tempo | French Tempo contract, day colour read from Home Assistant |
   | Solar, dynamic price | Hourly market prices read from a Home Assistant entity |

4. **All set.** Click **Calculate my first plan**. WattSlot then recalculates every hour on its own.

**See all steps** shows the full checklist at any time; it also stays on the Today screen, folded, as long as an optional step is left.

## The full checklist

| Step | Essential | What it needs |
|---|---|---|
| Connection to Home Assistant | yes | Home Assistant reachable |
| Home Assistant Energy dashboard | yes | Your grid meter, and your solar production if any, declared in Settings › Dashboards › Energy |
| Your home | yes | The proposed devices checked and saved |
| Solar forecast | yes, with panels | A forecast in the Energy dashboard (Forecast.Solar, Solcast, Open-Meteo…), or your panels described in **My home** (power, tilt, orientation): WattSlot then computes one with Open-Meteo |
| Consumption history | | Nothing to do: imported from Home Assistant on its own |
| First plan | yes | The steps above |
| Ready-made template | | Optional, sets everything in one go |
| Electricity tariff | | Otherwise a single price of €0.25/kWh is assumed |
| Battery | | Default settings until you adjust them |
| Notification | | A device to receive messages, see [Notifications](notifications.md) |

## The history import

To forecast your consumption and learn how long each appliance runs, WattSlot imports the history that Home Assistant already keeps (its **statistics**): hourly values as far back as they go, and 5-minute values for the last days.

- It starts on its own once your home is saved, one meter after the other. The checklist shows **Importing the Home Assistant history (N meter(s) left): nothing to do**.
- It takes from a few minutes to over an hour on a Raspberry Pi, depending on how much history you have and how many meters.
- Meanwhile the plan already works; past days fill in as the import goes.
- A sensor without statistics in Home Assistant (no `state_class`) is reported in **Settings › App status**: the plan then starts from its live measurements only.

## After the first plan

- **Today** tells you what is happening now and the next appliance to start.
- **Planning** shows the plan hour by hour, compared with what was measured.
- Adjust your rules in **My home**: see [Your home and its rules](your-home.md).
