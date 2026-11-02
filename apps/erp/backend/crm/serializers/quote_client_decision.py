"""Решение клиента по КП, записанное сотрудником (A1 волны 18a): форма поля `QuoteSerializer.client_decision`."""

from rest_framework import serializers

from crm.services.quotes.on_behalf import CHANNELS


class QuoteClientDecisionMetaSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject"])
    channel = serializers.ChoiceField(choices=list(CHANNELS))
    counterparty_person = serializers.CharField()
    occurred_on = serializers.DateField(allow_null=True)
    comment = serializers.CharField(allow_blank=True)
    recorded_by_name = serializers.CharField(allow_blank=True)
    recorded_at = serializers.DateTimeField(allow_null=True)
    evidence_attachment_id = serializers.IntegerField(allow_null=True)
    evidence_name = serializers.CharField(allow_blank=True)


def client_decision_of(quote) -> dict | None:
    """Снимок `Quote.client_decision_meta` для ответа; `None` — клиент решил сам или ещё не решал."""
    meta = quote.client_decision_meta if isinstance(quote.client_decision_meta, dict) else {}
    if not meta.get("decision"):
        return None
    return {
        "decision": meta.get("decision"),
        "channel": meta.get("channel") or "",
        "counterparty_person": meta.get("counterparty_person") or "",
        "occurred_on": meta.get("occurred_on"),
        "comment": meta.get("comment") or "",
        "recorded_by_name": meta.get("recorded_by_name") or "",
        "recorded_at": meta.get("recorded_at"),
        "evidence_attachment_id": meta.get("evidence_attachment_id"),
        "evidence_name": meta.get("evidence_name") or "",
    }
