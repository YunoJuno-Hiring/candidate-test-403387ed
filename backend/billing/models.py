from django.conf import settings
from django.db import models

from accounts.models import Company, Freelancer
from contracts.models import TimesheetEntry


class BillingRun(models.Model):
    """Audit record of one request to bill a month.

    Runs are safe to repeat: invoices and lines are protected by database
    constraints, so a second run for the same month only retries deliveries
    that haven't gone out yet.
    """

    period = models.DateField(help_text='First day of the billed month.')
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='billing_runs')
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    emails_sent = models.PositiveIntegerField(default=0)
    emails_failed = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'Billing run {self.period:%Y-%m} ({self.company.name})'


class Invoice(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='invoices')
    freelancer = models.ForeignKey(Freelancer, on_delete=models.PROTECT, related_name='invoices')
    period = models.DateField(help_text='First day of the billed month.')
    billing_run = models.ForeignKey(BillingRun, on_delete=models.PROTECT, related_name='invoices')
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period', 'company__name', 'freelancer__name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'freelancer', 'period'],
                name='unique_invoice_per_company_freelancer_period',
            ),
        ]

    @property
    def number(self):
        return f'INV-{self.period:%Y%m}-{self.pk:06d}'

    def __str__(self):
        return f'{self.number} — {self.freelancer.name} @ {self.company.name}'


class InvoiceLine(models.Model):
    """One billed timesheet entry.

    Date, hours and rate are copied from the entry and its contract at billing
    time so the invoice never changes after it has been issued.
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    # One-to-one is what guarantees an entry is billed at most once.
    timesheet_entry = models.OneToOneField(
        TimesheetEntry, on_delete=models.PROTECT, related_name='invoice_line'
    )
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    daily_rate = models.DecimalField(max_digits=8, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['date', 'id']

    def __str__(self):
        return f'{self.invoice.number}: {self.date} {self.hours}h = {self.amount}'


class InvoiceDelivery(models.Model):
    """Outbox row for one invoice email.

    Rows are written in the same transaction as the invoice and sent after it
    commits, so a failed send never rolls back an invoice and can be retried.
    """

    RECIPIENT_COMPANY = 'company'
    RECIPIENT_FREELANCER = 'freelancer'
    RECIPIENT_CHOICES = [
        (RECIPIENT_COMPANY, 'Company'),
        (RECIPIENT_FREELANCER, 'Freelancer'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='deliveries')
    recipient = models.CharField(max_length=10, choices=RECIPIENT_CHOICES)
    email = models.EmailField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['invoice', 'recipient']
        constraints = [
            models.UniqueConstraint(
                fields=['invoice', 'recipient'], name='unique_delivery_per_invoice_recipient'
            ),
        ]

    def __str__(self):
        return f'{self.invoice.number} → {self.email} ({self.status})'
