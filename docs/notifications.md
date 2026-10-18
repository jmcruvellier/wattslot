# Notifications and reminders

*[Version française](fr/notifications.md) · [User guide](README.md)*

WattSlot sends its messages through Home Assistant, to a device that has the **Home Assistant companion app** (a `notify.mobile_app_…` service). Nothing is sent until you choose a device and enable a notification. Settings are in **Settings › Notifications**.

## Choosing where they go

- **Common device**: used by every notification that has no device of its own.
- **Device**, on each notification: to send, for instance, the daily recommendation to one phone and "start now" to another.
- **Other notification service**: any other `notify.*` service of Home Assistant.
- **Message language**: one of the six languages of the app.
- **Send a test** checks each notification right away.

## The five notifications

| Notification | When |
|---|---|
| **Today's recommendation** | Today's plan: appliances, battery, pool, balance and warnings. **Frequency**: after each run, only when the plan changes, or once a day from a given hour |
| **“Start X now”** | An appliance's planned cycle starts within the hour and it has not been started yet |
| **Off plan** | A planned cycle has not started 30 minutes after its time, or solar production is more than 25 % away from the forecast |
| **Battery full before noon** | The plan expects a full battery before noon: a good time to start an appliance, as the next surplus would go to the grid |
| **Tomorrow's forecast drops** | Tomorrow's planned production drops by more than 30 % against the highest forecast seen so far |

**Quiet hours**, on each notification: nothing is sent between two hours (the night, for instance).

## Reminders

On **Today**, under the next appliance to start, **Remind me** sends a notification when its slot begins. It uses the device of **“Start X now”**, or the common device.

## Requests from Home Assistant

The other way round, a task in a Home Assistant **to-do list** ("run the washing machine", with a due date) becomes a request: choose the list in **Settings › Automatic calculation**. The [voice assistant](assistant.md) can file requests too.
