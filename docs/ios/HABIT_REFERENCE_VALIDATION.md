# Habit reference validation

Both Habit tasks retain their authored business requirements. Static review by Muse found instruction/evaluator agreement, including the preserved Water Plants fields and exact habit counts. An independent offline database copy produced initial FAIL, correct completion PASS, and FAIL for each wrong color, extra habit, and changed preserved motivation.

The portable helper `scripts/author_habit_reference_check.py` was implemented with Muse and reviewed by the benchmark operator. It reads current `tasks/v1/ios` definitions, uses manually authored correct reference records, and backs up an offline source SQLite database through the read-only SQLite API so committed WAL state is included. All mutations affect its temporary copy. Both CLI modes were executed, and the input database SHA256 was unchanged after all checks.

Run with `--db-path <offline-Habit.sqlite> --task manage` or `--task rework`, and `--output <new-directory>`. Do not supply a live database or a formal simulator state. The JSON records include source/task hashes and check details. Separate real simulator initializer and UI checks are required before formal testing; the native references do not substitute for GUI checks.
