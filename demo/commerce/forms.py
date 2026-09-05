from django import forms

from demo.commerce.models import Customer, Order


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = (
            "name",
            "email",
            "phone",
            "organization",
            "status",
            "lifetime_value",
            "owner",
            "notes",
        )
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            "customer",
            "status",
            "subtotal",
            "tax",
            "total",
            "currency",
            "placed_at",
            "expected_at",
            "internal_note",
        )
        widgets = {
            "placed_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expected_at": forms.DateInput(attrs={"type": "date"}),
            "internal_note": forms.Textarea(attrs={"rows": 4}),
        }


class ArchiveCustomerForm(forms.Form):
    reason = forms.CharField(
        label="Reason",
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="This note is recorded in the customer activity timeline.",
    )


class CancelOrderForm(forms.Form):
    reason = forms.CharField(
        label="Cancellation reason",
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="The reason is visible to operations and support.",
    )


class ShipOrderForm(forms.Form):
    confirmed = forms.BooleanField(initial=True, widget=forms.HiddenInput)
