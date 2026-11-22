"""Тесты BFF для шага подписи исходящего документа (SIGN-3, ADR-0024)."""

from typing import Any

import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_documents_support import DOC_ID, ME, EdsFake, document, registry_item
from tests.test_eds_letterhead import letter, letter_doc

BASE = "/api/v1/eds"


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


async def test_sign_eds_document_proxies_to_eds_and_matches_contract(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    signed_doc = document(
        kind="letter_out",
        status="sent",
        number="ИСХ-042/26",
    )
    signed_doc["signed_at"] = "2026-11-05T14:30:00Z"
    signed_doc["signed_by"] = {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    signed_doc["signatory_basis"] = "charter"
    signed_doc["signatory_basis_text"] = None
    signed_doc["verification_code"] = "V7K9Q2P4M1"
    signed_doc["verification_url"] = "https://cabinet.railtech.uz/v/V7K9Q2P4M1"
    signed_doc["dispatch_method"] = "paper"

    eds.answer("POST", f"documents/{DOC_ID}/sign", 200, signed_doc)

    response = await web.client.post(
        f"{BASE}/documents/{DOC_ID}/sign",
        json={"dispatch_method": "paper", "send": False},
        headers={CSRF_HEADER: web.csrf},
    )

    assert response.status_code == 200, response.text
    check(response, "/eds/documents/{id}/sign", "post")
    data = response.json()
    assert data["number"] == "ИСХ-042/26"
    assert data["status"] == "sent"
    assert data["verification_code"] == "V7K9Q2P4M1"
    assert data["verification_url"] == "https://cabinet.railtech.uz/v/V7K9Q2P4M1"
    assert data["dispatch_method"] == "paper"


SIGNER = {"crm_user_id": 3, "full_name": "Рустам Директоров"}


@pytest.mark.parametrize(
    ("signing", "can_sign", "hint"),
    [
        (None, False, None),  # EDS без поля — подпись не предлагается
        (
            {"can_sign": True, "reason": None, "signer": None},
            True,
            {"reason": None, "signer": None, "signer_position": None, "signer_is_you": False},
        ),
        (
            {"can_sign": False, "reason": "no_authority", "signer": None},
            False,
            {
                "reason": "no_authority",
                "signer": None,
                "signer_position": None,
                "signer_is_you": False,
            },
        ),
        (
            {"can_sign": False, "reason": "author_cannot_sign", "signer": SIGNER},
            False,
            {
                "reason": "author_cannot_sign",
                "signer": SIGNER,
                "signer_position": None,
                "signer_is_you": False,
            },
        ),
    ],
)
async def test_letter_sign_offer_follows_eds_signing_check(
    web: Web,
    eds: EdsFake,
    check: ContractChecker,
    signing: dict[str, Any] | None,
    can_sign: bool,
    hint: dict[str, Any] | None,
) -> None:
    """СЦ-9: «Подписать» — только если EDS разрешает; причину и подписанта даёт подсказка."""
    await web.login(["DIRECTOR"])
    over: dict[str, Any] = {} if signing is None else {"signing": signing}
    eds.answer("GET", f"documents/{DOC_ID}", body=document(kind="letter_out", **over))

    response = await web.client.get(f"{BASE}/documents/{DOC_ID}")

    assert response.status_code == 200, response.text
    check(response, "/eds/documents/{id}", "get")
    body = response.json()
    assert body["can_sign"] is can_sign
    assert body["signing_hint"] == hint


# --- ГЛ-0: письмо «На подписи» без тупика --------------------------------------------------

HANDED = {"by": ME, "at": "2026-10-27T09:00:00Z"}


def on_signing(signing: dict[str, Any] | None, **over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "author": ME,
        "awaiting_signature": True,
        "letter": letter(registration_requested=HANDED),
        **({} if signing is None else {"signing": signing}),
        **over,
    }
    return letter_doc(**fields)


async def test_card_of_a_handed_over_letter_names_the_signer_and_gives_the_author_the_actions(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    """Автор видит, у кого письмо (имя, должность), и действия над передачей; чужой — нет."""
    signing = {"can_sign": True, "reason": None, "signer": SIGNER, "signer_position": "Директор"}
    eds.answer("GET", f"documents/{DOC_ID}", 200, on_signing(signing))
    await web.login(["MANAGER"])
    mine = await web.client.get(f"{BASE}/documents/{DOC_ID}")
    check(mine, "/eds/documents/{id}", "get")
    body = mine.json()
    assert body["can_sign"] is True
    assert body["can_manage_handover"] is True
    assert body["signing_hint"] == {
        "reason": None,
        "signer": SIGNER,
        "signer_position": "Директор",
        "signer_is_you": False,
    }

    eds.answer("GET", f"documents/{DOC_ID}", 200, on_signing(signing, author=SIGNER))
    stranger = (await web.client.get(f"{BASE}/documents/{DOC_ID}")).json()
    assert stranger["can_manage_handover"] is False


async def test_author_who_signs_himself_is_told_so(web: Web, eds: EdsFake) -> None:
    me = {"can_sign": True, "reason": None, "signer": ME, "signer_position": None}
    eds.answer("GET", f"documents/{DOC_ID}", 200, on_signing(me))
    await web.login(["MANAGER"])
    hint = (await web.client.get(f"{BASE}/documents/{DOC_ID}")).json()["signing_hint"]
    assert hint["signer_is_you"] is True


async def test_no_handover_actions_before_the_letter_is_handed_over_or_after_signing(
    web: Web, eds: EdsFake
) -> None:
    await web.login(["MANAGER"])
    eds.answer("GET", f"documents/{DOC_ID}", 200, letter_doc(author=ME))
    assert (await web.client.get(f"{BASE}/documents/{DOC_ID}")).json()[
        "can_manage_handover"
    ] is False
    signed = on_signing(None, status="sent", awaiting_signature=False)
    eds.answer("GET", f"documents/{DOC_ID}", 200, signed)
    assert (await web.client.get(f"{BASE}/documents/{DOC_ID}")).json()[
        "can_manage_handover"
    ] is False


async def test_remind_withdraw_and_change_signer_go_to_eds(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    card = on_signing(
        {"can_sign": False, "reason": None, "signer": SIGNER, "signer_position": None}
    )
    eds.answer("POST", f"documents/{DOC_ID}/remind", 200, card)
    reminded = await web.send("POST", f"{BASE}/documents/{DOC_ID}/remind")
    assert reminded.status_code == 200, reminded.text
    check(reminded, "/eds/documents/{id}/remind", "post")

    eds.answer("POST", f"documents/{DOC_ID}/withdraw", 200, letter_doc(author=ME))
    withdrawn = await web.send("POST", f"{BASE}/documents/{DOC_ID}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    check(withdrawn, "/eds/documents/{id}/withdraw", "post")
    assert withdrawn.json()["can_manage_handover"] is False

    eds.answer("POST", f"documents/{DOC_ID}/signer", 200, card)
    changed = await web.send(
        "POST", f"{BASE}/documents/{DOC_ID}/signer", json={"signer_crm_user_id": 3}
    )
    assert changed.status_code == 200, changed.text
    check(changed, "/eds/documents/{id}/signer", "post")
    assert eds.body("POST", f"documents/{DOC_ID}/signer") == {"signer_crm_user_id": 3}


async def test_remind_too_soon_reaches_the_screen_with_its_reason(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    eds.error(
        "POST",
        f"documents/{DOC_ID}/remind",
        409,
        "CONFLICT",
        "Напоминание уже отправлено. Повторить можно через час.",
        {"reason": "remind_too_soon", "retry_at": "2026-10-27T10:00:00+00:00"},
    )
    refused = await web.send("POST", f"{BASE}/documents/{DOC_ID}/remind")
    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "remind_too_soon"


async def test_registry_row_carries_the_signer_of_a_letter_on_signing(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    row = registry_item(
        kind="letter_out", awaiting_signature=True, status="draft", signer=SIGNER, number=None
    )
    eds.answer("GET", "registry", 200, {"items": [row], "next_cursor": None})
    page = await web.client.get(f"{BASE}/documents?scope=all")
    assert page.status_code == 200, page.text
    check(page, "/eds/documents", "get")
    assert page.json()["items"][0]["signer"] == SIGNER
