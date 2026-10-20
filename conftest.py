from dotenv import load_dotenv

# Loaded once, before any test module's env var reads run. load_dotenv()
# with no path argument searches upward from *this file's own location*
# (confirmed by hand — not from CWD, which pytest can run from anywhere),
# so a repo-root .env is found reliably regardless of where `pytest` was
# invoked from. Values already set in the real environment are not
# overridden (override=False, the default) — a CI secret or a value you
# already exported takes priority over whatever .env says.
load_dotenv()
