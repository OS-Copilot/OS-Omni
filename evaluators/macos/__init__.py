"""macOS evaluator package."""

from .command_check import CommandCheckEvaluator
from .blender import BlenderSceneEvaluator
from .drawio import DrawIODiagramEvaluator
from .deltachat import DeltaChatMessageEvaluator
from .gimp import GimpFileEvaluator
from .libreoffice_calc_cells import LibreOfficeCalcCellEvaluator
from .libreoffice_impress import LibreOfficeImpressEvaluator
from .libreoffice_writer_formatting import LibreOfficeWriterFormattingEvaluator
from .libreoffice_writer_reformat import LibreOfficeWriterReformatEvaluator
from .libreoffice_writer_table import LibreOfficeWriterTableEvaluator
from .libreoffice_writer_title import LibreOfficeWriterTitleEvaluator
from .one_plus_one import OnePlusOneEvaluator
from .open_calculator import OpenCalculatorEvaluator
from .openshop import OpenShopMacOSApiEvaluator
from .spotube import SpotubeEvaluator
from .textedit import TextEditFileEvaluator
from .vscodium import VSCodiumSettingsEvaluator, VSCodiumWorkspaceEvaluator
from .wireshark import WiresharkArtifactEvaluator, WiresharkObservationEvaluator
from .zotero import ZoteroLibraryEvaluator

__all__ = [
    "CommandCheckEvaluator",
    "BlenderSceneEvaluator",
    "DrawIODiagramEvaluator",
    "DeltaChatMessageEvaluator",
    "GimpFileEvaluator",
    "LibreOfficeWriterFormattingEvaluator",
    "LibreOfficeWriterReformatEvaluator",
    "LibreOfficeCalcCellEvaluator",
    "LibreOfficeImpressEvaluator",
    "LibreOfficeWriterTableEvaluator",
    "LibreOfficeWriterTitleEvaluator",
    "OnePlusOneEvaluator",
    "OpenCalculatorEvaluator",
    "OpenShopMacOSApiEvaluator",
    "SpotubeEvaluator",
    "TextEditFileEvaluator",
    "VSCodiumSettingsEvaluator",
    "VSCodiumWorkspaceEvaluator",
    "WiresharkArtifactEvaluator",
    "WiresharkObservationEvaluator",
    "ZoteroLibraryEvaluator",
]
