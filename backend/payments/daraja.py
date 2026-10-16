"""Server-side Safaricom Daraja STK Push client and response validation."""
import base64
import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger('payments')


class DarajaError(Exception):
    """Safe provider error; never includes credentials or response bodies."""

    def __init__(self, code, message):
        self.code = str(code)[:80]
        self.message = str(message)[:240]
        super().__init__(self.message)


def normalize_ke_phone(value):
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('0') and len(digits) == 10:
        digits = '254' + digits[1:]
    elif digits.startswith('7') and len(digits) == 9:
        digits = '254' + digits
    elif digits.startswith('254') and len(digits) == 12:
        pass
    else:
        raise DarajaError('INVALID_PHONE', 'Enter a valid Kenyan mobile number.')
    if not re.fullmatch(r'254(?:7\d{8}|1\d{8})', digits):
        raise DarajaError('INVALID_PHONE', 'Enter a valid Kenyan mobile number.')
    return digits


def _config():
    required = ('MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET', 'MPESA_SHORTCODE',
                'MPESA_PASSKEY', 'MPESA_CALLBACK_URL')
    missing = [name for name in required if not getattr(settings, name, '')]
    if missing:
        raise ImproperlyConfigured('M-Pesa is not configured. Missing: ' + ', '.join(missing))
    if not settings.MPESA_CALLBACK_URL.startswith('https://'):
        raise ImproperlyConfigured('MPESA_CALLBACK_URL must be a publicly reachable HTTPS URL.')
    environment = getattr(settings, 'MPESA_ENVIRONMENT', 'sandbox')
    if environment not in {'sandbox', 'production'}:
        raise ImproperlyConfigured('MPESA_ENVIRONMENT must be sandbox or production.')
    if getattr(settings, 'MPESA_TRANSACTION_TYPE', 'CustomerPayBillOnline') not in {
        'CustomerPayBillOnline', 'CustomerBuyGoodsOnline',
    }:
        raise ImproperlyConfigured('MPESA_TRANSACTION_TYPE must be CustomerPayBillOnline or CustomerBuyGoodsOnline.')
    root = 'https://sandbox.safaricom.co.ke' if environment == 'sandbox' else 'https://api.safaricom.co.ke'
    return root


def _request_json(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=(4, 12), **kwargs)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Daraja request failed (%s).', type(exc).__name__)
        raise DarajaError('PROVIDER_UNAVAILABLE', 'M-Pesa could not be reached. Please retry shortly.') from exc
    if not isinstance(data, dict):
        raise DarajaError('INVALID_PROVIDER_RESPONSE', 'M-Pesa returned an unexpected response.')
    return data


def access_token():
    root = _config()
    response = _request_json(
        'GET', f'{root}/oauth/v1/generate?grant_type=client_credentials',
        auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET),
    )
    token = response.get('access_token')
    if not token:
        logger.warning('Daraja OAuth response omitted access_token.')
        raise DarajaError('AUTH_FAILED', 'M-Pesa authentication failed. Check the Daraja credentials.')
    return token


def initiate_stk_push(phone, amount_minor, account_reference, description):
    root = _config()
    phone = normalize_ke_phone(phone)
    if int(amount_minor) % 100:
        raise DarajaError('INVALID_AMOUNT', 'M-Pesa payments must be a whole number of Kenyan shillings.')
    amount = int(amount_minor) // 100
    if amount <= 0 or amount > 150000:
        raise DarajaError('INVALID_AMOUNT', 'The order total is outside the supported M-Pesa range.')
    timestamp = datetime.now(timezone(timedelta(hours=3))).strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}'.encode()
    ).decode()
    body = {
        'BusinessShortCode': settings.MPESA_SHORTCODE,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': getattr(settings, 'MPESA_TRANSACTION_TYPE', 'CustomerPayBillOnline'),
        'Amount': amount,
        'PartyA': phone,
        'PartyB': settings.MPESA_SHORTCODE,
        'PhoneNumber': phone,
        'CallBackURL': settings.MPESA_CALLBACK_URL,
        'AccountReference': str(account_reference)[:12],
        'TransactionDesc': str(description)[:13],
    }
    response = _request_json(
        'POST', f'{root}/mpesa/stkpush/v1/processrequest',
        headers={'Authorization': f'Bearer {access_token()}'}, json=body,
    )
    if response.get('ResponseCode') != '0' or not response.get('CheckoutRequestID'):
        code = response.get('ResponseCode', 'STK_REJECTED')
        logger.info('Daraja STK request rejected (code=%s).', str(code)[:32])
        raise DarajaError(code, 'M-Pesa could not start the payment request. Please retry.')
    return response


def query_stk_status(checkout_request_id):
    root = _config()
    timestamp = datetime.now(timezone(timedelta(hours=3))).strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}'.encode()
    ).decode()
    response = _request_json(
        'POST', f'{root}/mpesa/stkpushquery/v1/query',
        headers={'Authorization': f'Bearer {access_token()}'},
        json={'BusinessShortCode': settings.MPESA_SHORTCODE, 'Password': password,
              'Timestamp': timestamp, 'CheckoutRequestID': checkout_request_id},
    )
    return response
