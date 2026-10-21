# Voice assistant

*[Version française](fr/assistant.md) · [User guide](README.md)*

Ask Home Assistant's **Assist** about your energy — *“Why is the washing machine planned at 11 AM?”*, *“How much did the panels produce yesterday?”*, *“Will the battery be full today?”* — with the language model you already use: a local one on your network (Ollama, for instance) or an online service. WattSlot provides the answers through an **MCP server**; the plan itself is always computed without any language model.

The **Assistant** screen guides you step by step and checks the connection.

## 1. Connect WattSlot in Home Assistant

In Home Assistant: **Settings › Devices & services › Add integration › Model Context Protocol**, with the address shown on the **Assistant** screen (**Copy the MCP server address**):

- **As a Home Assistant app**: an address on Home Assistant's internal network, that only Home Assistant can reach.
- **Standalone**: `http://<WattSlot's address>:8100/mcp`, its address on your local network: only Home Assistant (and Open WebUI) call the MCP server, never your browser. WattSlot remembers it the first time you open the page from your local network, and shows it afterwards even from outside; **Change** corrects it.

## 2. Choose the conversation agent

1. Add a conversation agent: the **Ollama** integration (a model on your network) or an online service's integration.
2. Choose a model that can **call tools**, with a context size of at least **8,192 tokens**.
3. In the agent's options, choose WattSlot's MCP server as the **LLM API**, then pick this agent in Assist.

## 3. Paste the advised prompt

**Copy the prompt** on the Assistant screen and paste it into the conversation agent's instructions: it tells the model which tool to use for each question and not to invent anything. It exists in the six languages of the app.

**Check** confirms that the MCP server answers.

## What the assistant can and cannot do

- **It reads**: the plan of a day and its explanations, the week, the measurements, the forecast, your home and its problems.
- **It does one thing on its own**: file a request (*“Run the dishwasher at the best time before tomorrow evening”*), after confirming it with you.
- **It never** starts a computation, changes a setting or controls a device.

## Tips

- Small local models answer well with the advised prompt; if answers go wrong, check that the prompt is pasted and the context size is large enough.
- **Security**: Home Assistant's MCP integration has no other sign-in than OAuth, which WattSlot does not offer: the MCP server is therefore protected like the app itself (only Home Assistant can reach it as an app; local network only in standalone mode).
