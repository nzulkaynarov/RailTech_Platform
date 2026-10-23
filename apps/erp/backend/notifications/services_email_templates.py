"""Business logic for the Platform-Operator email-template editor.

Keeps the DRF viewset thin (CONVENTIONS.md Rule 8): the viewset authorizes + validates
and calls exactly one of these functions. Two operations beyond plain CRUD:

  * `preview_template`  — render a key's subject/html/text against a SAMPLE
                          context, WITHOUT sending. Lets the editor see the
                          result of merge-variable interpolation.
  * `test_send_template` — render via the real `send_templated_email` pipeline
                          (DB row preferred, file fallback) and deliver to one
                          address, so the operator can confirm copy + transport.

The sample contexts mirror the real merge variables each calling service passes
(grep send_templated_email). They are illustrative ONLY — never persisted, never
sent to real users.
"""

from __future__ import annotations

from .emails import _render_bodies, send_templated_email

# Sample merge contexts per template key — what the editor sees in a preview.
# Mirrors the context dicts the production services build (accounts/services/*,
# crm/tasks.py). Values are obviously-fake placeholders.
SAMPLE_CONTEXTS: dict[str, dict] = {
    "setup_password": {
        "first_name": "Алиса",
        "setup_url": "https://erp.example.com/setup-password?uid=NDA&token=sample-token",
    },
    "invite_member": {
        "first_name": "Алиса",
        "company_name": "ООО «Пример»",
        "setup_url": "https://erp.example.com/setup-password?uid=NDA&token=sample-token",
    },
    "quote_sent": {
        # Mirrors the REAL merge variables passed by crm.tasks.send_quote_email — an operator
        # editing this template by the preview must see the same names the live send substitutes.
        "recipient_name": "Алиса",
        "seller_name": "ООО «Поставщик»",
        "deal_id": 1024,
        "quote_version": 1,
        "valid_until": "08.08.2026",
        "total_incl_vat": "20 608 000,00",
        "public_link": "https://erp.example.com/api/v1/public/quotes/sample-token/",
    },
    "reset_password": {
        "first_name": "Алиса",
        "reset_url": "https://erp.example.com/reset-password?uid=NDA&token=sample-token",
    },
    "portal_invitation": {
        "contact_name": "Алиса",
        "company_name": "ООО «Покупатель»",
        "invite_url": "https://cabinet.example.com/auth/magic/sample-token",
        "telegram_url": "https://t.me/sample_bot",
    },
    "portal_magic_link": {
        "contact_name": "Алиса",
        "company_name": "ООО «Покупатель»",
        "login_url": "https://cabinet.example.com/auth/magic/sample-token",
    },
}

# Fallback context for keys we don't have a curated sample for (e.g. a brand-new
# custom key the operator created). Common variables most templates reference.
_GENERIC_SAMPLE_CONTEXT = {
    "first_name": "Алиса",
    "company_name": "ООО «Пример»",
    "frontend_url": "https://erp.example.com",
}


def sample_context_for(key: str) -> dict:
    """Return the SAMPLE merge context used to preview/test a template key."""
    return SAMPLE_CONTEXTS.get(key, dict(_GENERIC_SAMPLE_CONTEXT))


def preview_template(key: str, context: dict | None = None) -> dict:
    """Render subject/html/text for a key against a sample context. No send.

    Uses the same `_render_bodies` pipeline as production, so it transparently
    reflects whether a DB override or the file template is active for the key.
    """
    rendering_context = context if context is not None else sample_context_for(key)
    subject, text_body, html_body = _render_bodies(key, rendering_context)
    return {
        "key": key,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "context_used": rendering_context,
    }


def test_send_template(key: str, to_email: str, *, user=None, context: dict | None = None):
    """Send the rendered template to a single address via the real pipeline.

    Returns the EmailLog row written by `send_templated_email`, so the caller can
    surface delivery status. The send is audited like any other outbound mail.
    """
    rendering_context = context if context is not None else sample_context_for(key)
    return send_templated_email(
        key,
        rendering_context,
        to=[to_email],
        channel="transactional",
        user=user,
    )
