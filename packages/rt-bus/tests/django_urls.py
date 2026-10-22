from __future__ import annotations

from django.urls import path

from rt_bus.django.views import bus_view
from tests.django_support import bus_for_view, win_deal

urlpatterns = [
    path("bus/v1/events", bus_view(bus_for_view)),
    path("deals/905/win", win_deal),
]
