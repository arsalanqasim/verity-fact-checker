![Tests](https://github.com/arsalanqasim/verity-fact-checker/actions/workflows/tests.yml/badge.svg)

# Verity

A Slack agent that takes a pasted link or plain-text claim and returns a
sourced, source-quality-weighted verdict — **True / False / Misleading /
Unverifiable** — posted as a threaded Slack reply.

Built for the Slack Agent Builder Hackathon, "Slack Agent for Good" track.

---

## Prerequisites

- Python **3.11 or later**
- A Slack workspace where you have permission to install apps
- A [Google AI Studio API key](https://aistudio.google.com/apikey) (free tier, `GEMINI_API_KEY`)
- A Brave Search MCP server URL (local or hosted)

---

## 1. Clone the repo

```bash
git clone https://github.com/arsalanqasim/verity-fact-checker.git
cd verity-fact-checker
```

---

## 2. Create and activate a virtual environment

```bash
# Create venv (name it "venv" — it is gitignored)
python -m venv venv

# Activate — macOS / Linux
source venv/bin/activate

# Activate — Windows (PowerShell)
venv\Scripts\Activate.ps1

# Activate — Windows (cmd.exe)
venv\Scripts\activate.bat
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Configure environment variables

```bash
# Copy the template
cp .env.example .env
```

Then edit `.env` and fill in every value:

| Variable | Where to find it |
|---|---|
| `SLACK_BOT_TOKEN` | Slack app dashboard → **OAuth & Permissions** → Bot User OAuth Token (starts with `xoxb-`) |
| `SLACK_SIGNING_SECRET` | Slack app dashboard → **Basic Information** → Signing Secret |
| `SLACK_APP_TOKEN` | Slack app dashboard → **Basic Information** → App-Level Tokens → create one with `connections:write` scope (starts with `xapp-`) |
| `SLACK_USER_TOKEN` | (Optional) Slack app dashboard → **OAuth & Permissions** → User OAuth Token (starts with `xoxp-`), required for Workspace Memory search. |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free tier) |
| `BRAVE_SEARCH_MCP_URL` | Your local or hosted Brave Search MCP server endpoint, e.g. `http://localhost:3001` |

---

## 5. Set up the Slack app

The easiest way to set up the Slack app is by using the provided [manifest.json](file:///C:/Users/arsal/Desktop/slack-agent/manifest.json):

1. Go to the [Slack App Dashboard](https://api.slack.com/apps) and click **Create New App**.
2. Select **From an app manifest**.
3. Choose your workspace, then copy and paste the contents of `manifest.json` into the JSON tab.
4. Click **Create** and install the app to your workspace.

### Manual Scopes Configuration (If needed)

If you prefer to configure the app manually, ensure Socket Mode is enabled and the following bot token scopes are added in **OAuth & Permissions**:
- `app_mentions:read`
- `chat:write`
- `chat:write.public` (to post in public channels)
- `assistant:write`
- `channels:history`
- `groups:history`
- `canvases:write`
- `lists:write`
- `channels:join` (to automatically join a public channel when sharing a fact-check report if the bot is not already in it)

### Workflow Builder Custom Step Constraints

> [!NOTE]
> Custom Workflow Steps (using Bolt app functions) require the Slack app to be **org-ready** and installed at the **enterprise org level**. 
> Due to this native Slack platform constraint:
> 1. You must use a Slack Enterprise Grid sandbox workspace to test the custom step in Workflow Builder.
> 2. The step will only be available in workflows built within that specific enterprise org.
> 
> The code in [slack_app.py](file:///C:/Users/arsal/Desktop/slack-agent/src/slack_app.py) registers the `verify_claim` custom step handler natively, but the step itself will only appear in Workflow Builder once the manifest is imported into an Enterprise Grid workspace.

### Required user token scopes (`OAuth & Permissions` - Optional for Workspace Memory)

If utilizing `SLACK_USER_TOKEN` for workspace history checks via the Real-Time Search (RTS) API, grant the following granular user scopes to your app:

| Scope | Reason |
|---|---|
| `search:read.public` | Read access to all public channel messages |
| `search:read.private` | Read access to all private channel messages |
| `search:read.mpim` | Read access to all multi-person direct messages |
| `search:read.im` | Read access to all direct messages |
| `search:read.files` | Read access to all files |
| `search:read.users` | Read access to a workspace's users |

### Enable Socket Mode

In your Slack app dashboard → **Socket Mode** → enable it.  
Create an App-Level Token with the `connections:write` scope and save it as
`SLACK_APP_TOKEN`.

### Subscribe to bot events (`Event Subscriptions`)

- `message.channels`
- `message.groups`
- `app_mention`

---

## 6. Run the Brave Search MCP server locally

The Brave Search MCP server handles the Server-Sent Events (SSE) connection that acts as Verity's core verification engine. 

1. Ensure you have Node.js 18+ installed.
2. Navigate to the MCP server directory:
   ```bash
   cd brave-search-mcp-sse
   ```
3. Install dependencies:
   ```bash
   npm install
   ```
4. Create a `.env` file in the `brave-search-mcp-sse` folder containing your Brave Search API key:
   ```env
   BRAVE_API_KEY=your_brave_api_key_here
   PORT=3001
   ```
5. Start the server:
   ```bash
   npm run dev
   ```
   The server will start on `http://localhost:3001`.

---

## 7. Run the Slack app locally

```bash
python -m src.slack_app
```

The app uses Socket Mode so no public URL / reverse proxy is needed for local
development.

---

## 8. Run the tests

```bash
pytest
```

All pipeline modules under `src/pipeline/` have corresponding test files under
`tests/`.  Per project convention, a module is not considered done until its
unit test passes with a fixed input/output.

---

## Project structure

```
verity-fact-checker/
├── src/
│   ├── slack_app.py          # Bolt entrypoint — event handlers only
│   └── pipeline/
│       ├── ingestion.py      # Stage 1: detect input type, extract text
│       ├── claims.py         # Stage 2: identify checkable claim(s) via Gemini
│       ├── verification.py   # Brave Search MCP query + source authority scoring
│       ├── mcp_client.py     # Background loop event loop transport for MCP client
│       ├── reporting.py      # Stage 5: create Slack Canvas reports & update Slack Lists
│       └── agent.py          # Stage 3 & 4: agentic loop + verdict synthesis (Gemini)
├── tests/
│   ├── test_ingestion.py
│   ├── test_claims.py
│   ├── test_verification.py
│   ├── test_mcp_client.py
│   ├── test_reporting.py
│   ├── test_agent.py
│   ├── test_agent_fallback.py
│   └── test_slack_app.py
├── .env.example              # Variable names — copy to .env, never commit .env
├── requirements.txt
└── README.md
```

---

## Pipeline overview

```
User pastes link or claim in Slack
           │
           ▼
    [1] Ingestion
    Detect input type → extract raw text
    (plain text / YouTube transcript / article body)
           │
           ▼
    [2] Claim Extraction  (Gemini)
    Identify the checkable claim(s) and their type
    (single-fact / comparative / causal)
           │
           ▼
    [3] Agentic Verification  (Brave Search MCP, via agent.py)
    Gemini runs a manual tool loop calling search_web_evidence;
    query external sources; rank by authority tier
    (.gov/.edu/peer-reviewed > established news > generic web)
           │
           ▼
    [4] Verdict Synthesis  (Gemini, in agent.py)
    Forced structured synthesis turn produces typed JSON:
    { verdict, confidence, summary, sources[] }
    (citation whitelist + post-processing filter enforced here)
           │
           ▼
    [5] Slack Delivery  (Bolt + Block Kit)
    Post formatted threaded reply
```

---

## How web verification works (for judges / operators)

Web evidence is gathered via a **Brave Search MCP server connected over SSE**
(`BRAVE_SEARCH_MCP_URL`). The agent loop calls this server live for every
fact-check. **If the MCP server is unreachable, Verity does not guess:** it
returns an honest `Unverifiable` verdict (confidence capped at 0.30) with no
fabricated source citations. This is the intended safety design, not a failure
mode — a confident answer is never produced from ungrounded parametric
knowledge.

---

## Contributing

- Commit after each working stage, not in one giant commit.
- Never commit `.env` or any file containing real secrets.
- Every new pipeline function needs a corresponding pytest test before it is
  merged.
