from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsManagerOrAdmin(BasePermission):
    """
    Allows access only to users with SystemRole.is_staff_level=True.
    Replacement for the hardcoded SALES_MANAGER/ADMIN checks.
    """
    message = "Access restricted to RailTech managers and administrators."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        return user.is_manager_or_admin


class IsAdminUser(BasePermission):
    """
    Allows access only to users with ADMIN code in SystemRole.
    """
    message = "Access restricted to super administrators."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if user.is_superuser:
            return True

        if hasattr(user, 'role') and user.role:
            return user.role.code == 'ADMIN'

        return False


class IsAdminOrReadOnly(BasePermission):
    """
    Allow read-only for anyone, write only for Admins.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        if not (user and user.is_authenticated):
            return False

        if user.is_superuser:
            return True

        if hasattr(user, 'role') and user.role:
            return user.role.code == 'ADMIN'

        return False


class IsOwnerOrManagerOrAdmin(BasePermission):
    """
    Object-level permission.
    - Admins/Managers: full access based on is_staff_level.
    - Clients: access only to their own objects.
    """
    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        # 1. Staff/Manager check (RailTech employees have full access)
        if user.is_superuser or user.is_manager_or_admin:
            return True

        # 2. B2B Multi-tenancy check
        # Get the target company for the object
        target_company = None

        if hasattr(obj, 'company'):  # Deal
            target_company = obj.company
        elif hasattr(obj, 'deal'):  # Quote, Message
            target_company = obj.deal.company
        elif hasattr(obj, 'quote'):  # QuoteItem
            target_company = obj.quote.deal.company
        elif obj == user:  # User profile
            return True

        if target_company:
            # Check if user is an active member of the target company
            return user.memberships.filter(company=target_company, is_active=True).exists()

        return False
