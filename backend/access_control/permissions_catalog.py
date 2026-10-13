"""Canonical MODEZA permission catalog.

This module is the single source of truth for:

  * permission groups (categories grouped in the UI),
  * permissions (codes, labels, descriptions, sensitive flags),
  * automatic dependencies (requires),
  * system default roles and their permission sets.

It contains *plain Python data only* so it can be consumed by data
migrations, management commands, forms and services alike.
"""

GROUPS = [
    ("products", "Products"),
    ("categories", "Categories"),
    ("variants", "Product Variants"),
    ("inventory", "Inventory"),
    ("orders", "Orders"),
    ("promotions", "Promotions"),
    ("customers", "Customers"),
    ("payments", "Payments"),
    ("receipts", "Receipts"),
    ("reports", "Reports"),
    ("staff", "Staff"),
    ("roles", "Roles & Permissions"),
    ("audit_logs", "Audit Logs"),
    ("emails", "Emails"),
]

# (code, label, description, is_sensitive, requires)
PERMISSIONS = [
    # Products
    ("products.view", "View products", "View the product catalog.", False, []),
    ("products.create", "Add products", "Create new products.", False, ["products.view"]),
    ("products.update", "Edit products", "Edit existing products.", False, ["products.view"]),
    ("products.delete", "Delete products", "Delete or archive products.", False, ["products.view"]),
    ("products.restock", "Restock products", "Restock products when low/out.", False, ["products.view", "inventory.view"]),
    ("products.import", "Import products", "Bulk import products.", False, ["products.view"]),
    # Categories
    ("categories.view", "View categories", "View categories.", False, []),
    ("categories.create", "Add categories", "Create new categories.", False, ["categories.view"]),
    ("categories.update", "Edit categories", "Edit categories.", False, ["categories.view"]),
    ("categories.delete", "Delete categories", "Delete or archive categories.", False, ["categories.view"]),
    # Product Variants
    ("variants.view", "View product variants", "View product variants.", False, ["products.view"]),
    ("variants.create", "Add product variants", "Add variants to products.", False, ["products.view"]),
    ("variants.update", "Edit product variants", "Edit variants.", False, ["products.view"]),
    ("variants.delete", "Delete product variants", "Delete or archive variants.", False, ["products.view"]),
    # Inventory
    ("inventory.view", "View inventory", "View inventory levels and stock.", False, []),
    ("inventory.adjust", "Adjust stock", "Manually adjust stock levels.", False, ["inventory.view"]),
    ("inventory.transfer", "Transfer stock", "Transfer stock between variants.", False, ["inventory.view"]),
    ("inventory.lowstock", "Manage low stock alerts", "View and manage low-stock alerts.", False, ["inventory.view"]),
    # Orders
    ("orders.view", "View orders", "View orders and order details.", False, []),
    ("orders.create", "Create orders", "Create new orders manually.", False, ["orders.view"]),
    ("orders.update", "Edit orders", "Edit order details.", False, ["orders.view"]),
    ("orders.confirm", "Approve / confirm orders", "Approve and confirm pending orders.", False, ["orders.view"]),
    ("orders.cancel", "Cancel orders", "Cancel orders.", False, ["orders.view"]),
    ("orders.refund", "Refund orders", "Issue refunds for orders.", True, ["orders.view"]),
    ("orders.delete", "Delete orders", "Delete orders.", False, ["orders.view"]),
    # Promotions
    ("promotions.view", "View promotions", "View promotions and usage.", False, []),
    ("promotions.create", "Add promotions", "Create new promotions.", False, ["promotions.view"]),
    ("promotions.update", "Edit promotions", "Edit and activate promotions.", False, ["promotions.view"]),
    ("promotions.delete", "Delete promotions", "Delete promotions.", False, ["promotions.view"]),
    # Customers
    ("customers.view", "View customers", "View customer profiles.", False, []),
    ("customers.update", "Edit customers", "Edit customer details.", False, ["customers.view"]),
    # Payments
    ("payments.view", "View payments", "View payment records.", False, []),
    ("payments.manage", "Manage / reconcile payments", "Reconcile and manage payments.", True, ["payments.view"]),
    # Receipts
    ("receipts.view", "View receipts", "View order receipts.", False, []),
    ("receipts.generate", "Regenerate receipts", "Regenerate order receipts.", False, ["receipts.view"]),
    # Reports
    ("reports.view", "View reports", "View operational reports and exports.", False, []),
    ("reports.financial", "Financial reports", "View financial / money reports.", True, ["reports.view"]),
    # Staff
    ("staff.view", "View staff", "View the staff directory.", False, []),
    ("staff.create", "Add staff", "Invite and create staff accounts.", True, ["staff.view"]),
    ("staff.update", "Edit staff", "Edit staff profiles and details.", True, ["staff.view"]),
    ("staff.deactivate", "Deactivate / reactivate staff", "Activate and deactivate staff accounts.", True, ["staff.view"]),
    # Roles & Permissions
    ("roles.view", "View roles", "View roles and the permission matrix.", False, []),
    ("roles.create", "Create roles", "Create custom roles.", True, ["roles.view"]),
    ("roles.update", "Edit roles", "Edit roles and their permission sets.", True, ["roles.view"]),
    ("roles.delete", "Delete roles", "Delete custom roles.", True, ["roles.view"]),
    ("permissions.assign", "Assign permissions", "Assign roles and permissions to staff.", True, ["staff.view"]),
    # Audit Logs
    ("audit_logs.view", "View audit logs", "View the audit trail.", False, []),
    ("audit_logs.export", "Export audit logs", "Export / download audit data.", False, ["audit_logs.view"]),
    # Emails
    ("emails.view", "View emails", "View the outbound email log.", False, []),
    ("emails.manage", "Manage emails", "Re-send failed or stuck outbound emails.", False, ["emails.view"]),
    # Supabase replica
    ("replica.view", "View backup status", "View Supabase replica status and run history.", False, []),
    ("replica.sync", "Run backup now", "Trigger a manual backup to Supabase.", True, ["replica.view"]),
]

