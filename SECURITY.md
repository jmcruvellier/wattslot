# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately with this repository's **Security → Report a vulnerability** form (GitHub private vulnerability reporting). You can write in English or French.

Include the WattSlot version, the installation mode (Home Assistant app or standalone Docker) and the steps to reproduce. You should get a first answer within a week; a fix is published as a new version, and the advisory once users have had time to update.

## Supported versions

Only the **latest version** receives security fixes. Home Assistant offers the update in **Settings → Apps**; in standalone mode, pull the `latest` image.

## Scope

- **As a Home Assistant app**, WattSlot is only reachable through Home Assistant's ingress (the Supervisor's proxy) and from Home Assistant Core for its MCP server. It holds no password and uses the Supervisor's own token.
- **In standalone mode**, WattSlot has no login of its own: keep port 8100 on your local network, never expose it to the Internet. It only answers to local host names (and those of `WATTSLOT_ALLOWED_HOSTS`) and refuses changes sent by another site, against DNS rebinding and cross-site requests; a device on your local network keeps full access. The Home Assistant token or OAuth credentials are stored in the data volume.
- WattSlot reads Home Assistant and sends notifications; it does not control your devices by itself. The **Assistant** screen can pass your messages to Home Assistant's conversation agents, and Assist can control devices: as an app, only Home Assistant users reach it; in standalone mode this chat is off unless `WATTSLOT_HOME_ASSISTANT_CHAT=true`.

Issues in Home Assistant itself belong to the [Home Assistant project](https://www.home-assistant.io/security/).
