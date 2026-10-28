from rest_framework import serializers

from accounts.serializers import CompanySerializer, FreelancerSerializer
from .models import BillingRun, Invoice, InvoiceDelivery, InvoiceLine


class BillingRunSerializer(serializers.ModelSerializer):
    run_id = serializers.IntegerField(source='id', read_only=True)
    month = serializers.DateField(source='period', format='%Y-%m', read_only=True)
    status = serializers.SerializerMethodField()
    invoices_generated = serializers.IntegerField(source='invoices.count', read_only=True)

    class Meta:
        model = BillingRun
        fields = [
            'run_id', 'month', 'status', 'invoices_generated',
            'emails_sent', 'emails_failed',
        ]

    def get_status(self, obj):
        return 'completed_with_errors' if obj.emails_failed else 'completed'


class InvoiceDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceDelivery
        fields = ['recipient', 'email', 'status', 'attempts', 'last_error', 'sent_at']


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ['id', 'timesheet_entry', 'date', 'hours', 'daily_rate', 'amount']


class InvoiceSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    month = serializers.DateField(source='period', format='%Y-%m', read_only=True)
    company = CompanySerializer(read_only=True)
    freelancer = FreelancerSerializer(read_only=True)
    deliveries = InvoiceDeliverySerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = ['id', 'number', 'month', 'company', 'freelancer', 'total', 'created_at', 'deliveries']


class InvoiceDetailSerializer(InvoiceSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ['lines']
