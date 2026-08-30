"""Windows initializers."""

from .deltachat import DeltaChatSendMessageInitializer
from .cross_app import OfficeThunderbirdInitializer, ShoppingCalendarInitializer
from .open_app import OpenAppInitializer
from .openshop import OpenShopInitializer
from .setup import DesktopSetupInitializer

__all__ = [
    "DeltaChatSendMessageInitializer",
    "OfficeThunderbirdInitializer",
    "OpenAppInitializer",
    "OpenShopInitializer",
    "ShoppingCalendarInitializer",
    "DesktopSetupInitializer",
]
