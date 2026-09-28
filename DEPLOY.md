# Deploying Ask Your Data

Total time: **about 10 minutes**. Cost: **free**. No credit card.

The app is self-healing — `data/warehouse.db` is generated, not committed (it's in
`.gitignore`). On first launch the app runs the generator and build script itself, so you
can deploy straight from a git push with no manual step. Expect the **first load to take
~15 seconds** while it builds; after that it's instant.

---

## Step 1 — Put it on GitHub

```bash
cd ask-your-data

# already done for you (see "Git" below); if you need to redo it:
git init
git add .
git commit -m "Ask Your Data: text-to-SQL analytics copilot"

# create an empty repo on github.com/new (do NOT add a README/licence), then:
git remote add origin https://github.com/<your-username>/ask-your-data.git
git branch -M main
git push -u origin main
```

Once pushed, the CI workflow (`.github/workflows/ci.yml`) runs automatically and rebuilds
the warehouse, then runs **all three test suites + the 55-question evaluation**. A green
tick is itself a portfolio asset.

## Step 2 — Deploy on Streamlit Community Cloud

1. Go to **share.streamlit.io** and sign in with GitHub.
2. **New app** → *"Use an existing repo"*.
3. Fill in:

| Field | Value |
|---|---|
| Repository | `<your-username>/ask-your-data` |
| Branch | `main` |
| Main file path | **`app/streamlit_app.py`** |

4. **Deploy**. Watch the logs — you should see it install `requirements.txt`, then boot.

You'll get a URL like `https://<your-username>-ask-your-data-app-xxxxx.streamlit.app`.

## Step 3 — Add API keys (optional)

Skip this if you're happy with the offline rules engine — **the app works with no key at
all**. If you want the LLM path live:

**Manage app → ⋮ → Settings → Secrets**, then paste:

```toml
OPENAI_API_KEY    = "sk-..."      # or ANTHROPIC_API_KEY / GEMINI_API_KEY
OPENAI_MODEL      = "gpt-4o-mini"
```

Secrets are injected as environment variables and are **never** exposed to the browser.
Users can also paste their own key in the sidebar at runtime (session-only).

> ⚠️ **Ollama will not work on Streamlit Cloud.** `localhost` there means the server, not
> your laptop, and Cloud can't run Ollama. On Cloud, use a hosted provider (OpenAI / Groq /
> Gemini — Groq and Gemini both have free tiers). Run Ollama only when the app runs
> locally on your own machine.

## Step 4 — Verify the deployment

Open your URL and check:

- [ ] **Ask tab** — click an example button, get a chart + a written insight in English
- [ ] **Schema tab** — row counts load
- [ ] **Data quality tab** — the 17-check audit trail renders
- [ ] **Guardrails tab** — `DROP TABLE orders` is refused; the write-attempt button is refused
- [ ] **Evaluation tab** — the 55-question scorecard renders

## Step 5 — Add screenshots to the README (do this, it matters)

Recruiters skim. Three screenshots on the README reliably beat three more paragraphs.

Take these three and drop them into an `images/` folder:

1. **Ask tab** answering *"Top 5 cities by revenue"* — shows question, insight, chart, SQL
2. **Guardrails tab** blocking `DROP TABLE orders` — the security story at a glance
3. **Evaluation tab** — the scorecard

Then add near the top of `README.md`:

```markdown
![Ask](images/ask.png)
![Guardrails](images/guardrails.png)
![Evaluation](images/eval.png)
```

And commit:

```bash
git add images README.md
git commit -m "Add screenshots"
git push
```

While you're there, replace the CI badge placeholder at the top of the README:

```markdown
[![CI](https://github.com/<your-username>/ask-your-data/actions/workflows/ci.yml/badge.svg)](...)
```

## Step 6 — Put it in front of people

- **CV**, one line under Projects:
  > *Ask Your Data* — text-to-SQL analytics copilot: cleaning pipeline, read-only
  > guardrails, Streamlit app, 55-question eval suite with 0 wrong answers.
  > `streamlit.app/link` · `github.com/<you>/ask-your-data`
- **LinkedIn** — post the live link with *one* screenshot. Lead with the eval number, not
  the tech list.
- **Interview** — use the 60-second script at the bottom of the README.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FileNotFoundError: Database not found` | Self-heal didn't run | Should be impossible now — if it happens, run `python src/build_db.py` via the console and report it |
| Blank page / "app is not responding" | First load still building the warehouse | Wait 20s and refresh |
| `ModuleNotFoundError` | A missing dependency | Add it to `requirements.txt` and reboot the app |
| `use_container_width` error | Very old Streamlit | The shim handles both APIs; pin `streamlit>=1.30` |
| LLM mode does nothing | No key / wrong env var name | Secrets must match `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` exactly |
| Ollama "connection refused" | Ollama isn't on the server | Expected on Cloud — see the warning in Step 3 |

## Alternative hosts

| Host | Notes |
|---|---|
| **Streamlit Cloud** | Easiest, free, purpose-built. Recommended. |
| **Hugging Face Spaces** | Free; needs a `Dockerfile` with the SDK set to `streamlit` |
| **Render / Railway** | Free tiers exist; set start command to the `streamlit run` line |
| **Local** | `./run.sh` — required if you want Ollama |

---

## Git (already initialised)

A local git repo has been created with everything committed and ready to push:

```bash
cd ask-your-data
git log --oneline -1     # confirm the commit
git remote add origin https://github.com/<your-username>/ask-your-data.git
git branch -M main
git push -u origin main
```

`data/`, `__pycache__/`, `.env` and `.streamlit/secrets.toml` are gitignored — so no
11 MB database and no secrets ever reach GitHub.
