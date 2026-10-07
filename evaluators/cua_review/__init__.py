"""Support code vendored from the CUA-Tasks-Review ``benchmark/`` release.

The reviewed task evaluators import shared family bases, state readers and a
richer evaluator base under the release's own top-level names (``core``,
``evaluators``, ``platforms``, ``collectors``, ``runtime``, ``initializers``).
Several of those names collide with different OS-Omni modules, so
``tools/import_cua_tasks_review.py`` mirrors the release layout below this
package and rewrites the imports onto it.  Only ``core/evaluation.py`` and this
file are maintained by hand; everything else is generated.
"""
