"""Centralised MODEZA permission enforcement.

Every admin UI page, every DRF admin endpoint and every template snippet
must go through these helpers so that checks are consistent, fail-closed and
immediately responsive to deactivation.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import render

from audit.services import AuditLogService

from .models import Permission, Role, StaffProfile
from .permissions_catalog import resolve_dependencies

ADMIN_LOGIN_URL = "admin-login"


# ---------------------------------------------------------------------------
# Core checks
# ---------------------------------------------------------------------------

def _has_profile_access(user):
    profile = getattr(user, "staff_profile", None)
    if profile is None:
        # A staff user without a managed profile is fail-closed unless they
        # are a Django superuser (keeps the bootstrap path intact).
        return bool(user.is_superuser)
    return profile.status == StaffProfile.Status.ACTIVE


def has_staff_access(user):
    """Boolean gate: does this user currently have any admin access at all?"""
    if user is None or not user.is_authenticated:
        return False
    if not getattr(user, "is_active", False):
        return False
    if not getattr(user, "is_staff", False):
        return False
    return _has_profile_access(user)


def effective_permissions(user):
    """Return the sorted set of permission codes the user currently holds.

    Superusers bypass to the full permission set. Inactive staff members
    receive nothing, which makes deactivation effective immediately.
    """
    if user is None or not user.is_authenticated:
        return set()
    if user.is_superuser:
        if not getattr(user, "is_active", False):
            return set()
        return set(Permission.objects.values_list("code", flat=True))
    if not has_staff_access(user):
        return set()
    profile = getattr(user, "staff_profile", None)
    if profile is None:
        return set()
    return profile.effective_permission_codes()


def user_has_permission(user, code):
    """Fail-closed check for a single permission code."""
    try:
        if code not in effective_permissions(user):
            return False
        if user.is_superuser:
            return True
        return _has_profile_access(user)
    except Exception:
        return False


def user_has_all_permissions(user, codes):
    return all(user_has_permission(user, code) for code in codes)


def require_permission(user, code):
    if not user_has_permission(user, code):
        raise PermissionDenied("Missing permission: %s" % code)


def is_super_admin(user):
    """Elevated check for super-admin only operations."""
    if user is None or not user.is_authenticated:
        return False
    if not has_staff_access(user):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "staff_profile", None)
    return bool(profile and profile.roles.filter(is_superadmin=True).exists())


def can_assign_sensitive_permissions(user):
    """True for Super Admins: Django superusers or holders of a Super Admin role."""
    return is_super_admin(user)


# ---------------------------------------------------------------------------
# Super admin protection
# ---------------------------------------------------------------------------

def active_super_admin_count():
    return get_user_model().objects.filter(
        is_superuser=True, is_active=True).count()


def would_leave_no_active_super_admin(user):
    """True if making ``user`` inactive/demoted would leave zero super admins."""
    if not user.is_superuser or not user.is_active:
        return False
    count = active_super_admin_count()
    if count <= 1:
        return True
    return False


# ---------------------------------------------------------------------------
# DRF-oriented convenience (used by admin_api tests / endpoints)
# ---------------------------------------------------------------------------

def profile_has_permission(user, code, require_active=True):
    if user.is_superuser:
        return True
    if require_active and not has_staff_access(user):
        return False
    return code in effective_permissions(user)


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def audit_staff_event(action, actor, target_user, description, metadata, result="success"):
    AuditLogService.log(
        action=action,
        actor=actor,
        category="staff",
        object_type="user",
        object_id=target_user.pk,
        object_repr=target_user.get_full_name() or target_user.username,
        description=description,
        metadata=metadata,
        result=result,
    )


def audit_role_event(action, actor, role, description, metadata, result="success"):
    AuditLogService.log(
        action=action,
        actor=actor,
        category="roles",
        object_type="role",
        object_id=str(role.pk),
        object_repr=role.name,
        description=description,
        metadata=metadata,
        result=result,
    )


def role_readiness_issues(role, assigned_permissions_codes):
    """Return a list of human-readable warnings for a role permission set.

    This is the operator-facing verification that role bundles are never
    granted without their required permissions.
    """
    codes = set(assigned_permissions_codes)
    issues = []
    for code in sorted(codes):
        perms = Permission.objects.filter(code=code).first()
        if not perms:
            continue
        for req in (perms.requires or []):
            if req not in codes:
                issues.append(
                    f"{code} requires '{req}' which is not included. "
                    f"Selecting {req} automatically.")
    return issues


def expand_with_dependencies(codes):
    known = {p.code for p in Permission.objects.all()}
    return [c for c in resolve_dependencies([c for c in codes if c in known])]


# ---------------------------------------------------------------------------
# Django view protection primitives
# ---------------------------------------------------------------------------

def _denied_response(request, context=None):
    payload = {
        "page_title": "Access denied",
        "page_subtitle": "You don't have permission to access this page.",
        "title": "Access denied",
        "description": "You don't have permission to access this page. "
                       "Ask a Super Admin to grant you the required permission.",
    }
    if context:
        payload.update(context)
    return render(request, "admin_ui/access_denied.html", payload, status=403)


access_denied_response = _denied_response


def permission_required(*codes):
    """Class decorator that wraps ``View.dispatch``.

    Applied *after* a class is defined it wraps any ``@method_decorator``
    wrapped ``dispatch`` so anonymous users still get the login redirect while
    authenticated-but-unauthorized staff get a 403.
    """
    def decorator(view_cls):
        original_dispatch = view_cls.dispatch

        def dispatch(self, request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(
                    request.get_full_path(), login_url=ADMIN_LOGIN_URL)
            if not user_has_all_permissions(request.user, codes):
                return _denied_response(request)
            return original_dispatch(self, request, *args, **kwargs)

        view_cls.dispatch = dispatch
        return view_cls

    return decorator


def super_admin_required(view_cls):
    """Restrict a class-based view to active Super Admins only."""
    original_dispatch = view_cls.dispatch

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), login_url=ADMIN_LOGIN_URL)
        if not is_super_admin(request.user):
            return _denied_response(request)
        return original_dispatch(self, request, *args, **kwargs)

    view_cls.dispatch = dispatch
    return view_cls


class StaffPermissionRequiredMixin:
    """Mixin for access_control views: active staff + one permission code."""

    permission_required = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), login_url=ADMIN_LOGIN_URL)
        if not has_staff_access(request.user):
            return _denied_response(request)
        if not is_super_admin(request.user):
            return _denied_response(request)
        if self.permission_required and not user_has_permission(
                request.user, self.permission_required):
            return _denied_response(request)
        return super().dispatch(request, *args, **kwargs)


def staff_directory_stats():
    """Small stats block used on the staff index page."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return {
        "total_staff": User.objects.filter(is_staff=True).count(),
        "active_staff": User.objects.filter(is_staff=True, is_active=True).count(),
        "total_roles": Role.objects.count(),
        "super_admins": User.objects.filter(is_superuser=True, is_active=True).count(),
        "active_super_admins": active_super_admin_count(),
        "staff_by_role": (
            StaffProfile.objects
            .exclude(roles__isnull=True)
            .values("roles__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        ),
    }
