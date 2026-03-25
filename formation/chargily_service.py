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


def get_webhook_base_url():
    """Use NGROK_URL for webhooks if available, otherwise localhost."""
    return settings.NGROK_URL or 'http://localhost:8000'


def create_chargily_checkout(order, payment_method='edahabia', course_slug=''):
    """
    Create a Chargily Pay checkout for an order.

    Returns:
        tuple: (chargily_checkout_id, checkout_url)
    """
    base_url = get_webhook_base_url()

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
