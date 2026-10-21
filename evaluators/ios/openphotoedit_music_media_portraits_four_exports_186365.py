"""Revision 2: export the preloaded Shade sample unchanged."""

from evaluators.ios.openphotoedit_export_support import OpenPhotoEditNamedExportEvaluator


class OpenPhotoEditMusicMediaPortraitsFourExports186365Evaluator(
    OpenPhotoEditNamedExportEvaluator
):
    TASK_ID = "ios.openphotoedit.music_media_portraits_four_exports_186365"
    SOURCE_SAMPLE = "Shade"
    EXPORT_FILENAME = "music media portrait.png"
    SOURCE_SHA256 = "c0beb879923fd7da7ca384747d7fc65f3e8e05208003ffb76a637d614416e60b"
