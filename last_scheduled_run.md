# Scheduled Run Report — foreclosure-daily-update

**Date:** 2026-05-07
**Status:** ❌ FAILED — pipeline did not run (same mount error as 2026-05-05)

## What happened
The scheduled task tried to invoke `bash scripts/update.sh` via the Cowork
workspace bash sandbox. The sandbox could not start: every call returned the
same mount error, including a plain `echo hello`:

```
bash failed on resume, create, and re-resume. resume: RPC error: failed to
mount /mnt/.virtiofs-root/shared/Users/jarvis/Documents/Claude/Foreclosures
as Foreclosures: source path is not accessible: ... stat ...: operation not
permitted; create: RPC error: ensure user: user keen-admiring-volta already
exists unexpectedly: uid=1012 gid=1012
```

This is the same `bash workspace broken` issue documented in `CLAUDE.md` and
in the saved memory note `feedback_bash_broken.md`. The mount of the
Foreclosures folder fails before any command can execute, so neither the
scraper, the Sheets sync, nor the GitHub push happened.

## What did NOT happen today
- `scraper.py` did not run — `data/foreclosures.json` was not refreshed
- `sheets_sync.py` did not run — Google Sheet not updated
- `backfill.py` did not run — no enrichment passes
- No git commit / push — GitHub Pages dashboard still shows prior data

## What to do
Run the pipeline manually from your Mac terminal:

```bash
cd ~/Documents/Claude/Foreclosures
bash scripts/update.sh
```

Or, to test without pushing:

```bash
bash scripts/update.sh --no-push
```

## This has now failed twice in a row
The 2026-05-05 scheduled run hit the exact same error. The Cowork sandbox
has not recovered between runs, so the schedule is effectively a no-op
right now. Until this is resolved, the daily update has to be run by hand.

## Longer-term fix
Two options worth considering:

1. **Move the schedule off Cowork.** A `launchd` plist or a `cron` entry on
   the Mac itself would run `update.sh` daily without depending on the
   Cowork sandbox at all. This is the most reliable path.
2. **Re-grant Cowork access to the folder.** If macOS Full Disk Access for
   Cowork was revoked, or the folder was moved/renamed, re-selecting it
   inside Cowork may restore the mount. Worth a single try.

Ask me next session and I can draft the launchd plist.
