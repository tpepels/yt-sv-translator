# YouTube → Swedish Line-by-Line Translator

This tool helps translate a bilingual script (Ukrainian + English) into Swedish, **line by line**, while keeping track of **who is speaking**.  
You work in **Google Sheets**. The tool reads each line, asks the OpenAI API to translate it, and writes the Swedish translation back into the sheet.

The translation is **context-aware**:
- It remembers **recent lines**
- It keeps a **glossary of recurring names and terms**
- It respects **speaker identity** (tone, phrasing) using the **Character** column

No programming knowledge is needed once setup is complete.

---

## 1. Requirements

You need:

| Service | Purpose |
|--------|---------|
| **OpenAI API Key** | To perform the translations |
| **Google Service Account Key** | To let the tool read/write your sheet |
| **Python 3.9+** | To run the script locally |

If the OpenAI or Google permissions are not yet configured, follow the **Onboarding Guide** (provided separately) before continuing.

---

## 2. Google Sheet Structure

Your sheet must contain **one line of dialogue per row**, like this:

| Character | Ukrainian | English | Swedish |
|---|---|---|---|
| Olena | Добрий день | Good afternoon | *(tool fills this)* |
| Serhiy | Так, я згоден | Yes, I agree | *(tool fills this)* |

You choose which column letters are which — just make sure they are consistent.

---

## 3. Installation

```bash
git clone <your-repo-or-folder>
cd yt-sv-translator
python3 -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
````

---

## 4. Configuration

Copy the example config:

```bash
cp config.ini.example config.ini
```

Open `config.ini` and update the following fields:

### OpenAI

```
[openai]
api_key = sk-...
model = gpt-4o-mini
```

### Google Sheets

```
[google]
service_account_json = /path/to/your-google-service-account.json
spreadsheet_name = Your Sheet Name

character_col = A
ukrainian_col = B
english_col   = C
swedish_col   = D
```

If your sheet has a header row (column titles), keep:

```
header_rows = 1
```

### Optional context tuning

```
[translation]
context_window = 4        # How many past lines to consider
max_glossary_terms = 40   # Keeps terminology consistent
episode_synopsis =        # Path to a TXT file describing the episode (optional)
```

---

## 5. Running the Translator

Basic usage:

```bash
python -m src.main
```

If you have multiple worksheet tabs, select one interactively or specify it:

```bash
python -m src.main --sheet "Episode 01"
```

Translate only first N rows:

```bash
python -m src.main --limit 50
```

Re-translate even if Swedish already exists:

```bash
python -m src.main --force
```

Dry run (show translations but do **not** write to sheets):

```bash
python -m src.main --dry-run
```

---

## 6. How Context Works (Why translations sound natural)

The tool does **not** send the entire transcript to the model.
Instead, it sends a **small rolling window**:

* The **last few speakers**
* The **last few translated lines**
* A **short glossary** of recurring names/terms
* Optional **episode summary**

This keeps translations **consistent** and **natural**, while staying efficient.

The **Character** column influences tone, but is **not shown in output**.
For example, Olena will consistently sound like Olena.

---

## 7. Troubleshooting

| Problem                                   | Cause                                 | Solution                                                                |
| ----------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------- |
| “Permission denied” when writing to sheet | Sheet not shared with Service Account | Open sheet → Share → Add service account email → Give **Editor** access |
| Translation not happening                 | Swedish column is already filled      | Run with `--force`                                                      |
| “Invalid API key”                         | API key pasted incorrectly or expired | Create a new key under OpenAI API Keys                                  |
| Translations sound inconsistent           | Increase `context_window` to 6–8      | Edit `config.ini` under `[translation]`                                 |

---

## 8. Recommended Workflow

1. Paste script lines into Google Sheet.
2. Keep **Character**, **Ukrainian**, **English** columns filled.
3. Run the translator.
4. Review Swedish output and adjust if needed.
5. Record narration.

---