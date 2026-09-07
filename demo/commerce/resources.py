from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from demo.commerce import services
from demo.commerce.forms import (
    ArchiveCustomerForm,
    CancelOrderForm,
    CustomerForm,
    OrderForm,
    ShipOrderForm,
)
from demo.commerce.models import Customer, Invoice, Order, Organization, Payment, Product
from modern_admin import Dashboard, ModelResource, PageResource, site
from modern_admin.actions import ActionResult, ResourceAction
from modern_admin.columns import (
    BadgeColumn,
    DateColumn,
    DateTimeColumn,
    MoneyColumn,
    NumberColumn,
    RelationColumn,
    TextColumn,
)
from modern_admin.filters import ChoiceFilter, DateRangeFilter, RelationFilter
from modern_admin.navigation import Navigation
from modern_admin.queues import WorkQueue
from modern_admin.sections import DetailSection, DetailTab, RelatedObjectList
from modern_admin.widgets import MetricWidget, ProgressWidget, TemplateWidget
from modern_admin.workflows import TransitionAction

STATUS_VARIANTS = {
    "active": "success",
    "succeeded": "success",
    "paid": "success",
    "shipped": "success",
    "processing": "info",
    "open": "info",
    "lead": "neutral",
    "draft": "neutral",
    "pending": "warning",
    "at_risk": "warning",
    "overdue": "danger",
    "inactive": "danger",
    "cancelled": "danger",
    "failed": "danger",
    "void": "danger",
    "refunded": "warning",
    "retired": "neutral",
}

site.extra_css = ("commerce/demo.css",)


class ArchiveCustomer(ResourceAction[Customer]):
    key = "archive"
    label = "Archive customer"
    description = "The customer becomes inactive. Existing commercial records are retained."
    icon = "archive"
    variant = "danger"
    placements = ("row", "detail", "bulk")
    form_class = ArchiveCustomerForm

    def has_permission(self, request: HttpRequest, obj: Customer | None = None) -> bool:
        return super().has_permission(request, obj) and (
            obj is None or obj.status != Customer.Status.INACTIVE
        )

    def execute(
        self, *, request: HttpRequest, obj: Customer, cleaned_data: Mapping[str, Any]
    ) -> ActionResult:
        services.archive_customer(customer=obj, reason=cleaned_data["reason"], actor=request.user)
        return ActionResult.success(
            "Customer archived.", refresh=("#resource-panel", "#resource-detail")
        )

    def execute_bulk(self, *, request, queryset, cleaned_data):  # type: ignore[no-untyped-def]
        archived = 0
        for customer in queryset.select_for_update().exclude(status=Customer.Status.INACTIVE):
            services.archive_customer(
                customer=customer,
                reason=cleaned_data["reason"],
                actor=request.user,
            )
            archived += 1
        return ActionResult.success(
            f"Archived {archived} customer{'s' if archived != 1 else ''}.",
            refresh=("#resource-panel",),
        )


class CancelOrder(TransitionAction[Order]):
    key = "cancel"
    label = "Cancel order"
    description = "This stops fulfillment. The reason is recorded for the support team."
    icon = "x"
    variant = "danger"
    form_class = CancelOrderForm
    from_states = (Order.Status.DRAFT, Order.Status.PROCESSING)
    unavailable_message = "Only draft or processing orders can be cancelled."

    def execute(
        self, *, request: HttpRequest, obj: Order, cleaned_data: Mapping[str, Any]
    ) -> ActionResult:
        services.cancel_order(order=obj, reason=cleaned_data["reason"], actor=request.user)
        return ActionResult.success(
            "Order cancelled.", refresh=("#resource-panel", "#resource-detail")
        )


class MarkOrderShipped(TransitionAction[Order]):
    key = "ship"
    label = "Mark shipped"
    description = "Confirm that fulfillment handed this order to the carrier."
    icon = "package"
    variant = "primary"
    form_class = ShipOrderForm
    from_states = (Order.Status.PROCESSING,)
    unavailable_message = "Only processing orders can be marked as shipped."

    def execute(
        self, *, request: HttpRequest, obj: Order, cleaned_data: Mapping[str, Any]
    ) -> ActionResult:
        services.mark_order_shipped(order=obj, actor=request.user)
        return ActionResult.success(
            "Order marked as shipped.", refresh=("#resource-panel", "#resource-detail")
        )


