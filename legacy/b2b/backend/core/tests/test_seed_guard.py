"""SEC-03: core_seed creates DEMO login accounts with a known password, so it must refuse
to run against a non-DEBUG (prod-like) environment unless explicitly forced."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_core_seed_refuses_when_debug_false(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="Refusing to run with DEBUG=False"):
        call_command("core_seed")
