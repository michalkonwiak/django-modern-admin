from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from demo.commerce.models import Contact, Customer, Invoice, Order, Organization, Payment
from modern_admin.models import AuditEvent


class Command(BaseCommand):
    help = "Create a deterministic, realistic Modern Admin demo dataset."

    @transaction.atomic
    def handle(self, *args, **options):  # type: ignore[no-untyped-def]
        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.com", "first_name": "Maya", "last_name": "Chen"},
        )
        user.first_name = "Maya"
        user.last_name = "Chen"
        user.email = "demo@example.com"
        user.is_staff = True
        user.is_superuser = True
        user.set_password("demo")
        user.save()

        organizations_data = [
            ("Arc Foundry", "arcfoundry.co", "Manufacturing", 420),
            ("Northline Labs", "northline.io", "Software", 185),
            ("Canopy Works", "canopyworks.com", "Logistics", 760),
            ("Helio Systems", "helio.systems", "Energy", 310),
            ("Fieldnote", "fieldnote.app", "Software", 94),
            ("Morrow & Co.", "morrow.co", "Professional services", 128),
            ("Driftwood Supply", "driftwoodsupply.com", "Retail", 245),
            ("Kitehouse", "kitehouse.eu", "Real estate", 66),
        ]
        organizations = []
        for name, domain, industry, employees in organizations_data:
            organization, _ = Organization.objects.update_or_create(
                domain=domain,
                defaults={
                    "name": name,
                    "industry": industry,
                    "website": f"https://{domain}",
                    "employee_count": employees,
                },
            )
            organizations.append(organization)

        names = [
            "Alex Morgan",
            "Anna Kowalska",
            "Samira Okafor",
            "Noah Williams",
            "Mei Tan",
            "Lucas Bernard",
            "Sofia Alvarez",
            "Daniel Kim",
            "Amara Patel",
            "Elias Berg",
            "Nadia Petrova",
            "Theo Martin",
            "Clara Jensen",
            "Mateo Silva",
            "Aisha Rahman",
            "Jonas Vogel",
            "Elena Rossi",
            "Owen Hughes",
            "Leila Haddad",
            "Max Nowak",
            "Rina Sato",
            "Finn Andersen",
            "Inez Costa",
            "Adam Zieliński",
            "Marta Nowicka",
            "Leo Dubois",
            "Sara Lind",
            "Milan Horvat",
            "Eva Müller",
            "Tomasz Wiśniewski",
            "Nora Ibrahim",
            "Ben Carter",
            "Zoe Clark",
            "Victor Chen",
            "Julia Santos",
            "Anton Weber",
        ]
        status_cycle = [
            Customer.Status.ACTIVE,
            Customer.Status.ACTIVE,
            Customer.Status.LEAD,
            Customer.Status.ACTIVE,
            Customer.Status.AT_RISK,
            Customer.Status.ACTIVE,
            Customer.Status.INACTIVE,
        ]
        customers = []
        now = timezone.now()
        for index, name in enumerate(names):
            organization = organizations[index % len(organizations)]
            first, last = name.lower().replace("ń", "n").replace("ś", "s").split(" ", 1)
            email = f"{first}.{last.replace(' ', '.')}@{organization.domain}"
            customer, _ = Customer.objects.update_or_create(
                email=email,
                defaults={
                    "name": name,
                    "organization": organization,
                    "phone": f"+1 415 555 {1100 + index}",
                    "status": status_cycle[index % len(status_cycle)],
                    "lifetime_value": Decimal(3200 + ((index * 3475) % 42000)),
                    "owner": user,
                    "notes": "Key account context is kept here for sales, operations, and support.",
                },
            )
            Customer.objects.filter(pk=customer.pk).update(
                created_at=now - timedelta(days=index * 2, hours=index % 7)
            )
            customer.refresh_from_db()
            customers.append(customer)
            Contact.objects.update_or_create(
                customer=customer,
                email=email,
                defaults={"name": name, "role": "Primary stakeholder", "is_primary": True},
            )

        order_statuses = [
            Order.Status.PROCESSING,
            Order.Status.SHIPPED,
            Order.Status.DRAFT,
            Order.Status.PROCESSING,
            Order.Status.SHIPPED,
            Order.Status.CANCELLED,
        ]
        invoices = []
        for index in range(58):
            customer = customers[(index * 5) % len(customers)]
            subtotal = Decimal(850 + ((index * 1175) % 17000))
            tax = (subtotal * Decimal("0.08")).quantize(Decimal("0.01"))
            created = now - timedelta(days=index, hours=(index * 3) % 20)
            order, _ = Order.objects.update_or_create(
                pk=index + 1,
                defaults={
                    "customer": customer,
                    "status": order_statuses[index % len(order_statuses)],
                    "subtotal": subtotal,
                    "tax": tax,
                    "total": subtotal + tax,
                    "currency": "USD",
                    "placed_at": created + timedelta(hours=1),
                    "expected_at": (created + timedelta(days=5)).date(),
                    "internal_note": "Priority handling requested." if index % 9 == 0 else "",
                },
            )
            Order.objects.filter(pk=order.pk).update(created_at=created, updated_at=created)
            order.refresh_from_db()

            invoice_status = (
                Invoice.Status.OVERDUE
                if index % 11 == 0
                else Invoice.Status.OPEN
                if index % 4 == 0
                else Invoice.Status.PAID
            )
            invoice, _ = Invoice.objects.update_or_create(
                number=f"INV-2026-{1000 + index}",
                defaults={
                    "order": order,
                    "customer": customer,
                    "status": invoice_status,
                    "total": order.total,
                    "due_date": (created + timedelta(days=14)).date(),
                    "issued_at": created + timedelta(hours=2),
                },
            )
            Invoice.objects.filter(pk=invoice.pk).update(created_at=created + timedelta(hours=2))
            invoice.refresh_from_db()
            invoices.append(invoice)

            if invoice.status == Invoice.Status.PAID:
                payment, _ = Payment.objects.update_or_create(
                    reference=f"pay_ns_{90000 + index}",
                    defaults={
                        "invoice": invoice,
                        "status": Payment.Status.SUCCEEDED,
                        "amount": invoice.total,
                        "processed_at": created + timedelta(days=2),
                    },
                )
                Payment.objects.filter(pk=payment.pk).update(created_at=created + timedelta(days=2))

        for customer in customers[:8]:
            AuditEvent.objects.get_or_create(
                action="imported",
                resource_type=customer._meta.label_lower,
                resource_id=str(customer.pk),
                defaults={
                    "actor": user,
                    "object_label": str(customer),
                    "metadata": {"source": "CRM migration"},
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {len(customers)} customers, {Order.objects.count()} orders, "
                f"{Invoice.objects.count()} invoices. Sign in with demo / demo."
            )
        )
