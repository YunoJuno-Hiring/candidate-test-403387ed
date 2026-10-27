import datetime
import smtplib
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core import mail

from accounts.models import Freelancer
from billing import services
from billing.models import Invoice, InvoiceDelivery, InvoiceLine
from billing.services import line_amount, run_billing
from contracts.models import Contract, TimesheetEntry

APRIL = datetime.date(2026, 4, 1)


def _entry(contract, day, hours='8.0', status='approved'):
    return TimesheetEntry.objects.create(
        contract=contract,
        date=datetime.date(2026, 4, day),
        hours=Decimal(hours),
        status=status,
    )


@pytest.fixture
def april_entries(active_contract):
    return [
        _entry(active_contract, 6),
        _entry(active_contract, 7, hours='7.5'),
    ]


def test_line_amount_is_pro_rata_on_an_eight_hour_day():
    assert line_amount(Decimal('8'), Decimal('600.00')) == Decimal('600.00')
    assert line_amount(Decimal('7.5'), Decimal('600.00')) == Decimal('562.50')
    assert line_amount(Decimal('1'), Decimal('333.33')) == Decimal('41.67')


@pytest.mark.django_db
def test_run_invoices_only_approved_entries_in_the_month(active_contract, april_entries):
    _entry(active_contract, 8, status='submitted')
    _entry(active_contract, 9, status='rejected')
    TimesheetEntry.objects.create(
        contract=active_contract, date=datetime.date(2026, 5, 1), hours=Decimal('8'), status='approved'
    )

    run = run_billing(APRIL, company=active_contract.company)

    assert run.invoices.count() == 1
    invoice = Invoice.objects.get()
    assert invoice.company == active_contract.company
    assert invoice.freelancer == active_contract.freelancer
    assert invoice.total == Decimal('1162.50')
    assert {line.timesheet_entry for line in invoice.lines.all()} == set(april_entries)


@pytest.mark.django_db
def test_run_creates_one_invoice_per_freelancer(active_contract, april_entries):
    other_user = User.objects.create_user(username='other@test.test', email='other@test.test', password='x')
    other_freelancer = Freelancer.objects.create(user=other_user, name='Other Freelancer')
    second_contract = Contract.objects.create(
        company=active_contract.company,
        freelancer=other_freelancer,
        daily_rate=Decimal('400.00'),
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 12, 31),
    )
    _entry(second_contract, 6)

    run = run_billing(APRIL, company=active_contract.company)

    assert run.invoices.count() == 2
    assert Invoice.objects.get(freelancer=other_freelancer).total == Decimal('400.00')


@pytest.mark.django_db
def test_run_only_bills_the_given_company(active_contract, other_contract, april_entries):
    _entry(other_contract, 6)

    run_billing(APRIL, company=active_contract.company)

    assert list(Invoice.objects.values_list('company', flat=True)) == [active_contract.company_id]


@pytest.mark.django_db
def test_invoice_lines_snapshot_the_contract_rate(active_contract, april_entries):
    run_billing(APRIL, company=active_contract.company)
    active_contract.daily_rate = Decimal('900.00')
    active_contract.save()

    invoice = Invoice.objects.get()
    assert invoice.total == Decimal('1162.50')
    assert set(invoice.lines.values_list('daily_rate', flat=True)) == {Decimal('600.00')}


@pytest.mark.django_db
def test_run_emails_the_company_and_the_freelancer(active_contract, april_entries):
    run = run_billing(APRIL, company=active_contract.company)

    assert run.emails_sent == 2
    assert sorted(m.to[0] for m in mail.outbox) == ['billing@northstar.test', 'freelancer@test.test']
    invoice = Invoice.objects.get()
    assert invoice.number in mail.outbox[0].subject
    assert '£1162.50' in mail.outbox[0].body
    assert set(invoice.deliveries.values_list('status', flat=True)) == {InvoiceDelivery.STATUS_SENT}


@pytest.mark.django_db
def test_rerunning_a_month_is_idempotent(active_contract, april_entries):
    run_billing(APRIL, company=active_contract.company)
    mail.outbox.clear()

    rerun = run_billing(APRIL, company=active_contract.company)

    assert rerun.invoices.count() == 0
    assert rerun.emails_sent == 0
    assert Invoice.objects.count() == 1
    assert InvoiceLine.objects.count() == 2
    assert mail.outbox == []


@pytest.mark.django_db
def test_failed_email_keeps_the_invoice_and_is_retried_on_rerun(monkeypatch, active_contract, april_entries):
    real_send_mail = services.send_mail

    def send_mail_failing_for_freelancer(subject, body, from_email, recipients):
        if recipients == ['freelancer@test.test']:
            raise smtplib.SMTPServerDisconnected('Connection unexpectedly closed')
        return real_send_mail(subject, body, from_email, recipients)

    monkeypatch.setattr(services, 'send_mail', send_mail_failing_for_freelancer)
    run = run_billing(APRIL, company=active_contract.company)

    assert run.invoices.count() == 1
    assert (run.emails_sent, run.emails_failed) == (1, 1)
    failed = InvoiceDelivery.objects.get(recipient=InvoiceDelivery.RECIPIENT_FREELANCER)
    assert failed.status == InvoiceDelivery.STATUS_FAILED
    assert failed.attempts == 1
    assert 'SMTPServerDisconnected' in failed.last_error

    monkeypatch.setattr(services, 'send_mail', real_send_mail)
    mail.outbox.clear()
    rerun = run_billing(APRIL, company=active_contract.company)

    # Only the failed recipient is retried; the company isn't emailed twice.
    assert (rerun.invoices.count(), rerun.emails_sent, rerun.emails_failed) == (0, 1, 0)
    assert [m.to for m in mail.outbox] == [['freelancer@test.test']]
    failed.refresh_from_db()
    assert failed.status == InvoiceDelivery.STATUS_SENT
    assert failed.attempts == 2
    assert failed.last_error == ''


@pytest.mark.django_db
def test_entries_approved_after_the_invoice_are_not_added_to_it(active_contract, april_entries):
    run_billing(APRIL, company=active_contract.company)
    _entry(active_contract, 20)

    rerun = run_billing(APRIL, company=active_contract.company)

    assert rerun.invoices.count() == 0
    assert Invoice.objects.get().lines.count() == 2


@pytest.mark.django_db
def test_month_with_nothing_approved_generates_no_invoices(active_contract):
    _entry(active_contract, 6, status='submitted')

    run = run_billing(APRIL, company=active_contract.company)

    assert run.invoices.count() == 0
    assert not Invoice.objects.exists()
    assert mail.outbox == []
