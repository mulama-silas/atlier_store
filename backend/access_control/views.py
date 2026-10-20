from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit.models import AuditLog
from audit.services import AuditLogService

from .forms import RoleForm, StaffCreateForm, StaffEditForm, StaffSearchForm
from .models import Permission, Role, StaffProfile
from .permissions_catalog import GROUPS, sensitive_codes
from .services import (
    StaffPermissionRequiredMixin,
    active_super_admin_count,
    audit_role_event,
    audit_staff_event,
    can_assign_sensitive_permissions,
    expand_with_dependencies,
    has_staff_access,
    is_super_admin,
    permission_required,
    role_readiness_issues,
    staff_directory_stats,
    user_has_permission,
    would_leave_no_active_super_admin,
)

User = get_user_model()


def _page_context(request, page, title, subtitle):
    return {
        "admin_page": page,
        "page_title": title,
        "page_subtitle": subtitle,
    }


def _staff_profile(user):
    """Return the user's StaffProfile, or None when it does not exist yet.

    Staff accounts can be created outside of StaffCreateView (invite form,
    ``ensure_superuser``, Django admin), so the profile may be missing.
    ``user.staff_profile`` raises ``RelatedObjectDoesNotExist`` in that case,
    which subclasses ``AttributeError`` and is therefore swallowed by getattr.
    """
    return getattr(user, "staff_profile", None)


# ---------------------------------------------------------------------------
# Staff management
# ---------------------------------------------------------------------------

class StaffListView(StaffPermissionRequiredMixin, View):
    permission_required = "staff.view"
    template_name = "access_control/staff_list.html"

    def get(self, request):
        form = StaffSearchForm(request.GET)
        q = (request.GET.get("q") or "").strip()
        status = request.GET.get("status") or ""

        queryset = (User.objects
                    .filter(is_staff=True)
                    .select_related("staff_profile")
                    .prefetch_related("staff_profile__roles",
                                      "staff_profile__direct_permissions")
                    .order_by("username"))

        if q:
            queryset = queryset.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q))
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)

        context = _page_context(
            request, "staff", "Staff", "Manage MODEZA staff members and their access.")
        context.update({
            "staff_members": queryset,
            "search_form": form,
            "q": q,
            "status": status,
            "stats": staff_directory_stats(),
            "can_create": user_has_permission(request.user, "staff.create"),
            "can_edit": user_has_permission(request.user, "staff.update"),
            "can_deactivate": user_has_permission(request.user, "staff.deactivate"),
        })
        return render(request, self.template_name, context)


class StaffDetailView(StaffPermissionRequiredMixin, View):
    permission_required = "staff.view"
    template_name = "access_control/staff_detail.html"

    def get(self, request, user_id):
        user = get_object_or_404(
            User.objects.select_related("staff_profile").prefetch_related(
                "staff_profile__roles", "staff_profile__direct_permissions"),
            pk=user_id, is_staff=True)
        events = AuditLog.objects.filter(
            object_type="user",
            object_id=str(user.pk),
            action__in=[
                "staff_created", "staff_updated", "staff_deactivated",
                "staff_reactivated", "staff_role_changed",
                "permissions_granted", "permissions_revoked"],
        ).select_related("actor").order_by("-created_at")[:20]

        profile = _staff_profile(user)
        role_ids = set(profile.roles.values_list("pk", flat=True)) if profile else set()
        direct_ids = (set(profile.direct_permissions.values_list("pk", flat=True))
                      if profile else set())
        context = _page_context(
            request, "staff", user.get_full_name() or user.username,
            f"Staff detail · {user.username}")
        context.update({
            "staff_member": user,
            "profile": profile,
            "events": events,
            "is_self": user.pk == request.user.pk,
            "actor_is_super_admin": is_super_admin(request.user),
            "actor_assign": user_has_permission(request.user, "permissions.assign"),
            "can_edit": user_has_permission(request.user, "staff.update"),
            "can_deactivate": user_has_permission(request.user, "staff.deactivate"),
            "sensitive_permissions": sensitive_codes(),
            "role_ids": role_ids,
            "direct_permission_ids": direct_ids,
        })
        return render(request, self.template_name, context)