def customer_orders_context(request: HttpRequest, customer: Customer) -> Mapping[str, Any]:
    return {"orders": customer.orders.all()[:8]}


def customer_contacts_context(request: HttpRequest, customer: Customer) -> Mapping[str, Any]:
    return {"contacts": customer.contacts.all()}


def customer_notes_context(request: HttpRequest, customer: Customer) -> Mapping[str, Any]:
    return {"notes": customer.notes}


def order_invoices_context(request: HttpRequest, order: Order) -> Mapping[str, Any]:
    return {"invoices": order.invoices.all()}


@site.register(Customer)
class CustomerResource(ModelResource[Customer]):
    queues = (
        WorkQueue("mine", "Assigned to me", lambda request: Q(owner=request.user)),
        WorkQueue(
            "attention",
            "Needs attention",
            Q(status=Customer.Status.AT_RISK),
            description="Accounts at risk. Review the relationship before taking action.",
        ),
        WorkQueue("leads", "New leads", Q(status=Customer.Status.LEAD)),
    )
    icon = "users"
    title = "Customers"
    description = "Accounts, relationships, and commercial health across the workspace."
    navigation = Navigation(label="Customers", icon="users", group="Relationships", order=10)
    list_display = (
        TextColumn("name", label="Customer", secondary="email", width="25%"),
        RelationColumn("organization", width="19%"),
        BadgeColumn("status", variants=STATUS_VARIANTS),
        MoneyColumn("lifetime_value", label="Lifetime value", currency="USD"),
        RelationColumn("owner", sortable="owner__last_name"),
        DateColumn("created_at", label="Created", format="M j, Y"),
    )
    search_fields = ("name", "email", "organization__name")
    filters = (
        ChoiceFilter("status"),
        RelationFilter("organization"),
        DateRangeFilter("created_at"),
    )
    ordering = ("-created_at",)
    form_class = CustomerForm
    actions = (ArchiveCustomer,)
    detail_sections = (
        DetailSection(
            title="Profile",
            description="Primary relationship and contact details.",
            fields=("name", "email", "phone", "organization", "owner", "status"),
        ),
        DetailSection(
            title="Commercial summary",
            fields=("lifetime_value", "orders_count", "open_invoice_total", "created_at"),
        ),
    )
    detail_tabs = (
        RelatedObjectList("orders", "Orders", "order", "customer", icon="receipt"),
        DetailTab(
            "contacts",
            "Contacts",
            "commerce/tabs/customer_contacts.html",
            "users",
            context=customer_contacts_context,
        ),
        DetailTab(
            "notes",
            "Notes",
            "commerce/tabs/customer_notes.html",
            "file",
            context=customer_notes_context,
        ),
    )

    def get_queryset(self, request: HttpRequest):  # type: ignore[no-untyped-def]
        return (
            super()
            .get_queryset(request)
            .select_related("organization", "owner")
            .annotate(order_total=Count("orders", distinct=True))
        )

    def orders_count(self, obj: Customer) -> str:
        return f"{obj.order_total} order{'s' if obj.order_total != 1 else ''}"

    def open_invoice_total(self, obj: Customer) -> str:
        value = obj.invoices.filter(
            status__in=(Invoice.Status.OPEN, Invoice.Status.OVERDUE)
        ).aggregate(total=Sum("total"))["total"] or Decimal("0")
        return f"${value:,.2f}"


@site.register(Organization)
class OrganizationResource(ModelResource[Organization]):
    icon = "building-2"
    title = "Companies"
    description = "Organizations connected to your customer portfolio."
    navigation = Navigation(label="Companies", icon="building-2", group="Relationships", order=20)
    list_display = (
        TextColumn("name", label="Company", secondary="domain", width="32%"),
        TextColumn("industry"),
        NumberColumn("employee_count", label="Employees"),
        DateColumn("created_at", format="M j, Y"),
    )
    search_fields = ("name", "domain", "industry")
    ordering = ("name",)


