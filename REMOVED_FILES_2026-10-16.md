# Removed on 16 October 2026 (disk cleanup)

These folders were removed to free disk space, with your confirmation. **Your
own code, documents and data were not touched.** Everything removed here can be
rebuilt.

| Removed | Size | What it was |
|---|---|---|
| `.venv/` | 489 MB | Python environment |

## Only reinstall if you need this again

- Rebuild only when you work on this project again; until then nothing is
  missing that you use.
- Every step below **downloads from the internet**, and some downloads are
  large.
- Before running a step, ask Claude. It will tell you what will be downloaded
  and how big it is, and **wait for your yes**.

**The Python environment (`.venv/`):**

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

For the background worker, also install `requirements-worker.txt` the same way.

