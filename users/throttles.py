"""
Throttles for the authentication endpoints.

DRF's stock throttles count requests per client IP. That is not enough for
login: an attacker who rotates IP addresses can keep guessing the password of
one account. ``LoginEmailThrottle`` counts attempts per *target e-mail*, so the
limit holds whatever address the requests come from.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class LoginEmailThrottle(SimpleRateThrottle):
    """Limit login attempts against a single account, whatever the client IP."""

    scope = 'auth_login_email'

    def get_cache_key(self, request, view):
        email = request.data.get('email') if hasattr(request.data, 'get') else None
        if not isinstance(email, str) or not email.strip():
            return None  # nothing to key on — the serializer rejects the request
        ident = hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': ident}
