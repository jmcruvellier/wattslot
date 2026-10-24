# Tariffs

*[Version française](fr/tariffs.md) · [User guide](README.md)*

The plan places your appliances where electricity is free (your surplus) or cheap. Set your contract in **My home › Essentials › My contract**. Without one, a single price of 0.25 per kWh, in your currency, is assumed and the plan only tries to buy as little as possible from the grid.

**Suggest from the energy dashboard** reads the prices declared in Home Assistant's Energy dashboard, if any.

## Kinds of tariff

| Kind | When | What to enter |
|---|---|---|
| **Single price** | The same price at any hour | The price per kWh |
| **Off-peak and peak hours** | A lower price at some hours | The peak price, then one **band** per cheaper range (from, to, price). A band can be **limited to some days or months** (weekends, summer) |
| **Day color (Tempo)** | The price depends on the day colour and the hour | The Home Assistant sensor giving today's colour (and tomorrow's, optional), the hour the colour day starts, then each colour with its price outside bands and its bands. The first colour is used when the colour is unknown |
| **Dynamic price** | A price for every hour, from your supplier or the market | The Home Assistant sensor giving the price of the current and coming hours, its unit, and the price to use when it is not known |

## Minute-precision bands

Bands use local times, with the start included and the end excluded: **01:30–05:38** includes 30 minutes of the first hour and 38 minutes of the last hour. Minutes range from 00 to 59; **24:00** is allowed only as an end time. Older configurations without minutes keep their whole-hour times.

An end earlier than the start crosses midnight, for example **22:30–00:38**. Day-of-week and month filters apply to the **civil day being priced**, including the part after midnight; they do not inherit the previous day's filters. Identical start and end times define an empty band, not a full day; use **00:00–24:00** for a full day. If bands overlap, the **first band wins** for every minute. Time not covered by any band uses the base price. These rules apply to time-of-use and day-color bands.

The planner still uses **hourly prices**, not minute-by-minute prices: each hour is weighted by the number of minutes at each price. Mixed hours are rounded to six decimal places; a uniform hour retains its exact configured price. The dashboard and assistant show these hourly prices and hourly off-peak ranges, so a partially cheaper hour can be shown as off-peak. This is an hourly approximation, not sub-hourly optimization.

## Selling your surplus

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
- Prices are per kWh, in the currency of your home (**Settings › Language and display**). For a sensor per MWh (spot prices) or in cents, choose that unit: WattSlot converts.
