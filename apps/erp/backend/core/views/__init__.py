"""views package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .exchange_rates import CurrentRateView, ExchangeRateJournalView, ManualRateView
from .settings import SystemSettingSerializer, SystemSettingsView
from .stats import PageStatsView, PlatformDashboardView

__all__ = [
    "CurrentRateView",
    "ExchangeRateJournalView",
    "ManualRateView",
    "PageStatsView",
    "PlatformDashboardView",
    "SystemSettingSerializer",
    "SystemSettingsView",
]
