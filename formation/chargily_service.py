"""
Chargily Pay V2 service — creates checkouts and validates webhooks.
"""

from django.conf import settings
from chargily_pay import ChargilyClient
from chargily_pay.entity import Checkout

client = ChargilyClient(
    key=settings.CHARGILY_KEY,
    secret=settings.CHARGILY_SECRET,
    url=settings.CHARGILY_URL,
)


def _is_local_host(host: str) -> bool:
    host = (host or '').lower()
    return host.startswith('localhost') or host.startswith('127.0.0.1')


def _request_base_url(request) -> str:
    """Build backend base URL from the current request host.

    We force https for non-local hosts because payment providers require
    publicly reachable HTTPS webhook endpoints.
    """
    if not request:
        return ''
    host = request.get_host()
    if not host:
        return ''
    scheme = 'http' if _is_local_host(host) else 'https'
    return f'{scheme}://{host}'


def get_webhook_base_url(request=None):
    """Resolve webhook base URL with production-safe fallbacks.

    Priority:
    1) NGROK_URL (explicit local webhook tunneling)
    2) Current request host (works on Render/VPS)
    3) BACKEND_PUBLIC_URL env setting, if provided
    4) Render hostname, if present
    5) Localhost fallback for local dev
    """
    ngrok_url = (getattr(settings, 'NGROK_URL', '') or '').rstrip('/')
    if ngrok_url:
        return ngrok_url

    req_url = _request_base_url(request)
    if req_url:
        return req_url

    backend_public_url = (getattr(settings, 'BACKEND_PUBLIC_URL', '') or '').rstrip('/')
    if backend_public_url:
        return backend_public_url

    render_host = (getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', '') or '').strip()
    if render_host:
        return f'https://{render_host}'

    return 'http://localhost:8000'


def create_chargily_checkout(order, payment_method='edahabia', course_slug='', request=None):
    """
    Create a Chargily Pay checkout for an order.

    Returns:
        tuple: (chargily_checkout_id, checkout_url)
    """
    base_url = get_webhook_base_url(request=request)

    success_url = f"{settings.FRONTEND_URL}/payment/success?order={order.id}"
    if course_slug:
        success_url += f"&course={course_slug}"

    checkout = Checkout(
        amount=order.total,
        currency="dzd",
        success_url=success_url,
        failure_url=f"{settings.FRONTEND_URL}/payment/failure?order={order.id}",
        webhook_endpoint=f"{base_url}/api/formation/chargily/webhook/",
        payment_method=payment_method,
        description=f"OOSkills Order {order.id}",
        locale="fr",
        pass_fees_to_customer=False,
    )

    response = client.create_checkout(checkout=checkout)
    return response["id"], response["checkout_url"]