@site.register(Order)
class OrderResource(ModelResource[Order]):
    queues = (
        WorkQueue(
            "fulfillment",
            "Ready to ship",
            Q(status=Order.Status.PROCESSING),
            description="Review each order and confirm handover to the carrier.",
        ),
        WorkQueue(
            "overdue",
            "Overdue",
            lambda request: Q(status=Order.Status.PROCESSING, expected_at__lt=timezone.localdate()),
            description="Processing orders past their expected date.",
        ),
        WorkQueue("drafts", "Drafts", Q(status=Order.Status.DRAFT)),
    )
    icon = "receipt"
    title = "Orders"
    description = "Track fulfillment, value, and exceptions from placement to delivery."
    navigation = Navigation(label="Orders", icon="receipt", group="Operations", order=10)
    list_display = (
        TextColumn("number", label="Order", width="16%", sortable="id"),
        RelationColumn("customer", width="24%", sortable="customer__name"),
        BadgeColumn("status", variants=STATUS_VARIANTS),
        MoneyColumn("total", currency="USD"),
        DateTimeColumn("placed_at", label="Placed", format="M j, Y, P"),
        DateColumn("expected_at", label="Expected", format="M j, Y"),
    )
    search_fields = ("id", "customer__name", "customer__email")
    filters = (ChoiceFilter("status"), RelationFilter("customer"), DateRangeFilter("created_at"))
    ordering = ("-created_at",)
    form_class = OrderForm
    actions = (MarkOrderShipped, CancelOrder)
    detail_sections = (
        DetailSection(
            title="Order summary",
            fields=("number", "customer", "status", "placed_at", "expected_at", "currency"),
        ),
        DetailSection(title="Financials", fields=("subtotal", "tax", "total", "updated_at")),
    )
    detail_tabs = (
        DetailTab(
            "invoices",
            "Invoices",
            "commerce/tabs/order_invoices.html",
            "credit-card",
            context=order_invoices_context,
        ),
        DetailTab("fulfillment", "Fulfillment", "commerce/tabs/order_fulfillment.html", "package"),
    )

    def get_queryset(self, request: HttpRequest):  # type: ignore[no-untyped-def]
        return super().get_queryset(request).select_related("customer", "customer__organization")


@site.register(Invoice)
class InvoiceResource(ModelResource[Invoice]):
    icon = "credit-card"
    title = "Invoices"
    navigation = Navigation(label="Invoices", icon="credit-card", group="Billing", order=10)
    list_display = (
        TextColumn("number", label="Invoice", width="18%"),
        RelationColumn("customer", width="24%", sortable="customer__name"),
        BadgeColumn("status", variants=STATUS_VARIANTS),
        MoneyColumn("total"),
        DateColumn("due_date", label="Due", format="M j, Y"),
    )
    search_fields = ("number", "customer__name", "customer__email")
    filters = (ChoiceFilter("status"), DateRangeFilter("due_date"))
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest):  # type: ignore[no-untyped-def]
        return super().get_queryset(request).select_related("customer", "order")


@site.register(Payment)
class PaymentResource(ModelResource[Payment]):
    icon = "circle-dollar-sign"
    title = "Payments"
    navigation = Navigation(label="Payments", icon="circle-dollar-sign", group="Billing", order=20)
    list_display = (
        TextColumn("reference", label="Reference", width="23%"),
        RelationColumn("invoice"),
        BadgeColumn("status", variants=STATUS_VARIANTS),
        MoneyColumn("amount"),
        DateTimeColumn("processed_at", label="Processed"),
    )
    search_fields = ("reference", "invoice__number", "invoice__customer__name")
    filters = (ChoiceFilter("status"), DateRangeFilter("created_at"))
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest):  # type: ignore[no-untyped-def]
        return super().get_queryset(request).select_related("invoice", "invoice__customer")


@site.register(Product)
class ProductResource(ModelResource[Product]):
    form_fields = ("name", "sku", "status", "unit_price", "stock")
    icon = "package"
    title = "Products"
    navigation = Navigation(label="Products", icon="package", group="Operations", order=20)
    list_display = (
        TextColumn("name", label="Product", secondary="sku", width="32%"),
        BadgeColumn("status", variants=STATUS_VARIANTS),
        MoneyColumn("unit_price", label="Unit price"),
        NumberColumn("stock"),
        DateColumn("created_at", label="Created"),
    )
    search_fields = ("name", "sku")
    filters = (ChoiceFilter("status"),)
    ordering = ("name",)


