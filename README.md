# Transplantation-Medicine LLM Evaluation

A Streamlit tool to evaluate and compare LLMs (small/local, medium/on-prem, big/frontier)
on transplantation-medicine knowledge. Two-stage workflow: an **evaluator** scores model
answers, a **medical reviewer** validates and verifies them, and a **results** view ranks
the best model per category and overall.

The default and lowest-friction setup is a **Google Sheet** backend deployed on
**Streamlit Community Cloud** — no server to run, and because the Sheet is a remote store
it is unaffected by Community Cloud's ephemeral filesystem. Local Excel and SharePoint
backends are also included (see *Other backends*).

---

## Recommended path: Google Sheets + Streamlit Community Cloud

### 1. Create the Google service account (~10 min)
1. In the [Google Cloud console](https://console.cloud.google.com), create (or pick) a
   project and **enable the Google Sheets API**.
2. Create a **service account**, then create a **JSON key** for it and download the file.
3. Create a Google Sheet (any name). **Share it** with the service account's
   `client_email` (from the JSON), giving **Editor** access. This is the step that grants
   the app access — no OAuth screens, no admin consent.
4. Copy the sheet's id from its URL: `.../spreadsheets/d/<THIS-IS-THE-ID>/edit`.

The worksheet tab and its header row are created automatically on first run, so there is
no init script for this backend.

### 2. Put the code on GitHub
Push this folder to a GitHub repo (private is fine). `.gitignore` already excludes secrets
and local data, so nothing sensitive is committed.

### 3. Deploy on Streamlit Community Cloud (~5 min)
1. At [share.streamlit.io](https://share.streamlit.io), **New app** → pick the repo,
   branch, and `app.py`.
2. Open **Advanced settings → Secrets** and paste your secrets (template below). The
   service-account JSON goes under `[gcp_service_account]`; never commit it to the repo.
3. **Deploy.** Share the resulting URL with the reviewer — that is all they need.

### Secrets template
Copy `.streamlit/secrets.toml.example`. The essential parts:
```toml
[storage]
backend = "google"

[gsheets]
spreadsheet_id = "1AbCdEf...your-sheet-id..."
worksheet = "Evaluations"

[gcp_service_account]
type = "service_account"
project_id = "your-project"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "eval-bot@your-project.iam.gserviceaccount.com"
# ... remaining JSON key fields ...
```

### Run it locally first (optional)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in, or set backend="local"
streamlit run app.py
```
With `backend = "local"` (or no secrets at all) it uses a local `evaluations.xlsx`, so you
can try the whole workflow before touching Google. All dependencies are pure Python and run
on an M-series Mac.

> **Data location note.** Google Sheets + Community Cloud places the data on Google and the
> app on Streamlit's (Snowflake-run) infrastructure — both outside your M365 tenant. The
> evaluation content is LLM knowledge answers and scores, with no patient data, so this is
> low-sensitivity; still worth a one-line check with whoever owns data policy. If everything
> must stay in-tenant, use the SharePoint backend on Azure App Service instead (see below).

---

## How it works

The app does **not** call the models — you paste each model's answer in. That keeps it
usable for a local Ollama/LM Studio model and a frontier API alike.

- **Add evaluation** — pick a model (or define a new one with its category), pick a prompt,
  paste the answer, score each criterion 1–5 from a dropdown. Saved entries enter the
  review queue.
- **Review & verify** — the reviewer sees the prompt, answer anchor, output and the
  evaluator's scores pre-filled, adjusts where they disagree, and marks it **verified**.
  Both evaluator and reviewer scores are stored, so rater agreement can be measured later.
- **Results** — best model per category, overall ranking chart, per-criterion heatmap,
  coverage warnings, CSV/Excel export. Toggle "verified scores only" to restrict to
  reviewed entries.

### The rubric (edit in `config.py`)

| Criterion | Weight | What it measures |
|---|---|---|
| Factual accuracy | 0.35 | Correctness; penalises hallucination |
| Completeness | 0.20 | Coverage of the key points |
| Conceptual integration | 0.20 | Correct reasoning across concepts |
| Clinical relevance | 0.15 | Appropriate, guideline-concordant framing |
| Clarity & structure | 0.10 | Communication quality |

Plus a **safety flag** that *caps* the weighted score rather than nudging it: `major
inaccuracy` caps at 2.5, `potentially harmful` caps at 1.5 — so a dangerous answer can
never look good. Change weights, the 1–5 scale, the anchors, or the caps in `config.py`.

Aggregation: weighted score per (model × prompt) → mean per model → ranked within each
category and overall. Verified scores override the evaluator's once a row is verified.

### The prompts (edit in `prompts.yaml`)

Eight starter prompts span immunology/rejection, pharmacology (drug interaction), Swiss
allocation policy, donor management, HLA sensitisation, machine perfusion, a
clinical-reasoning vignette, and consent models — across recall, completeness, reasoning,
application and nuance. Each has `expected_key_points` shown to raters as an answer anchor.
These are a scaffold; refine them as the domain owner. Add a prompt by appending an entry
with a new `id`.

---

## Other backends

Storage sits behind one interface (`EvalStore` in `storage.py`), so backends are
interchangeable with no UI changes — set `backend` in secrets.

- **local** — a plain `.xlsx` on disk. Best for development or a single machine.
- **sharepoint** — Excel in SharePoint via Microsoft Graph, to keep data in your M365
  tenant. Needs an Azure AD app registration with `Sites.ReadWrite.All` (admin-consented).
  Run `python init_workbook.py llm_eval.xlsx` to create the named table, upload it, and fill
  the `[sharepoint]` secrets. Pair with **Azure App Service** for an in-tenant deployment.

If this ever outgrows a spreadsheet, a `SQLiteStore`/`PostgresStore` drops into the same
interface (SQLite needs persistent disk, so use it when self-hosting — e.g. Azure App
Service or a Raspberry Pi — not on Community Cloud's ephemeral disk).

## Files

```
app.py            Streamlit entry + navigation
views.py          the three pages (add / review / results)
config.py         criteria, weights, scale, safety caps, categories, schema
scoring.py        weighted score, safety cap, per-model & per-category aggregation
storage.py        EvalStore interface + Google Sheets, local Excel, SharePoint backends
prompts.yaml      the evaluation prompts
requirements.txt
.streamlit/secrets.toml.example
.gitignore
```
