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

## 6. Run the Slack app locally

```bash
python -m src.slack_app
```

The app uses Socket Mode so no public URL / reverse proxy is needed for local
development.

---

## 7. Run the tests

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
│       ├── verification.py   # Stage 3: query Brave Search MCP, rank sources
│       └── verdict.py        # Stage 4: synthesise verdict JSON via Gemini
├── tests/
│   ├── test_ingestion.py
│   ├── test_claims.py
│   ├── test_verification.py
│   └── test_verdict.py
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
    [3] Verification  (Brave Search MCP)
    Query external sources; rank by authority tier
    (.gov/.edu/peer-reviewed > established news > generic web)
           │
           ▼
    [4] Verdict Synthesis  (Gemini)
    Produce structured JSON:
    { verdict, confidence, summary, sources[] }
           │
           ▼
    [5] Slack Delivery  (Bolt + Block Kit)
    Post formatted threaded reply
```

---

## Contributing

- Commit after each working stage, not in one giant commit.
- Never commit `.env` or any file containing real secrets.
- Every new pipeline function needs a corresponding pytest test before it is
  merged.
