from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from demo.commerce.models import Customer, Order, Organization


@pytest.fixture
def user(db):
    user_model = get_user_model()
    return user_model.objects.create_superuser(
        username="operator",
        email="operator@example.com",
        password="secret",
        first_name="Maya",
        last_name="Chen",
    )


@pytest.fixture
def authenticated_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def organization(db):
    return Organization.objects.create(
        name="Northline Labs",
        domain="northline.example",
        industry="Software",
        employee_count=120,
    )


@pytest.fixture
def customers(db, organization, user):
    return [
        Customer.objects.create(
            name="Alex Morgan",
            email="alex@northline.example",
            organization=organization,
            status=Customer.Status.ACTIVE,
            lifetime_value=Decimal("14200.00"),
            owner=user,
        ),
        Customer.objects.create(
            name="Anna Kowalska",
            email="anna@northline.example",
            organization=organization,
            status=Customer.Status.LEAD,
            lifetime_value=Decimal("8940.00"),
            owner=user,
        ),
    ]


@pytest.fixture
def order(db, customers):
    return Order.objects.create(
        customer=customers[0],
        status=Order.Status.PROCESSING,
        subtotal=Decimal("1000.00"),
        tax=Decimal("80.00"),
        total=Decimal("1080.00"),
    )
