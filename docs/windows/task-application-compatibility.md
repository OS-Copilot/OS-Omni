# Windows task and application compatibility

## OpenTrip multi-booking tasks

The four Windows multi-booking tasks require the OpenTrip inventory from
`killthefullmoon/OS-Omni-V2` commit
`044ab5a8e95597ffa7a4354c8736de43fa153c7e`:

| ID | Required inventory |
| --- | --- |
| f2008 | ES8139, PVG–CKG, 2026-06-01 |
| f1001 | ES6821, SHA–SYX, 2026-06-12 |
| h4887 | Chengdu Jade Pavilion Boutique Stay |
| h4879 | Beijing Jade Pavilion Boutique Stay |

Commit `626f1cfbf567929f8d26f086d371cb183143d184` changed flight generation
to daily files beginning 2026-06-12 and reassigned hotel identifiers. Copying
that newer application between Windows images does not restore the old task
inventory. The initializer checks dates, routes, flight numbers and hotel
names before allowing these tasks to run.

Build the complete matching historical application from a local source checkout:

```bash
python tools/windows/build_opentrip_task_baseline.py --source-repo <OS-Omni-V2-checkout> --output <baseline.zip>
```

On a checkpointed guest, with no benchmark running:

```powershell
powershell -ExecutionPolicy Bypass -File install_opentrip_task_baseline.ps1 -Archive <baseline.zip>
```

The installer validates the payload manifest and preserves the previous app.
Only the default server port is adapted, from 4312 to the tasks' port 4330.
Inventory, booking behavior and evaluation requirements are not rewritten.
Create a separate clean shutdown snapshot and explicitly select it in the
experiment VM configuration; resetting to the older snapshot undoes installation.

## OpenFood place_order_from_existing_restaurants

The generated English summary incorrectly requested one order containing items
from five restaurants. The preserved original 66-step workflow instead visits
and adds items from five restaurants sequentially, then orders from the final
restaurant. The application intentionally clears the cart on a restaurant
switch. The task now uses its original workflow, including the quantity and
coupon actions, and preserves it when regenerating tasks.

LevelDB is a current-state database with delayed/coalesced commits, not an
action log. Raw-file scanning can omit successful intermediate application
writes. This task's initializer starts a loopback CDP observer, then confirms
Lucas Lin is signed in and the cart and created orders are empty. The observer
records successful application writes to the OpenFood localStorage key in a
fresh run-bound JSONL file. It does not navigate, add items or create orders.
It remains attached across page reloads. The evaluator reads only the current
run's ordered observations and keeps the restaurant sequence and final order
conditions. Missing, stale or malformed evidence fails closed.

Treat runs using these repaired definitions and the pinned OpenTrip application
as a distinct benchmark configuration. Contract/API and scripted GUI smoke
checks are diagnostics, not new agent scores.

### DeltaChat snapshot profile preservation (2026-10-28)

The generic Windows cleanup runs after each snapshot restore. DeltaChat's
`%LOCALAPPDATA%\DeltaChat` and `%APPDATA%\DeltaChat` are seeded profile roots,
not disposable output: the local profile contains `accounts/*/dc.db`, account
configuration and blob attachments. Removing either root destroys the task's
starting state even when the snapshot itself is complete. Generic cleanup now
preserves both roots; snapshot restore remains responsible for removing previous
task mutations. The initializer and evaluator requirements remain unchanged.

Validation on the independent Windows VM checked SQLite integrity, all required
source messages and Documents attachments for Atlas, Harbor and Nova. All three
initializers passed after the real generic cleanup; all 51 profile files kept
identical hashes. A regression test runs the production cleanup path-list loop
against disposable Windows profiles and also verifies unrelated app state is
still removed.
