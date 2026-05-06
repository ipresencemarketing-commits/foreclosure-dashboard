# Scheduled Run Status

**Run date:** 2026-05-06
**Status:** FAILED — bash sandbox unavailable

## What happened
The scheduled `foreclosure-daily-update` task tried to execute `bash scripts/update.sh`
via the Cowork workspace bash tool, but the workspace failed to start with a mount error:

```
RPC error: failed to mount /mnt/.virtiofs-root/shared/Users/jarvis/Documents/Claude/Foreclosures
as Foreclosures: source path is not accessible:
stat /mnt/.virtiofs-root/shared/Users/jarvis/Documents/Claude/Foreclosures:
operation not permitted
```

This is the same persistent issue noted in `CLAUDE.md` ("Bash sandbox is broken")
and in your memory (`feedback_bash_broken.md`). Every bash invocation in this
session — including a no-op `echo "test"` — returned the same mount error, so
no part of the pipeline (scrape, sync, backfill, publish) ran.

## Current data state
- `data/foreclosures.json` `meta.last_updated`: **2026-05-04T20:42:45**
- Data is ~2 days stale as of this run.

## To recover, run manually in Terminal
```bash
cd ~/Documents/Claude/Foreclosures
bash scripts/update.sh
```

That will run scrape → sheets sync → backfill → sheets sync → git push.
If something errors out mid-pipeline, the per-step `[warn]` messages in the
script output will show which step failed.

## Why the scheduled task can't run autonomously today
Scheduled Cowork tasks rely on the workspace bash sandbox to invoke local
Python scripts. Until the sandbox can mount this folder reliably, this
scheduled task will keep failing the same way. Options:
1. Run `update.sh` manually (works fine — the sandbox is the only blocker).
2. Move the schedule to a local cron job on your Mac (`crontab -e`) so it
   runs in your real shell instead of the Cowork sandbox.
