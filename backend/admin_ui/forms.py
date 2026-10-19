from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UsernameField
from django.contrib.auth.models import Group
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from catalog.models import Category, Product, ProductVariant
from catalog.variant_services import (
    normalize_hex,
    normalize_sku,
    sku_collides_within,
    unique_sku,
)
from access_control.models import StaffProfile


class AdminLoginForm(AuthenticationForm):
    """Django built-in authentication form restricted to staff accounts."""

    username = UsernameField(
        label='Username or staff email',
        widget=forms.TextInput(attrs={'autofocus': True}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'no_admin_access': 'This account does not have admin access.',
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(
                self.error_messages['no_admin_access'],
                code='no_admin_access',
            )


class AdminSignupForm(forms.ModelForm):
    """Create a staff administrator account with full powers (superuser-only view)."""

    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(render_value=False),
        strip=False,
        help_text='Must not be too similar to the username and must be at least 8 characters.',
    )
    password_confirm = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(render_value=False),
        strip=False,
    )

    class Meta:
        model = get_user_model()
        fields = (
            'username',
            'email',
            'first_name',
            'last_name',
            'groups',
            'is_superuser',
            'is_active',
        )
        labels = {
            'username': 'Username',
            'email': 'Email address',
            'first_name': 'First name',
            'last_name': 'Last name',
            'groups': 'Groups / roles',
            'is_superuser': 'Superuser (full control)',
            'is_active': 'Account active',
        }
        widgets = {
            'groups': forms.SelectMultiple(attrs={'size': 6}),
        }

    def __init__(self, *args, allow_superuser=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_superuser = allow_superuser
        self.fields['groups'].queryset = Group.objects.order_by('name')
        self.fields['groups'].help_text = 'Select the permission groups this administrator belongs to.'
        self.fields['is_superuser'].help_text = 'Superusers bypass all permission checks in the Django admin site.'
        self.fields['is_active'].help_text = 'Unchecking this locks the account immediately.'
        if not allow_superuser:
            self.fields['is_superuser'].disabled = True
            self.initial['is_superuser'] = False
            self.fields['is_superuser'].help_text = (
                'Only a superuser can grant full control.')

    def clean_is_superuser(self):
        is_superuser = self.cleaned_data.get('is_superuser') or False
        if getattr(self, 'allow_superuser', False):
            return is_superuser
        return False

    def clean_password(self):
        password = self.cleaned_data.get('password')
        username = self.cleaned_data.get('username')
        if password:
            password_validation.validate_password(password, user=None)
        if password and username and password.lower() == username.lower():
            raise ValidationError('The password must not match the username.')
        return password

    def clean_password_confirm(self):
        password = self.cleaned_data.get('password')
        password_confirm = self.cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            raise ValidationError('The two password fields did not match.')
        return password_confirm

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        if not getattr(self, 'allow_superuser', False):
            user.is_superuser = False
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            self.save_m2m()
            StaffProfile.objects.get_or_create(
                user=user, defaults={'status': StaffProfile.Status.ACTIVE})
        return user


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'slug', 'description', 'image_url', 'is_active')
        labels = {
            'name': 'Category name',
            'slug': 'Web address name',
            'image_url': 'Category image URL',
            'is_active': 'Visible in storefront',
        }
        help_texts = {
            'slug': 'Lowercase words separated by hyphens, for example evening-wear.',
            'image_url': 'Optional URL for the category image.',
        }


class ProductCreateForm(forms.Form):
    name = forms.CharField(label='Product name', max_length=200,
                           help_text='Use the name customers should see.')
    category = forms.ModelChoiceField(
        label='Collection', queryset=Category.objects.filter(is_active=True))
    price = forms.DecimalField(label='Selling price (KES)', max_digits=12,
                               decimal_places=2, min_value=0)
    status = forms.ChoiceField(
        label='Visibility', choices=Product.Status.choices, initial=Product.Status.ACTIVE,
        help_text='Active products appear in the storefront.')
    sku = forms.CharField(label='Internal item code', max_length=80, required=False,
                          help_text='Leave blank to generate a unique code automatically.')
    size = forms.CharField(label='Size', max_length=40, required=False)
    color = forms.CharField(label='Colour', max_length=80, required=False)
    stock_quantity = forms.IntegerField(label='Starting quantity', min_value=0,
                                        initial=0, help_text='How many are ready to sell?')
    image_file = forms.ImageField(
        label='Upload product image', required=True, help_text='Upload the product photo from your device.')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('sku') and ProductVariant.objects.filter(sku=cleaned['sku']).exists():
            self.add_error('sku', 'A variant with this SKU already exists.')
        return cleaned


