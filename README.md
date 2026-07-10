# Verity

A Slack agent that takes a pasted link or plain-text claim and returns a
sourced, source-quality-weighted verdict — **True / False / Misleading /
Unverifiable** — posted as a threaded Slack reply.

Built for the Slack Agent Builder Hackathon, "Slack Agent for Good" track.

---

## Prerequisites

- Python **3.11 or later**
- A Slack workspace where you have permission to install apps
- An [Anthropic API key](https://console.anthropic.com/)
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
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) |
| `BRAVE_SEARCH_MCP_URL` | Your local or hosted Brave Search MCP server endpoint, e.g. `http://localhost:3001` |

---

## 5. Set up the Slack app

### Required bot token scopes (`OAuth & Permissions`)

| Scope | Reason |
|---|---|
| `app_mentions:read` | Receive `@Verity` mentions |
| `chat:write` | Post verdict replies |
| `channels:history` | Read messages in public channels |
| `groups:history` | Read messages in private channels the bot is added to |
| `channels:read` | List channels |

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
│       ├── claims.py         # Stage 2: identify checkable claim(s) via Claude
│       ├── verification.py   # Stage 3: query Brave Search MCP, rank sources
│       └── verdict.py        # Stage 4: synthesise verdict JSON via Claude
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
    [2] Claim Extraction  (Claude)
    Identify the checkable claim(s) and their type
    (single-fact / comparative / causal)
           │
           ▼
    [3] Verification  (Brave Search MCP)
    Query external sources; rank by authority tier
    (.gov/.edu/peer-reviewed > established news > generic web)
           │
           ▼
    [4] Verdict Synthesis  (Claude)
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
