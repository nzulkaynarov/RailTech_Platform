"""Пакет вьюх сделки (распил deals.py по причинам изменения; AI — отдельным модулем)."""

from .ai import AiDraftThrottle  # noqa: F401
from .core import DealViewSet  # noqa: F401
from .stages import DealStageLookupSerializer, DealStageViewSet  # noqa: F401
