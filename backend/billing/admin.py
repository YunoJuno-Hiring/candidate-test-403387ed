from django.contrib import admin

from .models import BillingRun, Invoice, InvoiceDelivery, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    readonly_fields = ['timesheet_entry', 'date', 'hours', 'daily_rate', 'amount']


class InvoiceDeliveryInline(admin.TabularInline):
    model = InvoiceDelivery
    extra = 0
    readonly_fields = ['recipient', 'email', 'status', 'attempts', 'last_error', 'sent_at']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'period', 'total', 'created_at']
    list_filter = ['period', 'company']
    inlines = [InvoiceLineInline, InvoiceDeliveryInline]


@admin.register(BillingRun)
class BillingRunAdmin(admin.ModelAdmin):
    list_display = [
        '__str__', 'triggered_by', 'started_at',
        'emails_sent', 'emails_failed',
    ]
