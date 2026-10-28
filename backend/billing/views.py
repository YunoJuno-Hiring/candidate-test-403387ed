from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Invoice
from .serializers import BillingRunSerializer, InvoiceDetailSerializer, InvoiceSerializer
from .services import parse_period, run_billing


def _invoices_for(user):
    """Company admins see their company's invoices; freelancers see their own."""
    qs = Invoice.objects.select_related('company', 'freelancer').prefetch_related('deliveries')
    if hasattr(user, 'company_admin'):
        return qs.filter(company=user.company_admin.company)
    if hasattr(user, 'freelancer'):
        return qs.filter(freelancer=user.freelancer)
    return qs.none()


class BillingRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not hasattr(request.user, 'company_admin'):
            return Response(
                {'detail': 'Only company admins can run billing.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            period = parse_period(request.data.get('month'))
        except ValueError as exc:
            return Response({'month': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Invoices are one per month and never amended, so billing a month
        # before it has ended would leave the rest of its hours unbillable.
        if period >= timezone.localdate().replace(day=1):
            return Response(
                {'month': 'Only months that have already ended can be billed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        run = run_billing(
            period,
            company=request.user.company_admin.company,
            triggered_by=request.user,
        )
        return Response(BillingRunSerializer(run).data, status=status.HTTP_201_CREATED)


class InvoiceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _invoices_for(request.user)

        month_param = request.query_params.get('month')
        if month_param:
            try:
                qs = qs.filter(period=parse_period(month_param))
            except ValueError as exc:
                return Response({'month': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(InvoiceSerializer(qs, many=True).data)


class InvoiceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            invoice = _invoices_for(request.user).prefetch_related('lines').get(pk=pk)
        except Invoice.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvoiceDetailSerializer(invoice).data)
