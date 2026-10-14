"""views package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .settings import SystemSettingSerializer, SystemSettingsView
from .stats import PageStatsView, PlatformDashboardView

__all__ = [
    "PageStatsView",
    "PlatformDashboardView",
    "SystemSettingSerializer",
    "SystemSettingsView",
]