class StaffCreateView(StaffPermissionRequiredMixin, View):
    permission_required = "staff.create"
    template_name = "access_control/staff_form.html"

    def _selections(self, form):
        if form.is_bound:
            role_ids = {r for r in form.data.getlist("roles")}
            direct = set(form.data.getlist("direct_permissions"))
        else:
            role_ids = {str(r) for r in form.initial.get("roles", [])}
            direct = {str(p) for p in form.initial.get("direct_permissions", [])}
        direct_codes = set(Permission.objects.filter(
            pk__in=[d for d in direct if d.isdigit()]).values_list("code", flat=True))
        return role_ids, direct, direct_codes

    def _render_form(self, request, form):
        role_ids, direct, direct_codes = self._selections(form)
        context = _page_context(
            request, "staff", "Add Admin Account",
            "Create a staff login, then assign only the roles and permissions they need.")
        context.update({
            "form": form,
            "roles": Role.objects.all(),
            "selected_role_ids": role_ids,
            "selected_direct_ids": direct,
            "matrix": _role_matrix(direct_codes),
            "submit_label": "Create Admin Account",
            "mode": "create",
            "sensitive_permissions": sensitive_codes(),
        })
        return render(request, self.template_name, context)

    def get(self, request):
        return self._render_form(request, StaffCreateForm())

    def post(self, request):
        form = StaffCreateForm(request.POST)
        if not form.is_valid():
            return self._render_form(request, form)

        data = form.cleaned_data
        selected_roles = list(data["roles"])
        selected_permissions = list(data["direct_permissions"])

        if any(r.is_superadmin for r in selected_roles) or any(
                p.is_sensitive for p in selected_permissions):
            if not can_assign_sensitive_permissions(request.user):
                messages.error(
                    request,
                    "Only a Super Admin can create staff with admin (Super Admin) roles or sensitive permissions.")
                return self._render_form(request, form)

        with transaction.atomic():
            user = User.objects.create_user(
                username=data["username"],
                email=data["email"],
                password=data["password"],
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                is_staff=True,
                is_superuser=any(r.is_superadmin for r in selected_roles),
                is_active=True,
            )
            profile, _ = StaffProfile.objects.get_or_create(user=user)
            profile.roles.set(selected_roles)
            profile.direct_permissions.set(
                Permission.objects.filter(
                    code__in=expand_with_dependencies(
                        [p.code for p in selected_permissions])))
            profile.status = StaffProfile.Status.ACTIVE
            profile.save()

            audit_staff_event(
                "staff_created", request.user, user,
                f"Created staff account for {user.username}.",
                {
                    "roles": [r.slug for r in selected_roles],
                    "direct_permissions": [p.code for p in selected_permissions],
                    "superuser": user.is_superuser,
                })

        messages.success(request, f"Staff member {user.username} created.")
        return redirect("access-staff-detail", user_id=user.pk)


