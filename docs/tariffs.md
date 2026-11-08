# Tariffs

*[Version française](fr/tariffs.md) · [User guide](README.md)*

The plan places your appliances where electricity is free (your surplus) or cheap. Set your contract in **My home › Essentials › My contract**. Without one, a single price of 0.25 per kWh, in your currency, is assumed and the plan only tries to buy as little as possible from the grid.

**Suggest from the energy dashboard** reads the prices declared in Home Assistant's Energy dashboard, if any.

## Kinds of tariff

| Kind | When | What to enter |
|---|---|---|
| **Single price** | The same price at any hour | The price per kWh |
| **Off-peak and peak hours** | A lower price at some hours | The peak price, then one **band** per cheaper range (from, to, price). A band can be **limited to some days or months** (weekends, summer) |
| **Announced day (Tempo, EJP…)** | The price depends on the day announced by the supplier and on the hour | The Home Assistant sensor giving today's day (and tomorrow's, optional), the hour the announced day starts, then each kind of day with its name, the other sensor states that mean it, its price outside bands and its bands. The first kind is used when the day is unknown. **Start from a template** fills in Tempo or EJP |
| **Dynamic price** | A price for every hour, from your supplier or the market | The Home Assistant sensor giving the price of the current and coming hours, its unit, and the price to use when it is not known |

## Price preview

Below an off-peak or announced-day tariff, a grid shows the price of every hour, from the lightest (cheapest) to the darkest (most expensive): the next seven days for off-peak hours, public holidays included, or one row per kind of day for an announced day. It follows your changes before you save them; hover over a cell to read its price. Prices read from Home Assistant use the sensor's last known state.

## Days, months and public holidays

Under each band, the **Days** boxes limit it to some days of the week (all ticked: every day), and **All year** unfolds the months. One box always stays ticked.

**Public holidays count as a Sunday**, below the bands, gives public holidays the Sunday prices, as most contracts do (weekend offers, Spanish 2.0TD, Italian F3). The country is Home Assistant's by default; choose a **region** when it has its own holidays (Alsace, Moselle…). The holidays come from the open-source *holidays* library.

Example, a reduced price on Wednesdays, weekends and public holidays: a band from 00:00 to 24:00 at the reduced price, with only Wednesday, Saturday and Sunday ticked, and **Public holidays count as a Sunday** ticked.

## Minute-precision bands

Bands use local times, with the start included and the end excluded: **01:30–05:38** includes 30 minutes of the first hour and 38 minutes of the last hour. Minutes range from 00 to 59; **24:00** is allowed only as an end time. Older configurations without minutes keep their whole-hour times.

The end follows the start within the day, for example **22:30–24:00**. Day-of-week and month filters apply to the **civil day being priced**. An end at or before the start defines an empty band; use **00:00–24:00** for a full day. If bands overlap, the **first band wins** for every minute. Time not covered by any band uses the base price. These rules apply to time-of-use and day-color bands.

The planner still uses **hourly prices**, not minute-by-minute prices: each hour is weighted by the number of minutes at each price. Mixed hours are rounded to six decimal places; a uniform hour retains its exact configured price. The dashboard and assistant show these hourly prices and hourly off-peak ranges, so a partially cheaper hour can be shown as off-peak. This is an hourly approximation, not sub-hourly optimization.

## Prices read from Home Assistant

Any fixed price (the base price, a band, a colour) can follow a Home Assistant sensor whose state is the price, for example those of the **Tarif EDF** integration (`sensor.tarif_heures_creuses_ttc`…). Click **read from Home Assistant** next to the price and enter the sensor: WattSlot reads it at every calculation, so a price change of your supplier needs nothing from you. The price you enter stays as a fallback when the sensor is unavailable. Choose the sensor's unit (per kWh, cents, per MWh) in **Unit of prices read from Home Assistant**.

The export price sensor (advanced settings) also accepts a sensor whose state is the price, besides a forecast. The time ranges of the bands stay set in WattSlot: these integrations do not give them.


**Export price of the surplus**: what a kWh sent to the grid earns you (0 if you do not sell it). It can also be read from a sensor. With the **lowest cost** objective, the plan prefers using your surplus at home when it is worth more than its resale price.

## Your contract

These two fields apply to every kind of tariff:

- **Subscription** (per month): the standing charge, without the kWh. It is divided by the number of days in the month and added to the cost of each day; the plan's indicators show it ("including subscription 0.50 €"). It does not change the plan, only the cost shown. Leave 0 to leave it out.
- **Contract power** (kVA): the power above which your main breaker trips, for example 6, 9 or 12 kVA. The plan avoids drawing more than this from the grid in any hour (1 kW per kVA), for example by not running the water heater and the dryer at the same time. If your base consumption alone is already above it, the plan says so in a warning. It works on hourly totals: a peak of a few minutes is not seen. Leave empty if you do not know it.

## Without solar panels

WattSlot is just as useful without panels: with off-peak hours, colour days or dynamic prices, the plan moves your appliances, water heater and car to the cheapest hours. Leave the solar production out of the Energy dashboard; the solar forecast step then does not apply.

## Tips

- Template prices are **indicative**: replace them with yours, they drive every decision.
- For Tempo, the colour sensor usually comes from the **RTE Tempo** integration; enter colour names exactly as the sensor shows them.
- For EJP, the peak day runs from 7 am to 1 am the next day: the template starts the announced day at 7 am and returns to the normal price from 1 am to 7 am. If your sensor shows other states than `on`/`off` or `EJP`/`Non EJP`, add them under **also recognized** (case and accents do not matter).
- Prices are per kWh, in the currency of your home (**Settings › Language and display**). For a sensor per MWh (spot prices) or in cents, choose that unit: WattSlot converts.
