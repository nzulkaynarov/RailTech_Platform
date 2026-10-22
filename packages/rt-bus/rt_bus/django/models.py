"""Модели таблиц rt_bus (L9) — те же столбцы и индексы, что `rt_bus.sqlalchemy.bus_tables`.

Операции шины идут общим SQL (`rt_bus.sql`) через курсор; модели — для миграций, админки и журнала.
"""

from __future__ import annotations

from django.db import models


class Outbox(models.Model):
    id = models.UUIDField(primary_key=True)
    type = models.CharField(max_length=200)
    source = models.CharField(max_length=100)
    subject = models.CharField(max_length=200, null=True)
    correlation_id = models.CharField(max_length=128)
    envelope = models.JSONField()
    created_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "rt_bus_outbox"
        indexes = [
            models.Index(
                fields=["created_at"], name="rt_bus_outbox_pending_idx", condition=models.Q(dispatched_at__isnull=True)
            )
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.id}"


class Delivery(models.Model):
    id = models.BigAutoField(primary_key=True)
    event_id = models.UUIDField()
    event_type = models.CharField(max_length=200)
    subscriber = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    attempts = models.IntegerField()
    next_attempt_at = models.DateTimeField(null=True)
    lease_until = models.DateTimeField(null=True)
    lease_token = models.UUIDField(null=True)
    last_attempt_at = models.DateTimeField(null=True)
    last_status_code = models.IntegerField(null=True)
    last_error = models.TextField(null=True)
    delivered_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "rt_bus_delivery"
        constraints = [
            models.UniqueConstraint(fields=["event_id", "subscriber"], name="rt_bus_delivery_event_sub_uniq")
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="rt_bus_delivery_due_idx"),
            models.Index(fields=["subscriber", "status"], name="rt_bus_delivery_sub_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} → {self.subscriber} ({self.status})"


class Inbox(models.Model):
    event_id = models.UUIDField(primary_key=True)
    type = models.CharField(max_length=200)
    source = models.CharField(max_length=100)
    publisher = models.CharField(max_length=64)
    subject = models.CharField(max_length=200, null=True)
    correlation_id = models.CharField(max_length=128)
    envelope = models.JSONField()
    status = models.CharField(max_length=16)
    attempts = models.IntegerField()
    error = models.TextField(null=True)
    received_at = models.DateTimeField()
    processed_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "rt_bus_inbox"
        indexes = [models.Index(fields=["status", "received_at"], name="rt_bus_inbox_status_idx")]

    def __str__(self) -> str:
        return f"{self.type} {self.event_id} ({self.status})"


class SubscriberState(models.Model):
    id = models.BigAutoField(primary_key=True)
    subscriber = models.CharField(max_length=64)
    consecutive_failures = models.IntegerField()
    paused_until = models.DateTimeField(null=True)
    last_failure_at = models.DateTimeField(null=True)
    last_success_at = models.DateTimeField(null=True)
    last_error = models.TextField(null=True)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "rt_bus_subscriber_state"
        constraints = [models.UniqueConstraint(fields=["subscriber"], name="rt_bus_subscriber_state_uniq")]

    def __str__(self) -> str:
        return self.subscriber
