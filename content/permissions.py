"""
Landing Page CMS Permissions

Role-based access control for CMS endpoints:
- SUPER_ADMIN: Full access (CRUD all content)
- ADMIN: Full access (CRUD all content)  
- USER: Read-only access to public endpoints
- Anonymous: Read-only access to public endpoints

Uses the custom User model's role field from users.models.UserRole
"""

from rest_framework import permissions


# =============================================================================
# PERMISSION CLASSES
# =============================================================================

class IsAdminOrSuperAdmin(permissions.BasePermission):
    """
    Permission for admin-only endpoints.
    Only ADMIN and SUPER_ADMIN roles can access.
    """
    message = "Only administrators can perform this action."
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Use the is_admin property from our custom User model
        if hasattr(request.user, 'is_admin'):
            return request.user.is_admin
        
        # Fallback: Check Django's is_staff or is_superuser
        return request.user.is_superuser or request.user.is_staff
    
    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Permission that allows:
    - GET, HEAD, OPTIONS: Anyone (including anonymous)
    - POST, PUT, PATCH, DELETE: Only ADMIN/SUPER_ADMIN
    """
    message = "Only administrators can modify content."
    
    def has_permission(self, request, view):
        # Safe methods are allowed for anyone
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Unsafe methods require admin role
        if not request.user or not request.user.is_authenticated:
            return False
        
        if hasattr(request.user, 'is_admin'):
            return request.user.is_admin
        
        return request.user.is_superuser or request.user.is_staff


class IsAuthenticatedReadOnly(permissions.BasePermission):
    """
    Permission for authenticated users to read.
    Used for semi-private content.
    """
    message = "Authentication required."
    
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return False


class PublicReadOnly(permissions.BasePermission):
    """
    Permission for public read-only endpoints.
    Anyone can access (including anonymous users).
    """
    
    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_admin(user):
    """Check if user has admin privileges."""
    if not user or not user.is_authenticated:
        return False
    
    if hasattr(user, 'is_admin'):
        return user.is_admin
    
    return user.is_superuser or user.is_staff
