"""
Monthly billing run.

A run bills one company for one month, in two phases with separate
transaction boundaries:

1. Invoicing. Each Company × Freelancer invoice is created in its own
   transaction together with its lines and its pending delivery rows. Database
   constraints make this idempotent: one invoice per company/freelancer/month,
   and a timesheet entry can only ever appear on one invoice line.

2. Delivery. After the invoices are committed, each pending or failed
   delivery is sent and its outcome recorded. A failed email never rolls back
   an invoice; it stays `failed` and the next run for that month retries it.
   Delivery is at-least-once: if the process dies between the SMTP send and
   the status update, that email is sent again on the next run.
"""
import datetime
import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from contracts.models import TimesheetEntry
from .models import BillingRun, Invoice, InvoiceDelivery, InvoiceLine

logger = logging.getLogger(__name__)

# Contracts are priced per day but hours are logged per entry, so an entry is
# billed pro rata against a standard working day.
HOURS_PER_DAY = Decimal('8')
PENNY = Decimal('0.01')


def parse_period(value) -> datetime.date:
    """Parse 'YYYY-MM' into the first day of that month."""
    try:
        return datetime.datetime.strptime(value, '%Y-%m').date()
    except (TypeError, ValueError):
        raise ValueError('Expected a month in YYYY-MM format.')


def next_period(period: datetime.date) -> datetime.date:
    return (period.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


def line_amount(hours: Decimal, daily_rate: Decimal) -> Decimal:
    return (hours * daily_rate / HOURS_PER_DAY).quantize(PENNY, rounding=ROUND_HALF_UP)


def run_billing(period: datetime.date, *, company, triggered_by=None) -> BillingRun:
    """Invoice the company's approved, unbilled entries dated in `period`, then send any undelivered emails."""
    run = BillingRun.objects.create(period=period, company=company, triggered_by=triggered_by)

    entries = TimesheetEntry.objects.filter(
        contract__company=company,
        status=TimesheetEntry.STATUS_APPROVED,
        date__gte=period,
        date__lt=next_period(period),
        invoice_line__isnull=True,
    )
    invoices = Invoice.objects.filter(company=company, period=period)

    entries_by_freelancer = defaultdict(list)
    for freelancer_id, entry_id in entries.values_list('contract__freelancer_id', 'id'):
        entries_by_freelancer[freelancer_id].append(entry_id)

    already_invoiced = set(invoices.values_list('freelancer_id', flat=True))
    for freelancer_id, entry_ids in entries_by_freelancer.items():
        # One invoice per company/freelancer/month: entries approved after that
        # invoice was issued are not added to it, and stay unbilled for now.
        if freelancer_id not in already_invoiced:
            _create_invoice(run, freelancer_id, entry_ids)

    undelivered = InvoiceDelivery.objects.filter(invoice__in=invoices).exclude(
        status=InvoiceDelivery.STATUS_SENT
    )
    for delivery_id in undelivered.values_list('id', flat=True):
        sent = deliver_invoice_email(delivery_id)
        if sent is True:
            run.emails_sent += 1
        elif sent is False:
            run.emails_failed += 1

    run.finished_at = timezone.now()
    run.save()
    return run


def _create_invoice(run, freelancer_id, entry_ids):
    try:
        with transaction.atomic():
            # Lock the entries so they can't be edited or un-approved while
            # they're being billed; re-check the filters under the lock.
            entries = list(
                TimesheetEntry.objects.select_for_update(of=('self',))
                .filter(
                    id__in=entry_ids,
                    status=TimesheetEntry.STATUS_APPROVED,
                    invoice_line__isnull=True,
                )
                .select_related('contract__freelancer__user')
                .order_by('date')
            )
            if not entries:
                return None

            lines = [
                InvoiceLine(
                    timesheet_entry=entry,
                    date=entry.date,
                    hours=entry.hours,
                    daily_rate=entry.contract.daily_rate,
                    amount=line_amount(entry.hours, entry.contract.daily_rate),
                )
                for entry in entries
            ]
            invoice = Invoice.objects.create(
                company=run.company,
                freelancer_id=freelancer_id,
                period=run.period,
                billing_run=run,
                total=sum((line.amount for line in lines), Decimal('0')),
            )
            for line in lines:
                line.invoice = invoice
            InvoiceLine.objects.bulk_create(lines)

            freelancer = entries[0].contract.freelancer
            recipients = [
                (InvoiceDelivery.RECIPIENT_COMPANY, run.company.billing_email),
                (InvoiceDelivery.RECIPIENT_FREELANCER, freelancer.user.email),
            ]
            InvoiceDelivery.objects.bulk_create([
                InvoiceDelivery(invoice=invoice, recipient=recipient, email=email)
                for recipient, email in recipients
                if email
            ])
            return invoice
    except IntegrityError:
        # A concurrent run created this invoice or billed one of these entries first.
        logger.info(
            'Skipped invoice for company=%s freelancer=%s period=%s: already billed',
            run.company_id, freelancer_id, run.period,
        )
        return None


def deliver_invoice_email(delivery_id):
    """Send one invoice email and record the outcome.

    Returns True if sent, False if the send failed, and None if the delivery
    was already sent or is being handled by another process.
    """
    with transaction.atomic():
        delivery = (
            InvoiceDelivery.objects.select_for_update(of=('self',), skip_locked=True)
            .select_related('invoice__company', 'invoice__freelancer')
            .exclude(status=InvoiceDelivery.STATUS_SENT)
            .filter(pk=delivery_id)
            .first()
        )
        if delivery is None:
            return None

        delivery.attempts += 1
        subject, body = render_invoice_email(delivery.invoice)
        try:
            send_mail(subject, body, None, [delivery.email])
        except Exception as exc:
            logger.exception('Failed to send invoice email for delivery %s', delivery.pk)
            delivery.status = InvoiceDelivery.STATUS_FAILED
            delivery.last_error = f'{type(exc).__name__}: {exc}'
        else:
            delivery.status = InvoiceDelivery.STATUS_SENT
            delivery.sent_at = timezone.now()
            delivery.last_error = ''
        delivery.save()
        return delivery.status == InvoiceDelivery.STATUS_SENT


def render_invoice_email(invoice):
    """Plain-text stand-in for the real invoice document (PDF / e-invoice)."""
    period_label = f'{invoice.period:%B %Y}'
    subject = (
        f'Invoice {invoice.number}: {invoice.freelancer.name} for '
        f'{invoice.company.name}, {period_label}'
    )
    rows = [
        f'{line.date:%Y-%m-%d}  {line.hours:>6}h  @ £{line.daily_rate}/day  £{line.amount:>10}'
        for line in invoice.lines.all()
    ]
    body = '\n'.join([
        f'Invoice {invoice.number}',
        f'Period: {period_label}',
        f'Bill to: {invoice.company.name} <{invoice.company.billing_email}>',
        f'Freelancer: {invoice.freelancer.name}',
        '',
        *rows,
        '',
        f'Total due: £{invoice.total}',
        '',
        f'Amounts are pro rata against a working day of {HOURS_PER_DAY} hours.',
    ])
    return subject, body