class StaffEditView(StaffPermissionRequiredMixin, View):
    permission_required = "staff.update"
    template_name = "access_control/staff_form.html"

    def _selections(self, form):
        if form.is_bound:
            role_ids = {r for r in form.data.getlist("roles")}
            direct = set(form.data.getlist("direct_permissions"))
        else:
            role_ids = {str(r) for r in form.initial.get("roles", [])}
            direct = {str(p) for p in form.initial.get("direct_permissions", [])}
        direct_codes = set(Permission.objects.filter(
            pk__in=[d for d in direct if d.isdigit()]).values_list("code", flat=True))
        return role_ids, direct, direct_codes

    def _render_form(self, request, form, user):
        role_ids, direct, direct_codes = self._selections(form)
        context = _page_context(
            request, "staff", f"Edit {user.username}",
            "Update the staff member's details and access.")
        context.update({
            "form": form,
            "roles": Role.objects.all(),
            "selected_role_ids": role_ids,
            "selected_direct_ids": direct,
            "matrix": _role_matrix(direct_codes),
            "submit_label": "Save changes",
            "mode": "edit",
            "edit_user": user,
            "sensitive_permissions": sensitive_codes(),
        })
        return render(request, self.template_name, context)

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id, is_staff=True)
        profile = _staff_profile(user)
        initial = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "roles": list(profile.roles.values_list("pk", flat=True)) if profile else [],
            "direct_permissions": (list(profile.direct_permissions.values_list("pk", flat=True))
                                   if profile else []),
        }
        form = StaffEditForm(initial=initial, instance=user)
        return self._render_form(request, form, user)

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id, is_staff=True)
        form = StaffEditForm(request.POST, instance=user)
        if not form.is_valid():
            return self._render_form(request, form, user)

        if user.pk == request.user.pk:
            messages.error(
                request, "You cannot edit your own staff profile.")
            return redirect("access-staff-detail", user_id=user.pk)

        data = form.cleaned_data
        profile = _staff_profile(user)
        if profile is None:
            profile = StaffProfile.objects.create(user=user)

        new_role_ids = set(r.pk for r in data["roles"])
        new_direct_ids = set(p.pk for p in data["direct_permissions"])
        old_role_ids = set(profile.roles.values_list("pk", flat=True))
        old_direct_ids = set(profile.direct_permissions.values_list("pk", flat=True))
        old_direct_codes = set(
            Permission.objects.filter(pk__in=old_direct_ids)
            .values_list("code", flat=True))

        roles_changed = new_role_ids != old_role_ids
        perms_changed = new_direct_ids != old_direct_ids

        if roles_changed or perms_changed:
            assign_ok = (can_assign_sensitive_permissions(request.user)
                         or user_has_permission(request.user, "permissions.assign"))
            if not assign_ok:
                messages.error(
                    request,
                    "Changing roles or permissions requires the 'Assign permissions' capability.")
                return self._render_form(request, form, user)

        new_roles = list(data["roles"])
        new_permissions = list(data["direct_permissions"])

        # Only Super Admins may (de-)assign elevated privileges.
        if roles_changed:
            touches_superadmin = any(
                not r.is_superadmin for r in profile.roles.all()) or any(
                r.is_superadmin for r in new_roles)
            if (user.is_superuser or any(r.is_superadmin for r in profile.roles.all())
                    or any(r.is_superadmin for r in new_roles)):
                if not can_assign_sensitive_permissions(request.user):
                    messages.error(
                        request,
                        "Only a Super Admin can change the Super Admin(s).")
                    return self._render_form(request, form, user)

        if perms_changed:
            new_sensitive = {p.code for p in new_permissions if p.is_sensitive}
            old_sensitive = {p.code for p in profile.direct_permissions.all() if p.is_sensitive}
            if new_sensitive != old_sensitive and not can_assign_sensitive_permissions(request.user):
                messages.error(
                    request,
                    "Only a Super Admin can grant or revoke sensitive permissions.")
                return self._render_form(request, form, user)

        will_be_superuser = any(r.is_superadmin for r in new_roles)
        if user.is_superuser and not will_be_superuser:
            if would_leave_no_active_super_admin(user):
                messages.error(
                    request,
                    "This is the last active Super Admin. Grant another member the "
                    "Super Admin role before deactivating this account.")
                return self._render_form(request, form, user)

        with transaction.atomic():
            user.first_name = data.get("first_name") or ""
            user.last_name = data.get("last_name") or ""
            user.email = data["email"]
            user.is_superuser = will_be_superuser
            user.save()

            profile.roles.set(new_roles)
            granted_codes = set(
                expand_with_dependencies([p.code for p in new_permissions]))
            profile.direct_permissions.set(
                Permission.objects.filter(code__in=granted_codes))
            profile.save()

            if roles_changed:
                audit_staff_event(
                    "staff_role_changed", request.user, user,
                    f"Updated roles for {user.username}.",
                    {
                        "old_roles": [r.slug for r in Role.objects.filter(pk__in=old_role_ids)],
                        "new_roles": [r.slug for r in new_roles],
                        "superuser": user.is_superuser,
                    })

            added = sorted(granted_codes - old_direct_codes)
            if added:
                audit_staff_event(
                    "permissions_granted", request.user, user,
                    f"Granted {len(added)} direct permission(s) to {user.username}.",
                    {"permissions": added})

            revoked = sorted(old_direct_codes - granted_codes)
            if revoked:
                audit_staff_event(
                    "permissions_revoked", request.user, user,
                    f"Revoked {len(revoked)} direct permission(s) from {user.username}.",
                    {"permissions": revoked})

            audit_staff_event(
                "staff_updated", request.user, user,
                f"Updated staff profile for {user.username}.",
                {})

        messages.success(request, f"Staff member {user.username} updated.")
        return redirect("access-staff-detail", user_id=user.pk)


