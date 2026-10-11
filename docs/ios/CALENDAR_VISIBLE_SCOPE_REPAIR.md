# Calendar visible-state repair for iOS 26.5

The two closed-world Calendar tasks promise an exact number of events. On the
shipped iOS 26.5 simulator, opening Calendar recreated the built-in
`Subscribed Calendars` store and synchronized 123 OS holiday entries after
initialization. The store database flag was reset by this first-launch sync;
disabling the HolidayCalendar account alone did not prevent the entries from
being regenerated. Treating every row in `Calendar.sqlitedb` as a user-visible
event therefore made these tasks nondeterministic.

The repair keeps the task intent on the visible Calendar surface:

* The initializer purges and seeds as before, opens Calendar, waits for its
  first-launch sync, then disables the OS-provided `Subscribed Calendars`
  store again. It records the store IDs changed after activation.
* The Calendar store API has an opt-in `visible_calendars_only` query that joins
  events through Calendar and Store and excludes rows belonging to a disabled
  calendar. The two exact-count tasks opt into that query for both required
  and absent events. Other Calendar tasks retain the old all-row behavior.
* Preflight checks the actual visible native seed count before it accepts the
  initial evaluator FAIL. A correct task state must still be visible; hiding a
  required event does not pass.

This is an evaluation-scope revision for iOS 26.5 and is not comparable to the
unmodified all-database evaluator score. It does not accept arbitrary extras:
an extra event in an enabled calendar fails the exact count; a missing or
hidden required event fails; stale task summaries still fail. Independent
positive and negative references are run by
`scripts/author_calendar_reference_check.py` on a disposable simulator.

## Reproduction

```sh
uv run python scripts/author_ios_preflight.py \
  --task-id ios.calendar.finalize_schedule_with_two_followups \
  --udid "$IOS_AUDIT_UDID" --output "$PREFLIGHT_DIR" \
  --wda-derived-data "$WDA_DERIVED_DATA"
uv run python scripts/author_calendar_reference_check.py \
  --task finalize --udid "$IOS_AUDIT_UDID" --output "$REFERENCE_DIR"
```

Run one simulator at a time. Keep formal model runs separate from this
initializer/reference audit.
