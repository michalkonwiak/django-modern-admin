from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Organization(models.Model):
    name = models.CharField(verbose_name=_("name"), max_length=180)
    domain = models.CharField(verbose_name=_("domain"), max_length=180, blank=True)
    industry = models.CharField(verbose_name=_("industry"), max_length=100, blank=True)
    website = models.URLField(verbose_name=_("website"), blank=True)
    employee_count = models.PositiveIntegerField(verbose_name=_("employee count"), default=0)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class WorkspaceAccess(models.Model):
    """Permission host for pages that are not backed by records of their own.

    The model is unmanaged and has no table; it exists so the dashboard and the
    settings page can be granted with ordinary Django permissions.
    """

    class Meta:
        managed = False
        default_permissions = ()
        verbose_name = _("workspace access")
        verbose_name_plural = _("workspace access")
        permissions = (
            ("view_workspace_dashboard", "Can view the operations overview"),
            ("view_workspace_settings", "Can view workspace settings"),
        )


class Customer(models.Model):
    class Status(models.TextChoices):
        LEAD = "lead", _("Lead")
        ACTIVE = "active", _("Active")
        AT_RISK = "at_risk", _("At risk")
        INACTIVE = "inactive", _("Inactive")

    organization = models.ForeignKey(
        Organization,
        verbose_name=_("organization"),
        on_delete=models.PROTECT,
        related_name="customers",
    )
    name = models.CharField(verbose_name=_("name"), max_length=180)
    email = models.EmailField(verbose_name=_("email"))
    phone = models.CharField(verbose_name=_("phone"), max_length=40, blank=True)
    status = models.CharField(
        verbose_name=_("status"), max_length=20, choices=Status.choices, default=Status.LEAD
    )
    lifetime_value = models.DecimalField(
        verbose_name=_("lifetime value"), max_digits=12, decimal_places=2, default=Decimal("0")
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("owner"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_customers",
    )
    notes = models.TextField(verbose_name=_("notes"), blank=True)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name=_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("customer")
        verbose_name_plural = _("customers")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.name


class Contact(models.Model):
    customer = models.ForeignKey(
        Customer, verbose_name=_("customer"), on_delete=models.CASCADE, related_name="contacts"
    )
    name = models.CharField(verbose_name=_("name"), max_length=180)
    email = models.EmailField(verbose_name=_("email"))
    role = models.CharField(verbose_name=_("role"), max_length=120, blank=True)
    is_primary = models.BooleanField(verbose_name=_("is primary"), default=False)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("contact")
        verbose_name_plural = _("contacts")
        ordering = ("-is_primary", "name")

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DRAFT = "draft", _("Draft")
        RETIRED = "retired", _("Retired")

    name = models.CharField(verbose_name=_("name"), max_length=180)
    sku = models.CharField(verbose_name=_("sku"), max_length=40, unique=True)
    status = models.CharField(
        verbose_name=_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    unit_price = models.DecimalField(verbose_name=_("unit price"), max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(verbose_name=_("stock"), default=0)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("product")
        verbose_name_plural = _("products")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PROCESSING = "processing", _("Processing")
        SHIPPED = "shipped", _("Shipped")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")

    customer = models.ForeignKey(
        Customer, verbose_name=_("customer"), on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(
        verbose_name=_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    subtotal = models.DecimalField(verbose_name=_("subtotal"), max_digits=12, decimal_places=2)
    tax = models.DecimalField(
        verbose_name=_("tax"), max_digits=12, decimal_places=2, default=Decimal("0")
    )
    total = models.DecimalField(verbose_name=_("total"), max_digits=12, decimal_places=2)
    currency = models.CharField(verbose_name=_("currency"), max_length=3, default="USD")
    placed_at = models.DateTimeField(verbose_name=_("placed at"), null=True, blank=True)
    expected_at = models.DateField(verbose_name=_("expected at"), null=True, blank=True)
    cancellation_reason = models.TextField(verbose_name=_("cancellation reason"), blank=True)
    internal_note = models.TextField(verbose_name=_("internal note"), blank=True)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name=_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("order")
        verbose_name_plural = _("orders")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.number

    @property
    def number(self) -> str:
        return f"ORD-{self.pk:05d}" if self.pk else str(_("New order"))


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        OPEN = "open", _("Open")
        PAID = "paid", _("Paid")
        VOID = "void", _("Void")
        OVERDUE = "overdue", _("Overdue")

    order = models.ForeignKey(
        Order, verbose_name=_("order"), on_delete=models.PROTECT, related_name="invoices"
    )
    customer = models.ForeignKey(
        Customer, verbose_name=_("customer"), on_delete=models.PROTECT, related_name="invoices"
    )
    number = models.CharField(verbose_name=_("number"), max_length=30, unique=True)
    status = models.CharField(
        verbose_name=_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    total = models.DecimalField(verbose_name=_("total"), max_digits=12, decimal_places=2)
    due_date = models.DateField(verbose_name=_("due date"))
    issued_at = models.DateTimeField(verbose_name=_("issued at"), null=True, blank=True)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("invoice")
        verbose_name_plural = _("invoices")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.number


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        REFUNDED = "refunded", _("Refunded")

    invoice = models.ForeignKey(
        Invoice, verbose_name=_("invoice"), on_delete=models.PROTECT, related_name="payments"
    )
    reference = models.CharField(verbose_name=_("reference"), max_length=60, unique=True)
    status = models.CharField(
        verbose_name=_("status"), max_length=20, choices=Status.choices, default=Status.PENDING
    )
    amount = models.DecimalField(verbose_name=_("amount"), max_digits=12, decimal_places=2)
    processed_at = models.DateTimeField(verbose_name=_("processed at"), null=True, blank=True)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.reference


class Activity(models.Model):
    customer = models.ForeignKey(
        Customer, verbose_name=_("customer"), on_delete=models.CASCADE, related_name="activities"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("actor"), null=True, on_delete=models.SET_NULL
    )
    verb = models.CharField(verbose_name=_("verb"), max_length=100)
    summary = models.CharField(verbose_name=_("summary"), max_length=255)
    metadata = models.JSONField(verbose_name=_("metadata"), default=dict, blank=True)
    created_at = models.DateTimeField(verbose_name=_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("activity")
        ordering = ("-created_at",)
        verbose_name_plural = _("Activities")

    def __str__(self) -> str:
        return self.summary
