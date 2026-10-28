"""B-006: поля `extra` журнала шины доходят до JSON-журнала EDS (причина, код ответа, подписчик)."""

import json
import logging

import pytest

from app.config import Settings
from app.log import configure_logging


def test_bus_extra_fields_reach_the_json_log(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings.model_construct(log_format="json", log_level="INFO")
    configure_logging(settings)
    logging.getLogger("rt_bus").error(
        "rt_bus_delivery_dead",
        extra={"subscriber": "crm", "event_id": "e-9", "attempt": 5, "status_code": 410},
    )
    logging.getLogger("rt_bus.receiver").warning(
        "rt_bus_receive_rejected", extra={"status_code": 422, "reason": "unknown type"}
    )
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    dead, rejected = lines[-2], lines[-1]
    assert (dead["subscriber"], dead["event_id"], dead["attempt"]) == ("crm", "e-9", 5)
    assert dead["status_code"] == 410
    assert (rejected["status_code"], rejected["reason"]) == (422, "unknown type")
