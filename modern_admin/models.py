from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="modern_admin_audit_events",
    )
    action = models.CharField(max_length=100)
    resource_type = models.CharField(max_length=200, db_index=True)
    resource_id = models.CharField(max_length=255, db_index=True)
    object_label = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("resource_type", "resource_id", "-created_at"))]

    def __str__(self) -> str:
        return f"{self.action}: {self.object_label or self.resource_id}"


class SavedView(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="modern_admin_saved_views",
    )
    site_name = models.CharField(max_length=100)
    resource_key = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    query_string = models.CharField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "site_name", "resource_key", "name"),
                name="modern_admin_unique_saved_view",
            )
        ]

    def __str__(self) -> str:
        return self.name


class ProductTourState(models.Model):
    """An account's first-run decision, shared across sessions and devices."""

    class Outcome(models.TextChoices):
        COMPLETED = "completed", "Completed"
        DISMISSED = "dismissed", "Dismissed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="modern_admin_product_tours",
    )
    site_name = models.CharField(max_length=100)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    finished_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "site_name"), name="modern_admin_unique_product_tour",
            )
        ]