class StaffDeactivateView(StaffPermissionRequiredMixin, View):
    permission_required = "staff.deactivate"

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id, is_staff=True)
        if user.pk == request.user.pk:
            messages.error(request, "You cannot deactivate your own account.")
            return redirect("access-staff-detail", user_id=user.pk)

        if user.is_superuser and not can_assign_sensitive_permissions(request.user):
            messages.error(
                request, "Only a Super Admin can deactivate another Super Admin.")
            return redirect("access-staff-detail", user_id=user.pk)

        if would_leave_no_active_super_admin(user):
            messages.error(
                request,
                "This is the last active Super Admin. Grant another member the "
                "Super Admin role before deactivating this account.")
            return redirect("access-staff-detail", user_id=user.pk)

        profile = _staff_profile(user)
        with transaction.atomic():
            user.is_active = False
            user.save(update_fields=["is_active"])
            if profile:
                profile.status = StaffProfile.Status.INACTIVE
                profile.save(update_fields=["status", "updated_at"])

            audit_staff_event(
                "staff_deactivated", request.user, user,
                f"Deactivated staff account {user.username}.",
                {"reason": request.POST.get("reason", "")[:500] or "No reason given"})
            AuditLogService.log(
                action="security_event",
                actor=request.user,
                category="security",
                object_type="user",
                object_id=str(user.pk),
                object_repr=user.get_full_name() or user.username,
                description=f"Staff account {user.username} deactivated — admin access revoked immediately.",
                metadata={},
                result="success",
                severity="high",
            )

        messages.success(
            request,
            f"{user.username} deactivated. Admin access is revoked immediately "
            "(existing sessions included).")
        return redirect("access-staff-detail", user_id=user.pk)


class StaffReactivateView(StaffPermissionRequiredMixin, View):
    permission_required = "staff.deactivate"

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id, is_staff=True)
        profile = _staff_profile(user)
        with transaction.atomic():
            user.is_active = True
            user.save(update_fields=["is_active"])
            if profile:
                profile.status = StaffProfile.Status.ACTIVE
                profile.save(update_fields=["status", "updated_at"])

            audit_staff_event(
                "staff_reactivated", request.user, user,
                f"Reactivated staff account {user.username}.",
                {})
        messages.success(
            request, f"{user.username} reactivated. Access restored.")
        return redirect("access-staff-detail", user_id=user.pk)


# ---------------------------------------------------------------------------
# Roles & Permissions
# ---------------------------------------------------------------------------

def _role_matrix(selected_codes=None):
    """Build the permission matrix grouped by catalog group for templates.

    Every row exposes whether the permission is sensitive and what it requires,
    plus whether it is currently selected.
    """
    selected = set(selected_codes or [])
    permission_map = {p.code: p for p in Permission.objects.all()}
    matrix = []
    for group, label in GROUPS:
        permissions = [
            {
                "pk": p.pk,
                "code": code,
                "label": p.label if p is not None else label,
                "description": getattr(p, "description", "") if p else "",
                "sensitive": bool(p and p.is_sensitive),
                "requires": (list(p.requires or []) if p else []),
                "selected": code in selected,
            }
            for code, p in ((c, permission_map.get(c)) for c in sorted(
                Permission.objects.filter(group=group).values_list("code", flat=True)))
        ]
        matrix.append({"group": group, "label": label, "permissions": permissions})
    return matrix


class RoleListView(StaffPermissionRequiredMixin, View):
    permission_required = "roles.view"
    template_name = "access_control/role_list.html"

    def get(self, request):
        roles = Role.objects.prefetch_related("permissions").annotate(
            staff_count=Count("staff_profiles", distinct=True),
            sensitive_count=Count(
                "permissions", filter=Q(permissions__is_sensitive=True),
                distinct=True))
        context = _page_context(
            request, "roles", "Roles & Permissions",
            "Define roles and the exact permissions each role carries.")
        context.update({
            "roles": roles,
            "sensitive_permissions": sensitive_codes(),
            "can_create": user_has_permission(request.user, "roles.create"),
        })
        return render(request, self.template_name, context)


class RoleDetailView(StaffPermissionRequiredMixin, View):
    permission_required = "roles.view"
    template_name = "access_control/role_detail.html"

    def get(self, request, role_id):
        role = get_object_or_404(
            Role.objects.prefetch_related("permissions", "staff_profiles__user"),
            pk=role_id)
        codes = set(role.permissions.values_list("code", flat=True))
        context = _page_context(
            request, "roles", role.name, "Role detail and permission matrix.")
        context.update({
            "role": role,
            "matrix": _role_matrix(codes),
            "issues": role_readiness_issues(role, codes),
            "sensitive_count": role.permissions.filter(is_sensitive=True).count(),
            "is_system_role": role.is_system_role,
            "can_edit": user_has_permission(request.user, "roles.update"),
            "can_delete": user_has_permission(request.user, "roles.delete"),
            "has_staff": role.staff_profiles.exists(),
        })
        return render(request, self.template_name, context)


