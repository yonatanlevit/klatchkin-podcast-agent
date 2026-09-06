# Klatchkin Podcast Agent

An automated agent that listens to the latest episode of the Hebrew podcast **"ברדיו עם קלצ'קין"**, extracts the cultural recommendations mentioned in it (books, films, series, music albums), and sends them as a formatted summary to Telegram.

The whole thing runs itself once a day on GitHub Actions — no server needed.

## How it works

```
RSS feed  →  download MP3  →  upload to Gemini  →  extract recommendations  →  Telegram
                    ↑                                                              ↓
              skip if already                                              save episode title
              processed                                                    to last_processed.txt
```

1. **Fetch** — parses the podcast RSS feed (`https://feed.podbean.com/epgb/feed.xml`) and takes the newest entry.
2. **Deduplicate** — compares the episode title against `last_processed.txt`; if it matches, the run exits without doing anything.
3. **Download** — streams the episode audio to `podcast_episodes/latest_episode.mp3`.
4. **Analyze** — uploads the audio to the Google Files API, waits for processing, and asks `gemini-2.5-flash` to extract every active cultural recommendation: media type, title and creator, who recommended it and why. The prompt asks for Telegram-flavored HTML (`<b>`, `<i>`) and no Markdown.
5. **Notify** — sends the result to a Telegram chat. If the episode had no recommendations, the model replies `NO_RECOMMENDATIONS` and a short "nothing this time" message is sent instead.
6. **Clean up** — the episode title is written to `last_processed.txt`, the uploaded file is deleted from Google's servers, and the local MP3 is removed.

## Requirements

- Python 3.10+
- A [Google Gemini API key](https://aistudio.google.com/apikey)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather)) and the target chat ID

```bash
pip install feedparser requests google-genai python-dotenv
```

## Configuration

Create a `.env` file in the project root (it is gitignored):

```env
GEMINI_API_KEY=your_gemini_api_key
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

All three are required — the script raises on startup if any is missing.

## Running locally

```bash
python podcast_agent.py
```

To force a re-run on an episode that was already processed, clear `last_processed.txt` first.

## Running on GitHub Actions

`.github/workflows/run_agent.yml` runs the agent daily at **09:13 UTC** (12:13 Israel time) and can also be triggered manually via **workflow_dispatch**.

Add the three values above as repository secrets under **Settings → Secrets and variables → Actions**:

- `GEMINI_API_KEY`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

After each run the workflow commits any change to `last_processed.txt` back to the repo (via `git-auto-commit-action`), which is how the agent remembers what it already covered. The workflow therefore needs `contents: write` permission — already declared in the file.

## Files

| File | Purpose |
| --- | --- |
| `podcast_agent.py` | The entire agent: fetch, download, analyze, send. |
| `last_processed.txt` | Title of the last episode processed — the agent's memory. Committed by CI. |
| `.github/workflows/run_agent.yml` | Daily schedule and manual trigger. |
| `podcast_episodes/` | Temporary download folder (gitignored, emptied after each run). |

## Notes

- Gemini calls are retried up to 5 times with exponential backoff (30s, 60s, 120s, …) on `503`/`UNAVAILABLE`/`429` responses, since audio analysis often hits rate limits.
- Telegram sending is sent as HTML first; if Telegram rejects the formatting, the raw text is re-sent without `parse_mode` as a fallback.
- Only the single newest episode is checked per run, so if two episodes are published on the same day, the earlier one is skipped.
