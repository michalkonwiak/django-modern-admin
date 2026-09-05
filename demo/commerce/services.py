from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from demo.commerce.models import Activity, Customer, Order


@transaction.atomic
def archive_customer(*, customer: Customer, reason: str, actor: AbstractBaseUser) -> Customer:
    if customer.status == Customer.Status.INACTIVE:
        raise ValidationError("This customer is already inactive.")
    customer.status = Customer.Status.INACTIVE
    customer.notes = "\n".join(part for part in (customer.notes, f"Archived: {reason}") if part)
    customer.save(update_fields=("status", "notes", "updated_at"))
    Activity.objects.create(customer=customer, actor=actor, verb="archived", summary=reason)
    return customer


@transaction.atomic
def cancel_order(*, order: Order, reason: str, actor: AbstractBaseUser) -> Order:
    if order.status in {Order.Status.SHIPPED, Order.Status.CANCELLED, Order.Status.REFUNDED}:
        raise ValidationError("Only draft or processing orders can be cancelled.")
    order.status = Order.Status.CANCELLED
    order.cancellation_reason = reason
    order.save(update_fields=("status", "cancellation_reason", "updated_at"))
    Activity.objects.create(
        customer=order.customer,
        actor=actor,
        verb="cancelled order",
        summary=f"{order.number}: {reason}",
    )
    return order


@transaction.atomic
def mark_order_shipped(*, order: Order, actor: AbstractBaseUser) -> Order:
    if order.status != Order.Status.PROCESSING:
        raise ValidationError("Only processing orders can be marked as shipped.")
    order.status = Order.Status.SHIPPED
    order.save(update_fields=("status", "updated_at"))
    Activity.objects.create(
        customer=order.customer,
        actor=actor,
        verb="shipped order",
        summary=f"{order.number} was marked shipped at {timezone.now():%H:%M}.",
    )
    return order
