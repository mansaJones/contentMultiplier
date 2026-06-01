# Deploy to Render

How to take this app from "runs on localhost" to "has a real URL with a password gate."
Estimated time: ~15 minutes once the git repo is set up.

---

## What you need before starting

1. A GitHub account (Render also supports GitLab and Bitbucket — instructions below use GitHub).
2. A Render account — sign up at [render.com](https://render.com). Free tier requires no credit card.
3. Git installed locally. Test with `git --version`.
4. Your Anthropic API key on hand (the one already in your local `.env`).

---

## One-time setup: get the project into git

Skip this section if `MarTech\` is already a git repository pushed to GitHub.

### 1. Create a `.gitignore` at the project root

This is the single most important file for not leaking your API keys. From the `MarTech\` folder, create a file named `.gitignore` containing:

```
# Secrets — NEVER commit
.env
.env.local
credentials/

# Local state
.seen_ids.json
.seen_ids.json.corrupt
_work/
source/

# Python
__pycache__/
*.pyc
.venv/
venv/

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db
```

The `.env` line is the one that matters most. Without it, your real `.env` (with your live keys) ends up in the public history of your repo, and you will spend an afternoon rotating tokens.

### 2. Confirm `.env.example` has only placeholders

Open `.env.example` and verify every line has a placeholder value (e.g., `ANTHROPIC_API_KEY=sk-ant-...`), never a real key. This file IS committed — it documents the env vars the app needs.

### 3. Initialize the repo and make the first commit

From the `MarTech\` folder in a terminal:

```bash
git init
git add .
git commit -m "Initial commit: Content Multiplier web app"
```

If git complains about identity, set it once:

```bash
git config --global user.email "you@example.com"
git config --global user.name "Your Name"
```

### 4. Push to GitHub

Create a new repository on [github.com/new](https://github.com/new). Private is the safe default for anything that touches API keys. Then push:

```bash
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git
git push -u origin main
```

---

## Deploy to Render

### 1. Create a new Web Service

From the Render dashboard:

- **New** → **Web Service**
- Connect your GitHub account if it's the first time
- Pick the repository you just pushed
- Render reads the `Procfile` and auto-fills most settings

### 2. Verify the auto-detected settings

You should see:

| Setting | Value |
|---|---|
| **Name** | `content-multiplier` (or anything you want — becomes part of the URL) |
| **Region** | closest to you |
| **Branch** | `main` |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120` |

If the start command is empty, paste it manually — it's the line from `Procfile`.

### 3. Pick a plan

- **Free** — runs forever, but spins down after 15 minutes of inactivity. The first request after a spin-down takes 30-60 seconds to wake up. Fine for personal use.
- **Starter** ($7/mo) — always on. Worth it if the cold-start lag annoys you.

### 4. Set environment variables (critical)

Scroll to **Environment Variables** and add:

| Key | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Copy from your local `.env`. Paste it into Render's UI ONLY — never into chat, code, or commits. |
| `WEB_USERNAME` | `admin` | Or any username you prefer. |
| `WEB_PASSWORD` | a strong password | Generate one: `openssl rand -base64 24` in a terminal, or use a password manager. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Optional. Code already defaults to this. |

### 5. Click Create Web Service

Render starts the build. Watch the **Logs** panel. You should see, roughly in order:

1. Cloning your repo
2. Running `pip install -r requirements.txt` (1-2 minutes)
3. Starting `gunicorn app:app ...`
4. `Your service is live at https://content-multiplier-xxxx.onrender.com`

If the build fails, the logs will say why. The two most common causes:

- A missing or wrong-version dependency in `requirements.txt`
- Python version mismatch (Render defaults to a recent Python 3.11+; the app supports it)

---

## Verify the deploy

### 1. Hit the health endpoint

Visit `https://your-url.onrender.com/healthz` — should return `ok` instantly. No auth required.

### 2. Hit the form

Visit `https://your-url.onrender.com/` — the browser should prompt for username and password. Enter `admin` (or your `WEB_USERNAME`) and your `WEB_PASSWORD`. The form loads.

### 3. Run a real generation

Type a podcast premise, click **Generate**, wait ~15 seconds. The four panels populate.

If `/generate` returns a 500, the Render logs will have a Python traceback. The usual culprits: missing or invalid `ANTHROPIC_API_KEY`, or you're out of Anthropic credits.

---

## Things to know once it's deployed

### Cost monitoring

Set a hard spend cap in your [Anthropic Console](https://console.anthropic.com/settings/billing). Each generation costs roughly $0.04–0.08. The HTTP Basic auth gate stops anonymous abuse, but a spending cap is your safety net if the password ever leaks or your account is otherwise compromised.

### Updating the app

To deploy a change:

```bash
git add .
git commit -m "describe what changed"
git push
```

Render detects the push and rebuilds automatically. No clicking required.

### Logs

Render → your service → **Logs** tab. All `print` and `logging` output streams in real time. Useful when `/generate` misbehaves.

### Free tier cold starts

Inactive for 15 minutes? Render spins your service down. The next request takes ~30-60 seconds to wake the container before the actual work starts. If this bugs you, either upgrade to Starter ($7/mo) or set up a free uptime monitor (e.g., UptimeRobot) to ping `/healthz` every 5 minutes.

### Custom domain

Render → your service → **Settings** → **Custom Domain**. Add a CNAME at your DNS provider pointing to the `.onrender.com` URL. Render provisions an SSL cert automatically. Takes about five minutes.

---

## Troubleshooting cheat sheet

| Symptom | Most likely cause | What to check |
|---|---|---|
| Build fails on `pip install` | Missing or conflicting dependency | The exact pip error in the build log |
| 502 Bad Gateway | App crashed on startup | Logs for a Python traceback |
| 401 on every request | `WEB_PASSWORD` mismatch | The env var on Render matches what you're typing |
| 500 on `/generate` | Anthropic key missing/invalid, or out of credits | Logs for the actual exception |
| Long delay then 504 | Free tier cold start | Wait 60 seconds, retry. If still failing, check logs. |
| Form renders but Generate hangs | Anthropic API slow or timing out | Logs; try a shorter `length` setting |

---

## After it's deployed

The URL is yours. You can:

- Use it from your phone — HTTP Basic auth works on mobile browsers too
- Share it (URL + credentials) with one trusted person if you want
- Save it as a home-screen bookmark for one-tap access

When you want to add anything from the **Future Features** list in the project doc (token streaming, more tone presets, generation history, etc.), edit locally, commit, push. Render handles the rest.