class RoleCreateView(StaffPermissionRequiredMixin, View):
    permission_required = "roles.create"
    template_name = "access_control/role_form.html"

    def _selected_codes(self, form):
        if form.is_bound:
            pks = [p for p in form.data.getlist("permissions") if p.isdigit()]
        else:
            pks = [str(p) for p in form.initial.get("permissions", [])]
        return set(Permission.objects.filter(pk__in=pks).values_list("code", flat=True))

    def _render_form(self, request, form):
        context = _page_context(
            request, "roles", "Create role",
            "Bundle a set of permissions into a reusable role.")
        context.update({
            "form": form,
            "matrix": _role_matrix(self._selected_codes(form)),
            "sensitive_permissions": sensitive_codes(),
            "submit_label": "Create role",
            "mode": "create",
        })
        return render(request, self.template_name, context)

    def get(self, request):
        return self._render_form(request, RoleForm())

    def post(self, request):
        form = RoleForm(request.POST)
        if not form.is_valid():
            return self._render_form(request, form)

        data = form.cleaned_data
        codes = set(p.code for p in data["permissions"])
        with transaction.atomic():
            role = Role.objects.create(
                name=data["name"],
                description=data.get("description") or "",
                is_system_role=False,
                is_superadmin=False,
            )
            role.permissions.set(
                Permission.objects.filter(
                    code__in=expand_with_dependencies(sorted(codes))))
            audit_role_event(
                "role_created", request.user, role,
                f"Created role {role.name}.",
                {"permissions": sorted(role.permissions.values_list("code", flat=True))})
        messages.success(request, f"Role {role.name} created.")
        return redirect("access-role-detail", role_id=str(role.pk))


class RoleEditView(StaffPermissionRequiredMixin, View):
    permission_required = "roles.update"
    template_name = "access_control/role_form.html"

    def _selected_codes(self, form):
        if form.is_bound:
            pks = [p for p in form.data.getlist("permissions") if p.isdigit()]
        else:
            pks = [str(p) for p in form.initial.get("permissions", [])]
        return set(Permission.objects.filter(pk__in=pks).values_list("code", flat=True))

    def _render_form(self, request, form, role):
        context = _page_context(
            request, "roles", f"Edit role · {role.name}",
            "Adjust the role's permission bundle.")
        context.update({
            "form": form,
            "matrix": _role_matrix(self._selected_codes(form)),
            "sensitive_permissions": sensitive_codes(),
            "submit_label": "Save changes",
            "mode": "edit",
            "edit_role": role,
        })
        return render(request, self.template_name, context)

    def get(self, request, role_id):
        role = get_object_or_404(Role, pk=role_id)
        initial = {
            "name": role.name,
            "description": role.description,
            "permissions": list(role.permissions.values_list("pk", flat=True)),
        }
        return self._render_form(request, RoleForm(initial=initial), role)

    def post(self, request, role_id):
        role = get_object_or_404(Role, pk=role_id)
        form = RoleForm(request.POST)
        if not form.is_valid():
            return self._render_form(request, form, role)

        data = form.cleaned_data
        old = set(role.permissions.values_list("code", flat=True))
        new_codes = set(p.code for p in data["permissions"])
        with transaction.atomic():
            role.name = data["name"]
            role.description = data.get("description") or ""
            role.save()
            role.permissions.set(
                Permission.objects.filter(
                    code__in=expand_with_dependencies(sorted(new_codes))))
            audit_role_event(
                "role_updated", request.user, role,
                f"Updated role {role.name}.",
                {
                    "added": sorted(new_codes - old),
                    "removed": sorted(old - new_codes),
                })
        messages.success(request, f"Role {role.name} updated.")
        return redirect("access-role-detail", role_id=str(role.pk))


class RoleDeleteView(StaffPermissionRequiredMixin, View):
    permission_required = "roles.delete"

    def post(self, request, role_id):
        role = get_object_or_404(Role, pk=role_id)
        if role.is_system_role:
            messages.error(request, "System roles cannot be deleted.")
            return redirect("access-role-detail", role_id=str(role.pk))

        if role.staff_profiles.exists():
            messages.error(
                request,
                "This role is assigned to staff. Reassign those members before deleting it.")
            return redirect("access-role-detail", role_id=str(role.pk))

        with transaction.atomic():
            audit_role_event(
                "role_deleted", request.user, role,
                f"Deleted role {role.name}.",
                {"permissions": sorted(role.permissions.values_list("code", flat=True))})
            role.delete()
        messages.success(request, f"Role {role.name} deleted.")
        return redirect("access-roles")


@permission_required("roles.view")
class PermissionsMatrixView(View):
    template_name = "access_control/matrix.html"

    def get(self, request):
        context = _page_context(
            request, "roles", "Permissions",
            "Browse the complete MODEZA permission catalog.")
        context.update({
            "matrix": _role_matrix(),
            "sensitive_permissions": sensitive_codes(),
        })
        return render(request, self.template_name, context)
