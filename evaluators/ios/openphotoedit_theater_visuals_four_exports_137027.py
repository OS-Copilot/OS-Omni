"""Revision 2: export the preloaded Light sample unchanged."""

from evaluators.ios.openphotoedit_export_support import OpenPhotoEditNamedExportEvaluator


class OpenPhotoEditTheaterVisualsFourExports137027Evaluator(
    OpenPhotoEditNamedExportEvaluator
):
    TASK_ID = "ios.openphotoedit.theater_visuals_four_exports_137027"
    SOURCE_SAMPLE = "Light"
    EXPORT_FILENAME = "theater visuals portrait.png"
    SOURCE_SHA256 = "cb9d820b07274a84e825dbea271244683453a6cc78bf0dca92585bc4acdc7087"
