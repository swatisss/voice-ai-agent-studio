# Customer chat app (CP-0049)

A separate Next.js app that shows how an outside system uses the Voice AI platform. It talks to the agents **only through the public `/v1` API**, with a member API key held by its own server routes; the browser never sees the key.

Specs: `specs/architecture/external-chat-app.md`, `specs/architecture/human-message-channel.md`, `specs/ui/chat-app.md`.

## Run it next to the platform

```bash
python scripts/dev.py --chat        # web :3000 + API :8000 + this app on :3100; creates the chat-app key on first run
```

Or by hand:

```bash
cd apps/chat
npm install
cp .env.example .env.local          # set VOICEAI_API_KEY (a member key from Studio > Settings > API keys)
npm run dev                         # http://localhost:3100
```

| Variable | Default | Meaning |
|---|---|---|
| `VOICEAI_API_URL` | `http://localhost:8000` | Platform base URL |
| `VOICEAI_TENANT_ID` | `northgate-health` | Business unit of the key |
| `VOICEAI_API_KEY` | none | Member key (required) |
| `CHAT_BRAND_NAME` | `Northgate Health` | Name in the header |

## See the human hand-off

1. Open http://localhost:3100 and ask "I want to speak to a human".
2. The chat shows "We're connecting you to a specialist".
3. In the Studio, sign in (or open) the Agent console, accept the escalation and type in the **Conversation** panel.
4. The chat shows "You're now talking to a human agent" and the specialist's replies. Resolve the escalation to end the chat.

## Tests

```bash
npm test          # node:test against a stub platform (Node 24)
npm run typecheck
npm run build
```
