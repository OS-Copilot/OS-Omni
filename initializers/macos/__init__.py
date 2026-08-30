"""macOS initializer package."""

from .blender import BlenderInitializer
from .deltachat import DeltaChatInitializer, DeltaChatOracleInitializer
from .gimp import GimpInitializer
from .open_app import OpenAppInitializer
from .openshop import OpenShopInitializer
from .reset_calculator import ResetCalculatorInitializer
from .setup import DesktopSetupInitializer
from .spotube import SpotubeInitializer
from .vscodium import VSCodiumInitializer

__all__ = [
    "BlenderInitializer",
    "DeltaChatInitializer",
    "DeltaChatOracleInitializer",
    "DesktopSetupInitializer",
    "GimpInitializer",
    "OpenAppInitializer",
    "OpenShopInitializer",
    "ResetCalculatorInitializer",
    "SpotubeInitializer",
    "VSCodiumInitializer",
]
