"""
Formation Permissions — role-based access control.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrReadOnly(BasePermission):
    """
    Admin users get full CRUD access.
    Everyone else gets read-only access to published/catalog content.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_admin


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level: user can access only their own resources.
    Admins can access everything.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_admin:
            return True
        # Check for a 'user' FK or an 'enrollment.user' FK
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        if hasattr(obj, 'enrollment') and obj.enrollment.user == request.user:
            return True
        return False


class IsEnrolledStudent(BasePermission):
    """
    Ensures the requesting user has an active enrollment for the
    resource's parent course.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_admin:
            return True
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        if hasattr(obj, 'enrollment') and obj.enrollment.user == request.user:
            return True
        return False
