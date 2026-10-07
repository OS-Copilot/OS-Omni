# SEV2 Queue Lag Runbook

## Escalation
- Keep the incident at SEV3 during the draft watch.
- Post the current lag graph in the handoff thread.
- Page the backup on-call if queue lag stays above 20 minutes for two checks.

## Recovery
- Confirm the ingestion worker is healthy.
- Ask support to pause bulk imports if lag keeps rising.
