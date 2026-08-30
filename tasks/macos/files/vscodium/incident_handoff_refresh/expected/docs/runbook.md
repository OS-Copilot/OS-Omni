# SEV2 Queue Lag Runbook

## Escalation
- Keep the incident at SEV2 during the overnight watch.
- Post the current lag graph in the handoff thread.
- Page the backup on-call if queue lag stays above 12 minutes for two checks.
- Escalate immediately if bridge lag reaches 20 minutes.

## Recovery
- Confirm the ingestion worker is healthy.
- Ask support to pause bulk imports if lag keeps rising.
- Reassign the handoff owner to Night Watch after paging.
