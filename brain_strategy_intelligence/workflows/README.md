# Optional n8n workflow

`n8n_scheduled_research.json` runs the read-only `bsi rank` command on a schedule. n8n is **not** a dependency of the bundle;
everything works from cron/Task Scheduler or by hand.

**Status: the JSON was written against n8n's documented node types but was NOT imported into a live n8n instance in the
build environment.** Treat it as a starting point and verify the import.

Setup: n8n -> Workflows -> Import from file -> select the JSON -> edit the command (working directory must be the bundle root, venv
activated, `--csv` pointing at real data) -> activate. The command only reads data and writes reports; it cannot place orders.
Windows Task Scheduler equivalent: run `scripts\run_tests.ps1`-style wrapper calling `.venv\Scripts\bsi.exe rank --csv ...`.
