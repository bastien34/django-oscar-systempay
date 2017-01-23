from decimal import Decimal as D
from urllib.parse import urlencode
import logging

from django.conf import settings
from django.http import QueryDict
from django.utils.translation import ugettext_lazy as _

from . import gateway
from .models import SystemPayTransaction
from .utils import printable_form_errors
from .exceptions import (
    SystemPayGatewayServerError, SystemPayGatewayParamError,
    SystemPayGatewayPaymentRejected, SystemPayFormNotValid)


logger = logging.getLogger('systempay')


class Facade(object):
    """
    A bridge between oscar's objects and the core gateway object.
    """

    def __init__(self):
        self.gateway = gateway.Gateway(
            settings.SYSTEMPAY_SANDBOX_MODE,
            settings.SYSTEMPAY_SITE_ID,
            settings.SYSTEMPAY_CERTIFICATE,
            getattr(settings, 'SYSTEMPAY_ACTION_MODE', 'INTERACTIVE'),
        )
        self.currency = getattr(settings, 'SYSTEMPAY_CURRENCY', 978)  # 978
        # stands for EURO (ISO 639-1)

    def get_order_number(self, form):
        return form.data.get('vads_order_id')

    def get_total_incl_tax(self, form):
        return D(int(form.data.get('vads_amount', '0'))/100.0)

    def get_result(self, form):
        return form.data.get('vads_result')

    def get_extra_result(self, form):
        return form.data.get('vads_extra_result')

    def get_auth_result(self, form):
        return form.data.get('vads_auth_result')

    def get_submit_form_populated_with_order(self, order, **kwargs):
        """
        Pre-populate the submit form with order data

        :order: an oscar order instance
        :kwargs: additional data, check the fields of the `SystemPaySubmitForm`
        class to see all possible values.
        """
        params = dict()

        params['vads_order_id'] = order.number

        if order.user:
            params['vads_cust_name'] = order.user.get_full_name()
            params['vads_cust_email'] = order.user.email
            params['vads_cust_id'] = order.user.pk

        if order.billing_address:
            params['vads_cust_title'] = order.billing_address.title or ""
            params['vads_cust_address'] = order.billing_address.line1 or ""
            params['vads_cust_city'] = order.billing_address.city or ""
            params['vads_cust_state'] = order.billing_address.state or ""
            params['vads_cust_zip'] = order.billing_address.postcode or ""
            params['vads_cust_country'] = order.billing_address.country.\
                iso_3166_1_a2

        if order.shipping_address:
            params['vads_ship_to_name'] = order.shipping_address.salutation
            params['vads_ship_to_street'] = order.shipping_address.line1 or ""
            params['vads_ship_to_street2'] = order.shipping_address.line2 or ""
            params['vads_ship_to_city'] = order.shipping_address.city or ""
            params['vads_ship_to_state'] = order.shipping_address.state or ""
            params['vads_ship_to_zip'] = order.shipping_address.postcode or ""
            params['vads_ship_to_country'] = order.shipping_address.country.\
                iso_3166_1_a2

        params.update(kwargs)

        form = self.gateway.get_submit_form(
            order.total_incl_tax,
            **params
        )
        self.gateway.sign(form)
        return form

    def get_return_form_populated_with_request(self, request, **kwargs):
        """
        Pre-populate the return form with the current request
        """
        return self.gateway.get_return_form(
            **dict((k, request.POST.get(k)) for k in request.POST))

    def handle_request(self, request):
        """
        Handle the income request which can have two different forms:

            1. user coming back on the store after clicking on a "go back to
            store" button

            OR

            2. a notification of payment issued from SystemPay server to
            our server

        In both cases the data will be POST data, the only difference is
        that in the case 2. the POST data will contain a ``hash`` parameter
        that needs to be include in the signature computation.
        """
        form = self.get_return_form_populated_with_request(request)

        # create the transaction record, before saving the source payment
        order_number = self.get_order_number(form)
        total_incl_tax = self.get_total_incl_tax(form)
        txn = self.save_txn_notification(order_number, total_incl_tax, request)

        if not form.is_valid():
            txn.error_message = printable_form_errors(form)
            txn.save()
            msg = _("The data received are not complete: %s. See the "
                    "transaction record #%s for more details") % (
                printable_form_errors(form),
                txn.id,
            )
            raise SystemPayFormNotValid(msg)

        if not self.gateway.is_signature_valid(form):
            txn.error_message = \
                _("Signature not valid. Get '%s' instead of '%s'") % (
                    form.cleaned_data['signature'],
                    self.gateway.compute_signature(form)
                )
            txn.save()
            raise SystemPayFormNotValid(
                _("Incorrect signature. Check SystemPayTransaction #%s "
                  "for more details") % txn.id)

        if not txn.is_complete():

            if txn.result == '02':
                raise SystemPayGatewayPaymentRejected(
                    "The shop must contact the bank")
            elif txn.result == '05':
                raise SystemPayGatewayPaymentRejected(
                    "The payment has been rejected")
            elif txn.result == '30':
                extra_result = self.get_extra_result(form)
                raise SystemPayGatewayParamError(code=extra_result)
            elif txn.result == '96':
                raise SystemPayGatewayServerError(
                    "Technical error while processing the payment")
            elif txn.result == '17':
                raise
            else:
                raise SystemPayGatewayServerError(
                    "Unknown error: %s" % txn.result)

        return txn

    def save_submit_txn(self, order_number, amount, form):
        """
        Save submitted transaction into the database.
        """
        return self.save_txn(order_number, amount, form.data,
                             SystemPayTransaction.MODE_SUBMIT)

    def save_txn_notification(self, order_number, amount, request):
        """
        Save notification transaction into the database.
        """
        return self.save_txn(order_number, amount, request.POST.copy(),
                             SystemPayTransaction.MODE_RETURN)

    def save_txn(self, order_number, amount, data, mode):
        """
        Save the transaction into the database to be able to track
        everything we received.
        """
        # convert the QueryDict into a dict
        d = {}
        if isinstance(data, QueryDict):
            for k in data:
                d[k] = data.get(k)
        else:
            d.update(data)

        return SystemPayTransaction.objects.create(
            mode=mode,
            operation_type=d.get('vads_operation_type'),
            trans_id=d.get('vads_trans_id'),
            trans_date=d.get('vads_trans_date'),
            order_number=order_number,
            amount=amount,
            auth_result=d.get('vads_auth_result'),
            result=d.get('vads_result'),
            raw_request=urlencode(d)
        )
