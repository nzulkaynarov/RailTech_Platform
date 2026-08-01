"""Пакет вьюх сделки (распил deals.py 783 строки по причинам изменения)."""

from .core import DealViewSet  # noqa: F401
from .stages import DealStageLookupSerializer, DealStageViewSet  # noqa: F401
from .workflow import AiDraftThrottle  # noqa: F401