def dashboard_revenue(request: HttpRequest) -> str:
    total = (
        Payment.objects.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    return f"${total:,.0f}"


def dashboard_open_invoices(request: HttpRequest) -> int:
    return Invoice.objects.filter(status__in=(Invoice.Status.OPEN, Invoice.Status.OVERDUE)).count()


def recent_orders(request: HttpRequest) -> Mapping[str, Any]:
    return {"orders": Order.objects.select_related("customer").all()[:7]}


def pipeline_context(request: HttpRequest) -> Mapping[str, Any]:
    total = Customer.objects.count() or 1
    rows = []
    for value, label in Customer.Status.choices:
        count = Customer.objects.filter(status=value).count()
        rows.append(
            {
                "value": value,
                "label": label,
                "count": count,
                "percent": round(count / total * 100),
                "variant": STATUS_VARIANTS[value],
            }
        )
    return {"pipeline": rows, "total": total}


@site.set_dashboard
class OperationsDashboard(Dashboard):
    # The widgets read across the commercial records, so the overview needs all of them.
    permission_required = (
        "commerce.view_workspace_dashboard",
        "commerce.view_customer",
        "commerce.view_order",
        "commerce.view_invoice",
        "commerce.view_payment",
    )
    template_name = "commerce/dashboard.html"
    widgets = (
        MetricWidget(
            "revenue",
            "Collected revenue",
            value=dashboard_revenue,
            change=8.4,
            description="versus last month",
            icon="circle-dollar-sign",
        ),
        MetricWidget(
            "orders",
            "Orders in motion",
            value=lambda request: Order.objects.filter(status=Order.Status.PROCESSING).count(),
            change=3.2,
            description="currently processing",
            icon="receipt",
        ),
        MetricWidget(
            "customers",
            "Active customers",
            value=lambda request: Customer.objects.filter(status=Customer.Status.ACTIVE).count(),
            change=5.1,
            description="healthy accounts",
            icon="users",
        ),
        MetricWidget(
            "invoices",
            "Invoices to collect",
            value=dashboard_open_invoices,
            change=-2.0,
            description="open or overdue",
            icon="credit-card",
        ),
        TemplateWidget(
            "recent-orders",
            "Recent orders",
            "commerce/widgets/recent_orders.html",
            span=2,
            context=recent_orders,
        ),
        TemplateWidget(
            "pipeline",
            "Customer health",
            "commerce/widgets/customer_health.html",
            span=2,
            context=pipeline_context,
        ),
        ProgressWidget(
            "monthly-goal",
            "September revenue goal",
            span=2,
            value=lambda request: (
                Payment.objects.filter(status=Payment.Status.SUCCEEDED).aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            ),
            total=250000,
            description="collected",
        ),
        TemplateWidget(
            "attention",
            "Needs attention",
            "commerce/widgets/attention.html",
            span=2,
            context=lambda request: {
                "invoices": Invoice.objects.select_related("customer").filter(
                    status=Invoice.Status.OVERDUE
                )[:4]
            },
        ),
    )

    def get_context_data(self, request: HttpRequest, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(request, **kwargs)
        overdue = Invoice.objects.filter(status=Invoice.Status.OVERDUE).count()
        if overdue:
            self.alerts = {
                "title": f"{overdue} overdue invoice{'s' if overdue != 1 else ''}",
                "message": "Collections work is waiting for review.",
                "url": reverse("modern_admin:invoice_list") + "?status=overdue",
            }
        return context


@site.page(path="settings/", label="Settings", icon="settings", group="System", order=10)
class SettingsPage(PageResource):
    permission_required = "commerce.view_workspace_settings"
    title = "Workspace settings"
    description = "Configuration shared across operations."
    template_name = "commerce/settings.html"

    def get_context_data(self, request: HttpRequest, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(
            request,
            workspace={
                "name": "Northstar Industries",
                "region": "European Union",
                "timezone": "Europe/Warsaw",
                "currency": "USD",
            },
            **kwargs,
        )
