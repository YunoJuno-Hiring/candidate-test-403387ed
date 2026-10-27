import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from billing.models import Invoice
from billing.services import run_billing
from contracts.models import TimesheetEntry

APRIL = datetime.date(2026, 4, 1)


@pytest.fixture
def approved_entry(active_contract):
    return TimesheetEntry.objects.create(
        contract=active_contract, date=datetime.date(2026, 4, 6), hours=Decimal('8'), status='approved'
    )


@pytest.fixture
def other_company_invoice(other_contract):
    TimesheetEntry.objects.create(
        contract=other_contract, date=datetime.date(2026, 4, 6), hours=Decimal('8'), status='approved'
    )
    run_billing(APRIL, company=other_contract.company)
    return Invoice.objects.get(company=other_contract.company)


@pytest.mark.django_db
def test_admin_can_run_billing(admin_client, approved_entry):
    resp = admin_client.post('/api/billing/runs/', {'month': '2026-04'}, format='json')

    assert resp.status_code == 201
    assert resp.data['status'] == 'completed'
    assert resp.data['month'] == '2026-04'
    assert resp.data['invoices_generated'] == 1
    assert resp.data['emails_sent'] == 2
    assert resp.data['run_id']


@pytest.mark.django_db
def test_admin_run_only_bills_their_own_company(admin_client, approved_entry, other_contract):
    TimesheetEntry.objects.create(
        contract=other_contract, date=datetime.date(2026, 4, 6), hours=Decimal('8'), status='approved'
    )

    admin_client.post('/api/billing/runs/', {'month': '2026-04'}, format='json')

    assert list(Invoice.objects.values_list('company', flat=True)) == [approved_entry.contract.company_id]


@pytest.mark.django_db
def test_freelancer_cannot_run_billing(freelancer_client):
    resp = freelancer_client.post('/api/billing/runs/', {'month': '2026-04'}, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize('month', [None, '', '2026-13', 'April', '2026-04-01'])
def test_run_rejects_invalid_month(admin_client, month):
    resp = admin_client.post('/api/billing/runs/', {'month': month}, format='json')
    assert resp.status_code == 400
    assert 'month' in resp.data


@pytest.mark.django_db
def test_run_rejects_a_month_that_has_not_ended(admin_client):
    this_month = timezone.localdate().strftime('%Y-%m')
    resp = admin_client.post('/api/billing/runs/', {'month': this_month}, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_invoice_list_is_scoped_to_the_admins_company(admin_client, approved_entry, other_company_invoice):
    run_billing(APRIL, company=approved_entry.contract.company)

    resp = admin_client.get('/api/invoices/?month=2026-04')

    assert resp.status_code == 200
    assert [inv['company']['id'] for inv in resp.data] == [approved_entry.contract.company_id]
    assert resp.data[0]['total'] == '600.00'
    assert resp.data[0]['month'] == '2026-04'
    assert len(resp.data[0]['deliveries']) == 2


@pytest.mark.django_db
def test_invoice_list_filters_by_month(admin_client, approved_entry):
    run_billing(APRIL, company=approved_entry.contract.company)

    assert len(admin_client.get('/api/invoices/?month=2026-04').data) == 1
    assert admin_client.get('/api/invoices/?month=2026-03').data == []
    assert admin_client.get('/api/invoices/?month=nope').status_code == 400


@pytest.mark.django_db
def test_invoice_detail_includes_lines(admin_client, approved_entry):
    run_billing(APRIL, company=approved_entry.contract.company)
    invoice = Invoice.objects.get()

    resp = admin_client.get(f'/api/invoices/{invoice.id}/')

    assert resp.status_code == 200
    assert resp.data['number'] == invoice.number
    assert [line['timesheet_entry'] for line in resp.data['lines']] == [approved_entry.id]
    assert resp.data['lines'][0]['amount'] == '600.00'


@pytest.mark.django_db
def test_admin_cannot_see_another_companys_invoice(admin_client, other_company_invoice):
    resp = admin_client.get(f'/api/invoices/{other_company_invoice.id}/')
    assert resp.status_code == 404


@pytest.mark.django_db
def test_freelancer_sees_their_own_invoices(freelancer_client, approved_entry, other_company_invoice):
    run_billing(APRIL, company=approved_entry.contract.company)

    resp = freelancer_client.get('/api/invoices/')

    assert resp.status_code == 200
    assert len(resp.data) == 2


@pytest.mark.django_db
def test_freelancer_cannot_see_another_freelancers_invoice(approved_entry):
    from django.contrib.auth.models import User
    from accounts.models import Freelancer

    run_billing(APRIL, company=approved_entry.contract.company)
    other = User.objects.create_user(username='other@test.test', email='other@test.test', password='x')
    Freelancer.objects.create(user=other, name='Other')
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=other).key}')

    resp = client.get(f'/api/invoices/{Invoice.objects.get().id}/')

    assert resp.status_code == 404


@pytest.mark.django_db
def test_invoiced_entry_can_no_longer_be_changed(admin_client, approved_entry):
    run_billing(APRIL, company=approved_entry.contract.company)

    resp = admin_client.patch(f'/api/timesheets/{approved_entry.id}/', {'status': 'rejected', 'rejection_reason': 'x'})

    assert resp.status_code == 409
    approved_entry.refresh_from_db()
    assert approved_entry.status == 'approved'
