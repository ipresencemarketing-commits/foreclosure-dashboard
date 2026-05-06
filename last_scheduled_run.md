# Scheduled Run Report — foreclosure-daily-update

**Date:** 2026-05-05
**Status:** ❌ FAILED — pipeline did not run

## What happened
The scheduled task tried to invoke `bash scripts/update.sh` via the Cowork
workspace bash sandbox. The sandbox could not start: every call returned a
mount error.

```
bash failed on resume, create, and re-resume. resume: RPC error: failed to
mount /mnt/.virtiofs-root/shared/Users/jarvis/Documents/Claude/Foreclosures
as Foreclosures: source path is not accessible: ... stat ...: operation not
permitted; create: RPC error: ensure user: user vibrant-epic-carson already
exists unexpectedly: uid=1010 gid=1010
```

This is the same `bash workspace broken` issue documented in `CLAUDE.md` and
in the saved memory note `feedback_bash_broken.md`. The mount of the
Foreclosures folder fails before any command can execute, so neither the
scraper, the Sheets sync, nor the GitHub push happened.

## What did NOT happen today
- `scraper.py` did not run — `data/foreclosures.json` was not refreshed
- `sheets_sync.py` did not run — Google Sheet not updated
- No git commit / push — GitHub Pages dashboard shows yesterday's data

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

## Longer-term fix
The Cowork-side bash sandbox keeps failing to mount this folder for
scheduled runs. Two options worth considering:

1. **Move the schedule off Cowork.** A `launchd` plist or a `cron` entry on
   the Mac itself would run `update.sh` daily without depending on the
   Cowork sandbox at all.
2. **Re-grant Cowork access to the folder.** If the folder permissions
   changed (e.g. macOS Full Disk Access was reset, or the folder was moved),
   re-selecting it inside Cowork may restore the mount. Worth trying once
   before going the launchd route.

If you want, I can draft the launchd plist next session.
