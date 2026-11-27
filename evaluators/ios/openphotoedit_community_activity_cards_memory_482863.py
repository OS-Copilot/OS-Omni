"""Revision 2: export the preloaded Window sample unchanged."""

from evaluators.ios.openphotoedit_export_support import (
    OpenPhotoEditNamedExportEvaluator,
    validate_named_export,
)


TASK_ID = "ios.openphotoedit.community_activity_cards_memory_482863"
EXPORT_FILENAME = "community activity main cover.png"
SOURCE_SAMPLE = "Window"
EXPECTED_SOURCE_SHA256 = "8cfbd4717868d17193f29e209a524e83cc82d75fec266b1b42418fee3c025536"


def validate_export_files(files):
    return validate_named_export(
        files,
        expected_filename=EXPORT_FILENAME,
        expected_sha256=EXPECTED_SOURCE_SHA256,
    )


class OpenPhotoEditCommunityActivityCardsMemory482863Evaluator(
    OpenPhotoEditNamedExportEvaluator
):
    TASK_ID = TASK_ID
    SOURCE_SAMPLE = SOURCE_SAMPLE
    EXPORT_FILENAME = EXPORT_FILENAME
    SOURCE_SHA256 = EXPECTED_SOURCE_SHA256
