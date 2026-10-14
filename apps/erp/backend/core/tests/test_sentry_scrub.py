"""SEC-tail: the Sentry before_send hook masks domain PII we put into events.

send_default_pii=False only stops Sentry's own auto-PII; ИНН/phone/bank data we
echo into request.data / extra / breadcrumbs would still ship. scrub_event masks it.
"""

from core.sentry_scrub import MASK, scrub_event


def test_scrubs_sensitive_keys_in_request_data():
    event = {
        "request": {
            "data": {
                "inn": "1234567890",
                "phone": "+998901234567",
                "bank_account": "20208000000000000001",
                "company_name": "Acme LLC",
            }
        }
    }
    scrubbed = scrub_event(event)
    data = scrubbed["request"]["data"]
    assert data["inn"] == MASK
    assert data["phone"] == MASK
    assert data["bank_account"] == MASK
    # Non-sensitive key with non-PII value is untouched.
    assert data["company_name"] == "Acme LLC"


def test_scrubs_inn_and_phone_in_free_text_values():
    event = {
        "request": {
            "data": {
                # Neutral key names → value-level regex must catch the PII inside.
                "note": "Клиент ИНН 305412345 просит счёт",
                "comment": "звонить на +998 90 123 45 67 после обеда",
                "individual_inn": "123456789012",
            }
        }
    }
    scrubbed = scrub_event(event)
    data = scrubbed["request"]["data"]
    assert "305412345" not in data["note"] and MASK in data["note"]
    assert "123 45 67" not in data["comment"] and MASK in data["comment"]
    # individual_inn key also matches the "inn" token → wholesale mask.
    assert data["individual_inn"] == MASK


def test_scrubs_extra_and_breadcrumbs():
    event = {
        "extra": {"passport": "AB1234567", "payload": {"iban": "UZ00 0000"}},
        "breadcrumbs": {
            "values": [
                {"category": "query", "data": {"phone": "+998901112233", "safe": "ok"}},
                {"category": "log", "message": "no data key here"},
            ]
        },
    }
    scrubbed = scrub_event(event)
    assert scrubbed["extra"]["passport"] == MASK
    assert scrubbed["extra"]["payload"]["iban"] == MASK
    crumb_data = scrubbed["breadcrumbs"]["values"][0]["data"]
    assert crumb_data["phone"] == MASK
    assert crumb_data["safe"] == "ok"


def test_breadcrumbs_as_bare_list():
    event = {"breadcrumbs": [{"data": {"card": "4111111111111111"}}]}
    scrubbed = scrub_event(event)
    assert scrubbed["breadcrumbs"][0]["data"]["card"] == MASK


def test_clean_event_passes_through_unchanged():
    event = {
        "request": {"data": {"query": "railway rails", "count": 5}},
        "extra": {"deal_id": 42},
        "message": "Something broke on order 7",
    }
    scrubbed = scrub_event(event)
    assert scrubbed["request"]["data"] == {"query": "railway rails", "count": 5}
    assert scrubbed["extra"] == {"deal_id": 42}
    # The exception message/stacktrace is intentionally NOT scrubbed (debuggability).
    assert scrubbed["message"] == "Something broke on order 7"


def test_never_returns_none_and_is_total_on_bad_input():
    # Malformed event must not raise nor drop the report (would be data loss).
    assert scrub_event({}) == {}
    weird = {"request": "not-a-dict", "extra": None}
    assert scrub_event(weird) is weird
