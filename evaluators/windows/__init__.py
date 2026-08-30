"""Windows evaluators."""

from .deltachat_create_group_from_existing_chats import DeltaChatCreateGroupFromExistingChatsEvaluator
from .deltachat_share_sync_screenshot import DeltaChatShareSyncScreenshotEvaluator
from .deltachat_send_message import DeltaChatSendMessageEvaluator
from .cross_app import CrossAppEvaluator
from .openshop import OpenShopApiEvaluator
from .screenshot_check import ScreenshotCheckEvaluator

__all__ = [
    "CrossAppEvaluator",
    "DeltaChatCreateGroupFromExistingChatsEvaluator",
    "DeltaChatShareSyncScreenshotEvaluator",
    "DeltaChatSendMessageEvaluator",
    "OpenShopApiEvaluator",
    "ScreenshotCheckEvaluator",
]
