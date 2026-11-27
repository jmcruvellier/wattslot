# Sensors in Home Assistant (experimental)

*[Version française](fr/sensors.md) · [User guide](README.md)*

WattSlot can write some of its forecasts to Home Assistant sensors, so that your dashboards, your automations or another integration can read them. This is **experimental** and **off by default**: the sensors and their format may still change.

## Home consumption forecast

Switch on **Settings › Calculation and data › Sensors in Home Assistant › Publish the home consumption forecast**. Nothing else to install: WattSlot uses the connection it already has, as a Home Assistant app or with Docker.

Three sensors appear in Home Assistant, in kWh:

| Sensor | Value |
|---|---|
| `sensor.wattslot_home_consumption_forecast_remaining_today` | Expected consumption of the home from now until midnight |
| `sensor.wattslot_home_consumption_forecast_today` | Expected consumption of the whole day |
| `sensor.wattslot_home_consumption_forecast_tomorrow` | Expected consumption of tomorrow |

These are the numbers behind the consumption curve of the **Today** and **Planning** screens: the usual consumption of your home at each hour (same day of the week first), plus the appliances the plan has placed. The battery is not part of it.

Each sensor also carries two attributes: `forecast_date` (the day the forecast is for) and `computed_at` (when the plan was last computed).

## When they are updated

- after each plan computation (every hour by default);
- every quarter of an hour, because the rest of today decreases with time;
- each time WattSlot reconnects to Home Assistant.

A sensor is **unavailable** when WattSlot has no plan for that day yet: before the first computation, or just after midnight until the next one. An integration that reads it should then fall back to its own estimate.

## Good to know

- **No history of their own.** A forecast is not a measurement: the sensors have no `state_class`, so Home Assistant keeps no long-term statistics for them. Their recent states stay in the history like any other sensor.
- **No device, no settings in Home Assistant.** These sensors are written through Home Assistant's API: they have no unique ID, so they cannot be renamed, hidden or assigned to an area from Home Assistant's interface.
- **After a restart of Home Assistant** they disappear for a moment, then come back when WattSlot reconnects, usually within a minute.
- **Switching the setting off** removes them from Home Assistant.
- **Administrator account.** With Docker, the account used for the Home Assistant connection must be an administrator: Home Assistant only lets administrators write states. Otherwise the setting shows that Home Assistant refuses the write.
- WattSlot never offers its own sensors when you choose the sensors of your home: it does not read back what it publishes.

## Example: a dashboard card

```yaml
type: entities
title: Home consumption forecast
entities:
  - sensor.wattslot_home_consumption_forecast_remaining_today
  - sensor.wattslot_home_consumption_forecast_today
  - sensor.wattslot_home_consumption_forecast_tomorrow
```

Tell us what you do with these sensors, and which other ones you would like (next appliance to start, expected cost of the day…): [give feedback](https://github.com/jmcruvellier/wattslot/issues/new?template=beta_feedback.yml).