class ProductUpdateForm(forms.Form):
    product_id = forms.UUIDField(widget=forms.HiddenInput())
    name = forms.CharField(label='Product name', max_length=200)
    slug = forms.SlugField(label='Web address name', max_length=100)
    category = forms.ModelChoiceField(
        label='Collection', queryset=Category.objects.filter(is_active=True))
    description = forms.CharField(label='Short description', widget=forms.Textarea(
        attrs={'rows': 3}))
    price = forms.DecimalField(label='Selling price (KES)', max_digits=12,
                               decimal_places=2, min_value=0)
    status = forms.ChoiceField(
        label='Visibility', choices=Product.Status.choices)
    image_file = forms.ImageField(
        label='Replace image', required=False, help_text='Upload a new product photo from your device.')

    def __init__(self, *args, **kwargs):
        self.product = kwargs.pop('product', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        slug = cleaned.get('slug')
        if slug and self.product and self.product.slug != slug:
            if Product.objects.filter(slug=slug).exclude(pk=self.product.pk).exists():
                self.add_error(
                    'slug', 'A product with this slug already exists.')
        return cleaned


class ProductVariantForm(forms.Form):
    sku = forms.CharField(label='SKU', max_length=80)
    size = forms.CharField(label='Size', max_length=40, required=False)
    color = forms.CharField(label='Colour', max_length=80, required=False)
    color_hex = forms.CharField(
        label='Colour hex', max_length=7, required=False)
    price = forms.DecimalField(
        label='Variant price (KES)', max_digits=12, decimal_places=2,
        min_value=0, required=False,
        help_text='Leave blank to use the product price.')
    stock_quantity = forms.IntegerField(
        label='Stock quantity', min_value=0, initial=0)
    is_active = forms.BooleanField(
        label='Available for sale', required=False, initial=True)

    def __init__(self, *args, **kwargs):
        self.product = kwargs.pop('product')
        self.variant = kwargs.pop('variant', None)
        super().__init__(*args, **kwargs)

    def clean_sku(self):
        sku = normalize_sku(self.cleaned_data['sku'])
        if not sku:
            raise forms.ValidationError(
                'Enter an SKU. Only letters and numbers are kept, '
                'everything else becomes a hyphen.')
        queryset = ProductVariant.objects.filter(sku=sku)
        if self.variant:
            queryset = queryset.exclude(pk=self.variant.pk)
        if queryset.exists():
            raise forms.ValidationError(
                'A variant with this SKU already exists.')
        return sku

    def clean_color_hex(self):
        value = self.cleaned_data.get('color_hex', '')
        try:
            return normalize_hex(value)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc

    def clean(self):
        cleaned = super().clean()
        size = (cleaned.get('size') or '').strip()
        color = (cleaned.get('color') or '').strip()
        if sku_collides_within(self.product, size, color,
                               exclude_id=self.variant.pk if self.variant else None):
            raise forms.ValidationError(
                'This size and colour combination already exists for the product.')
        return cleaned


class ProductVariantBulkForm(forms.Form):
    color = forms.CharField(label='Colour', max_length=80, required=False)
    color_hex = forms.CharField(
        label='Colour hex', max_length=7, required=False)
    price = forms.DecimalField(
        label='Variant price (KES)', max_digits=12, decimal_places=2,
        min_value=0, required=False,
        help_text='Leave blank to use the product price.')
    size_1 = forms.CharField(label='Size 1', max_length=40, required=False)
    quantity_1 = forms.IntegerField(
        label='Quantity 1', min_value=0, required=False)
    size_2 = forms.CharField(label='Size 2', max_length=40, required=False)
    quantity_2 = forms.IntegerField(
        label='Quantity 2', min_value=0, required=False)
    size_3 = forms.CharField(label='Size 3', max_length=40, required=False)
    quantity_3 = forms.IntegerField(
        label='Quantity 3', min_value=0, required=False)
    size_4 = forms.CharField(label='Size 4', max_length=40, required=False)
    quantity_4 = forms.IntegerField(
        label='Quantity 4', min_value=0, required=False)
    size_5 = forms.CharField(label='Size 5', max_length=40, required=False)
    quantity_5 = forms.IntegerField(
        label='Quantity 5', min_value=0, required=False)
    size_6 = forms.CharField(label='Size 6', max_length=40, required=False)
    quantity_6 = forms.IntegerField(
        label='Quantity 6', min_value=0, required=False)

    def __init__(self, *args, **kwargs):
        self.product = kwargs.pop('product')
        super().__init__(*args, **kwargs)

    def clean_color_hex(self):
        value = self.cleaned_data.get('color_hex', '')
        try:
            return normalize_hex(value)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from exc

    def clean(self):
        cleaned = super().clean()
        rows = []
        for index in range(1, 7):
            size = (cleaned.get(f'size_{index}') or '').strip()
            quantity = cleaned.get(f'quantity_{index}')
            if not size:
                if quantity not in (None, ''):
                    self.add_error(
                        f'quantity_{index}', 'Add a size for this quantity.')
                continue
            rows.append((size, quantity if quantity is not None else 0))

        if not rows:
            raise forms.ValidationError('Add at least one size and quantity.')

        color = (cleaned.get('color') or '').strip()
        seen_sizes = set()
        generated_skus = set()
        variant_specs = []
        for size, quantity in rows:
            normalized = size.casefold()
            if normalized in seen_sizes:
                raise forms.ValidationError(
                    f'The size {size} is listed more than once.')
            seen_sizes.add(normalized)
            if sku_collides_within(self.product, size, color):
                raise forms.ValidationError(
                    f'The size and colour combination {size} already exists.')
            sku = unique_sku(self.product, size, color)
            if sku in generated_skus:
                raise forms.ValidationError(
                    f'The sizes {size} would collide on the same SKU.')
            generated_skus.add(sku)
            variant_specs.append((sku, size, quantity))

        cleaned['variant_rows'] = rows
        cleaned['variant_specs'] = variant_specs
        return cleaned


class StockAdjustmentForm(forms.Form):
    variant = forms.ModelChoiceField(label='Item to update', queryset=ProductVariant.objects.select_related(
        'product').order_by('product__name', 'sku'))
    delta = forms.IntegerField(label='Quantity change', min_value=-100000,
                               max_value=100000, help_text='Add stock with a positive number or remove it with a negative number.')
    reason = forms.CharField(label='Reason', max_length=40,
                             initial='manual_adjustment')


class PromotionForm(forms.ModelForm):
    discount_amount = forms.DecimalField(label='Fixed discount (KES)', required=False, min_value=0, initial=0)
    maximum_discount = forms.DecimalField(label='Maximum discount (KES, optional)', required=False, min_value=0)
    minimum_order_value = forms.DecimalField(label='Minimum order value (KES)', required=False, min_value=0, initial=0)
    target_products = forms.ModelMultipleChoiceField(label='Specific products (optional)', queryset=Product.objects.order_by('name'), required=False)
    target_categories = forms.ModelMultipleChoiceField(label='Specific categories (optional)', queryset=Category.objects.order_by('name'), required=False)
    target_variants = forms.ModelMultipleChoiceField(label='Specific variants (optional)', queryset=ProductVariant.objects.select_related('product').order_by('sku'), required=False)
    target_customers = forms.ModelMultipleChoiceField(
        label='Specific customers',
        queryset=get_user_model().objects.filter(is_staff=False, is_active=True).order_by('email', 'username'),
        required=False,
        help_text='Choose the customer accounts eligible for this offer.',
    )

    class Meta:
        from promotions.models import Promotion
        model = Promotion
        fields = ('name', 'description', 'promotion_type', 'status', 'discount_percent',
                  'qualifying_quantity', 'reward_quantity', 'reward_discount_percent',
                  'max_redemptions_per_order', 'coupon_code', 'is_automatic',
                  'starts_at', 'ends_at', 'usage_limit', 'usage_limit_per_customer',
                  'priority', 'stackable', 'eligible_all', 'sale_only', 'new_only',
                  'customer_scope', 'minimum_quantity')
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing} form-control'.strip()
        for field_name in ('eligible_all', 'sale_only', 'new_only', 'stackable', 'is_automatic'):
            self.fields[field_name].widget.attrs['class'] += ' promo-checkbox'
        inst = self.instance
        if inst is not None and getattr(inst, 'pk', None):
            self.fields['discount_amount'].initial = (inst.discount_amount_minor or 0) / 100
            self.fields['maximum_discount'].initial = ((inst.maximum_discount_minor / 100)
                                                         if inst.maximum_discount_minor is not None else None)
            self.fields['minimum_order_value'].initial = (inst.minimum_order_value_minor or 0) / 100
            self.fields['target_products'].initial = [l.product_id for l in inst.promo_products.all()]
            self.fields['target_categories'].initial = [l.category_id for l in inst.promo_categories.all()]
            self.fields['target_variants'].initial = [l.variant_id for l in inst.promo_variants.all()]
            self.fields['target_customers'].initial = [l.user_id for l in inst.promo_customers.all()]

    def clean(self):
        cleaned = super().clean()
        starts, ends = cleaned.get('starts_at'), cleaned.get('ends_at')
        if starts and ends and ends <= starts:
            raise forms.ValidationError('End date must be after start date.')
        if cleaned.get('status') == 'active' and not ends:
            self.add_error('ends_at', 'Set an end date before publishing this promotion.')
        if float(cleaned.get('discount_percent') or 0) > 100:
            raise forms.ValidationError('Discount percentage cannot exceed 100.')
        ptype = cleaned.get('promotion_type')
        if ptype in ('buy_x_get_y', 'buy_x_get_pct') and ((cleaned.get('qualifying_quantity') or 0) <= 0 or (cleaned.get('reward_quantity') or 0) <= 0):
            raise forms.ValidationError('Buy X Get Y promotions need qualifying and reward quantities.')
        if cleaned.get('customer_scope') == 'specific' and not cleaned.get('target_customers'):
            self.add_error('target_customers', 'Choose at least one customer for a specific-customer offer.')
        if not cleaned.get('is_automatic') and not (cleaned.get('coupon_code') or '').strip():
            raise forms.ValidationError('Non-automatic promotions require a coupon code.')
        return cleaned

    def save(self, commit=True):
        promo = super().save(commit=False)
        if promo.is_automatic:
            # Automatic offers are applied by eligibility rules and do not have
            # a customer-facing code to retain or prefill at checkout.
            promo.coupon_code = ''
        promo.discount_amount_minor = int(round(float(self.cleaned_data.get('discount_amount') or 0) * 100))
        maxd = self.cleaned_data.get('maximum_discount')
        promo.maximum_discount_minor = None if maxd in (None, '') else int(round(float(maxd) * 100))
        promo.minimum_order_value_minor = int(round(float(self.cleaned_data.get('minimum_order_value') or 0) * 100))
        if commit:
            promo.save()
            from promotions.models import PromotionCategory, PromotionCustomer, PromotionProduct, PromotionVariant
            PromotionProduct.objects.filter(promotion=promo).delete()
            PromotionCategory.objects.filter(promotion=promo).delete()
            PromotionVariant.objects.filter(promotion=promo).delete()
            PromotionCustomer.objects.filter(promotion=promo).delete()
            for product in self.cleaned_data.get('target_products') or []:
                PromotionProduct.objects.get_or_create(promotion=promo, product=product)
            for category in self.cleaned_data.get('target_categories') or []:
                PromotionCategory.objects.get_or_create(promotion=promo, category=category)
            for variant in self.cleaned_data.get('target_variants') or []:
                PromotionVariant.objects.get_or_create(promotion=promo, variant=variant)
            for customer in self.cleaned_data.get('target_customers') or []:
                PromotionCustomer.objects.get_or_create(promotion=promo, user=customer)
            if promo.eligible_all is False and not ((self.cleaned_data.get('target_products') or []) or (self.cleaned_data.get('target_categories') or []) or (self.cleaned_data.get('target_variants') or [])):
                pass
        return promo
