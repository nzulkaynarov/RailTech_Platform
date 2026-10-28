import pytest
from inventory.tests.support import make_world


@pytest.fixture
def world(db):
    return make_world()
