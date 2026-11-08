# Notifications and reminders

*[Version française](fr/notifications.md) · [User guide](README.md)*

WattSlot sends its messages through Home Assistant, to a device that has the **Home Assistant companion app** (a `notify.mobile_app_…` service). Nothing is sent until you choose a device; only the resource alerts are on by default, the other notifications have to be enabled. Settings are in **Settings › Notifications**.

## Choosing where they go

- **Common device**: used by every notification that has no device of its own.
- **Device**, on each notification: to send, for instance, the daily recommendation to one phone and "start now" to another.
- **Other notification service**: any other `notify.*` service of Home Assistant.
- **Message language**: one of the six languages of the app.
- **Send a test** checks each notification right away.

## The seven notifications

| Notification | When |
|---|---|
| **Today's recommendation** | Today's plan: appliances, battery, pool, balance and warnings. **Frequency**: after each run, only when the plan changes, or once a day from a given hour |
| **This week's plan** | The appliances planned for the coming days, one line per day ("Saturday, October 17: Washing machine 11 AM–1 PM"). **Sending days and hour**: one or more days of the week, from a given hour (Sunday from 6 pm by default) |
| **“Start X now”** | An appliance's planned cycle starts within the hour and it has not been started yet |
| **Off plan** | A planned cycle has not started 30 minutes after its time, or solar production is more than 25 % away from the forecast |
| **Battery full before noon** | The plan expects a full battery before noon: a good time to start an appliance, as the next surplus would go to the grid |
| **Tomorrow's forecast drops** | Tomorrow's planned production drops by more than 30 % against the highest forecast seen so far |
| **Resource alerts** | The data disk is nearly full, WattSlot uses a lot of memory, or a plan computation takes very long (see [Troubleshooting](troubleshooting.md)). Once a day for each alert while it lasts. **On by default**: switch it off here |

**Quiet hours**, on each notification: nothing is sent between two hours (the night, for instance).

Notifications sent "from a given hour" leave with the first automatic run after that hour (runs take place every hour, at the minute set in **Settings › Automatic calculation**). This week's plan is a forecast: beyond two or three days it follows a still uncertain weather forecast, and the plan is recalculated every hour. "Start X now" and reminders follow the plan of the moment.

## Reminders

On **Today**, under the next appliance to start, **Remind me** sends a notification when its slot begins. It uses the device of **“Start X now”**, or the common device.

## Requests from Home Assistant

The other way round, a task in a Home Assistant **to-do list** ("run the washing machine", with a due date) becomes a request: choose the list in **Settings › Automatic calculation**. The [voice assistant](assistant.md) can file requests too.
