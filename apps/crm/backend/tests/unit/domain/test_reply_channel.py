import pytest

from app.domain.reply_channel import ReplyFacts, ReplyVia, reply_via


def facts(**kw: object) -> ReplyFacts:
    base: dict[str, object] = {
        "has_telegram": False,
        "has_cabinet": False,
        "has_consent": False,
        "email": None,
        "has_phone": False,
        "source": "web",
        "last_inbound": None,
    }
    return ReplyFacts(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        # Telegram with consent
        (
            {"has_telegram": True, "has_consent": True, "last_inbound": "telegram"},
            ReplyVia("telegram"),
        ),
        # Telegram without consent: blocked, not a silent fall-through
        ({"has_telegram": True, "last_inbound": "telegram"}, ReplyVia(None, "no_consent")),
        # Telegram conversation closed (no chat), nothing else
        ({"has_consent": True, "last_inbound": "telegram"}, ReplyVia(None, "no_contact")),
        # Cabinet needs no consent
        (
            {"has_cabinet": True, "source": "cabinet", "last_inbound": "cabinet"},
            ReplyVia("cabinet"),
        ),
        # Last inbound is cabinet while Telegram is alive: the last channel wins
        (
            {
                "has_telegram": True,
                "has_cabinet": True,
                "has_consent": True,
                "last_inbound": "cabinet",
            },
            ReplyVia("cabinet"),
        ),
        # Last inbound telegram, but both alive: telegram
        (
            {
                "has_telegram": True,
                "has_cabinet": True,
                "has_consent": True,
                "last_inbound": "telegram",
            },
            ReplyVia("telegram"),
        ),
        # Last inbound channel is gone: any other available one
        ({"has_cabinet": True, "last_inbound": "telegram"}, ReplyVia("cabinet")),
        # Web lead with e-mail: letter, no consent needed
        ({"email": "a@b.uz", "source": "web", "has_phone": True}, ReplyVia("email")),
        # Manual lead with e-mail and no consent: the reason is the missing consent
        (
            {"email": "a@b.uz", "source": "referral", "has_phone": True},
            ReplyVia(None, "no_email_consent"),
        ),
        # Source «email» chosen by a manager is not «the client wrote first»
        ({"email": "a@b.uz", "source": "email"}, ReplyVia(None, "no_email_consent")),
        ({"email": "a@b.uz", "source": "email", "inbound_mail": True}, ReplyVia("email")),
        # Undeliverable address: blocked even for a web lead
        (
            {"email": "a@b.uz", "source": "web", "email_blocked": True},
            ReplyVia(None, "email_undeliverable"),
        ),
        # Manual lead with e-mail and consent: letter
        ({"email": "a@b.uz", "source": "phone", "has_consent": True}, ReplyVia("email")),
        # Web lead with phone only
        ({"has_phone": True, "source": "web"}, ReplyVia(None, "phone_only")),
        # Manual referral without contacts
        ({"source": "referral"}, ReplyVia(None, "no_contact")),
        # Blank e-mail is no e-mail
        ({"email": "  ", "source": "web"}, ReplyVia(None, "no_contact")),
    ],
)
def test_reply_via(kw: dict[str, object], expected: ReplyVia) -> None:
    assert reply_via(facts(**kw)) == expected
