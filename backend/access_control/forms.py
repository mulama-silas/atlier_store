from django import forms
from django.contrib.auth import get_user_model

from .models import Permission, Role, StaffProfile

User = get_user_model()


class StaffCreateForm(forms.Form):
    first_name = forms.CharField(
        required=False, max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "First name", "class": "form-control"}))
    last_name = forms.CharField(
        required=False, max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "Last name", "class": "form-control"}))
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "staff@modeza.store", "class": "form-control"}))
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "username", "class": "form-control"}))
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"placeholder": "Set a temporary password", "class": "form-control"}),
        label="Temporary password",
        help_text="Set a password for this account and share it with the staff member securely.")
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "perm-checkbox"}),
        label="Roles")
    direct_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "perm-checkbox"}),
        label="Direct permissions")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = Role.objects.all()
        self.fields["direct_permissions"].queryset = Permission.objects.all()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        conflict = User.objects.filter(
            email__iexact=email, is_staff=True,
        ).exclude(username__startswith="supabase_").order_by("username").first()
        if conflict is not None:
            raise forms.ValidationError(
                "A staff account with this email already exists (%s)."
                % conflict.username)
        return email


class StaffEditForm(forms.Form):
    first_name = forms.CharField(required=False, max_length=150)
    last_name = forms.CharField(required=False, max_length=150)
    email = forms.EmailField()
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "perm-checkbox"}),
        label="Roles")
    direct_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "perm-checkbox"}),
        label="Direct permissions")

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = Role.objects.all()
        self.fields["direct_permissions"].queryset = Permission.objects.all()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if self.instance is None:
            return email
        conflict = User.objects.filter(
            email__iexact=email, is_staff=True,
        ).exclude(username__startswith="supabase_").exclude(
            pk=self.instance.pk).order_by("username").first()
        if conflict is not None:
            raise forms.ValidationError(
                "A staff account with this email already exists (%s)."
                % conflict.username)
        return email


class RoleForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. Catalog Manager",
        }))
    description = forms.CharField(
        required=False, max_length=2000,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "form-control",
            "placeholder": "Describe the team or access this role is intended for.",
        }))
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "perm-checkbox"}),
        label="Permissions")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = Permission.objects.all()


class StaffSearchForm(forms.Form):
    q = forms.CharField(required=False, max_length=120)
