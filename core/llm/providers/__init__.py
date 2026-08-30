"""Provider adapters for the shared LLM client."""

from .base import OpenAICompatibleAdapter, ProviderAdapter, ProviderRequest, ProviderResult

__all__ = [
    "OpenAICompatibleAdapter",
    "ProviderAdapter",
    "ProviderRequest",
    "ProviderResult",
]

try:  # pragma: no cover - import depends on optional runtime deps
    from .google_adapter import GoogleAdapter

    __all__.append("GoogleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    GoogleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .intern_adapter import InternAdapter

    __all__.append("InternAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    InternAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .openai_adapter import OpenAIAdapter

    __all__.append("OpenAIAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    OpenAIAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .taobao_adapter import TaobaoAdapter

    __all__.append("TaobaoAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    TaobaoAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .deepseek_adapter import DeepSeekAdapter

    __all__.append("DeepSeekAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    DeepSeekAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .together_adapter import TogetherAdapter

    __all__.append("TogetherAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    TogetherAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .mock_adapter import MockAdapter

    __all__.append("MockAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    MockAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .scripted_adapter import ScriptedAdapter

    __all__.append("ScriptedAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    ScriptedAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .android_oracle_adapter import AndroidOracleAdapter

    __all__.append("AndroidOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    AndroidOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .linux_gui_oracle_adapter import LinuxGuiOracleAdapter

    __all__.append("LinuxGuiOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    LinuxGuiOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .linux_wireshark_oracle_adapter import LinuxWiresharkOracleAdapter

    __all__.append("LinuxWiresharkOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    LinuxWiresharkOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .openshop_oracle_adapter import OpenShopOracleAdapter

    __all__.append("OpenShopOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    OpenShopOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .deltachat_oracle_adapter import DeltaChatOracleAdapter

    __all__.append("DeltaChatOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    DeltaChatOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .gimp_oracle_adapter import GimpOracleAdapter

    __all__.append("GimpOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    GimpOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .zotero_oracle_adapter import ZoteroOracleAdapter

    __all__.append("ZoteroOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    ZoteroOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .wireshark_oracle_adapter import WiresharkOracleAdapter

    __all__.append("WiresharkOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    WiresharkOracleAdapter = None  # type: ignore[assignment]


try:  # pragma: no cover - import depends on optional runtime deps
    from .macos_blender_oracle_adapter import MacOSBlenderOracleAdapter

    __all__.append("MacOSBlenderOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    MacOSBlenderOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .macos_openshop_oracle_adapter import MacOSOpenShopOracleAdapter

    __all__.append("MacOSOpenShopOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    MacOSOpenShopOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .macos_spotube_oracle_adapter import MacOSSpotubeOracleAdapter

    __all__.append("MacOSSpotubeOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    MacOSSpotubeOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .macos_script_oracle_adapter import MacOSScriptOracleAdapter

    __all__.append("MacOSScriptOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    MacOSScriptOracleAdapter = None  # type: ignore[assignment]

try:  # pragma: no cover - import depends on optional runtime deps
    from .windows_oracle_adapter import WindowsOracleAdapter

    __all__.append("WindowsOracleAdapter")
except Exception:  # pragma: no cover - optional until runtime deps are installed
    WindowsOracleAdapter = None  # type: ignore[assignment]
