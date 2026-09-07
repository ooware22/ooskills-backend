"""
Shared role-based permission classes.

These live in ``users`` because authorization is a property of the user's role,
and both ``formation`` and ``gamefication`` need the same rules. This mirrors
the pattern the ``content`` app already established (``IsAdminOrSuperAdmin``),
promoted here so every app enforces admin access the same way.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


def _is_admin(user) -> bool:
    """True only for authenticated ADMIN / SUPER_ADMIN users."""
    if not user or not user.is_authenticated:
        return False
    if hasattr(user, 'is_admin'):
        return user.is_admin
    # Fallback for the stock Django user (e.g. shell-created superusers).
    return bool(getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False))


class IsAdmin(BasePermission):
    """Deny-by-default: only ADMIN / SUPER_ADMIN may access, for every method."""

    message = 'Administrator privileges are required for this action.'

    def has_permission(self, request, view):
        return _is_admin(request.user)

    def has_object_permission(self, request, view, obj):
        return _is_admin(request.user)


class IsAdminOrAuthenticatedReadOnly(BasePermission):
    """
    Authenticated users get read-only access; writes require an admin.

    Unlike the older ``formation.IsAdminOrReadOnly``, anonymous users get
    *nothing* — safe methods still require authentication. Use this for
    resources that logged-in users may read but only admins may change.
    """

    message = 'Administrator privileges are required to modify this resource.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return _is_admin(request.user)