PERMISSION_BY_CODE = {code: p for p in PERMISSIONS for code in ([p[0]] if isinstance(p[0], str) else p[0])}


def permissions_in_group(group):
    return [p for p in PERMISSIONS if p[0].split(".", 1)[0] == group]


# (code, name, description, is_system, is_superadmin, permission codes)
DEFAULT_ROLES = [
    (
        "super_admin",
        "Super Admin",
        "Full, unrestricted access to every MODEZA admin feature, including sensitive operations.",
        True,
        True,
        [code for code, *_ in PERMISSIONS],
    ),
    (
        "catalog_manager",
        "Catalog Manager",
        "Manages products, categories and product variants.",
        False,
        False,
        [
            "products.view", "products.create", "products.update", "products.delete",
            "products.restock", "products.import",
            "categories.view", "categories.create", "categories.update", "categories.delete",
            "variants.view", "variants.create", "variants.update", "variants.delete",
        ],
    ),
    (
        "inventory_manager",
        "Inventory Manager",
        "Manages stock levels, adjustments and low-stock alerts.",
        False,
        False,
        [
            "inventory.view", "inventory.adjust", "inventory.transfer", "inventory.lowstock",
            "products.view", "products.restock",
            "variants.view", "categories.view",
        ],
    ),
    (
        "order_manager",
        "Order Manager",
        "Processes orders: view, confirm, cancel, update and delete orders.",
        False,
        False,
        [
            "orders.view", "orders.create", "orders.update", "orders.confirm",
            "orders.cancel", "orders.delete",
            "promotions.view",
            "customers.view",
            "payments.view",
            "receipts.view",
            "inventory.view",
            "products.view", "variants.view", "categories.view",
        ],
    ),
    (
        "customer_support",
        "Customer Support",
        "Helps customers: views customers, orders and receipts.",
        False,
        False,
        [
            "customers.view", "customers.update",
            "orders.view",
            "receipts.view",
            "products.view", "variants.view", "categories.view",
        ],
    ),
    (
        "finance_manager",
        "Finance Manager",
        "Manages payments, receipts and financial reports.",
        False,
        False,
        [
            "payments.view", "payments.manage",
            "receipts.view", "receipts.generate",
            "reports.view", "reports.financial",
            "orders.view", "customers.view",
        ],
    ),
    (
        "promotion_manager",
        "Promotion Manager",
        "Manages promotions, coupon codes and promotion analytics.",
        False,
        False,
        [
            "promotions.view", "promotions.create", "promotions.update", "promotions.delete",
            "products.view", "variants.view", "categories.view",
            "orders.view", "reports.view",
        ],
    ),
    (
        "legacy_administrator",
        "Legacy Administrator",
        "Migration fallback for pre-existing staff not previously covered by "
        "the role system. Grants full access with sensitive capabilities excluded.",
        True,
        False,
        [code for code, _label, _desc, sensitive, _req in PERMISSIONS if not sensitive],
    ),
]

ROLE_BY_CODE = {code: r for r in DEFAULT_ROLES for code in ([r[0]] if isinstance(r[0], str) else r[0])}


def resolve_dependencies(codes):
    """Expand ``codes`` with all of their required permissions (recursive)."""
    by_code = {code: set(req) for code, _l, _d, _s, req in PERMISSIONS}
    resolved = set(codes)
    stack = list(codes)
    while stack:
        current = stack.pop()
        for req in by_code.get(current, set()):
            if req not in resolved:
                resolved.add(req)
                stack.append(req)
    return sorted(resolved)


def sensitive_codes():
    return {code for code, _l, _d, sensitive, _req in PERMISSIONS if sensitive}