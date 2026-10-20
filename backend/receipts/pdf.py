"""Official receipt PDF rendering for Modeza (reportlab).

Generates a brand-consistent A4 receipt from a frozen :class:`Receipt` snapshot.
Built with reportlab's pure-Python platypus toolkit — no system packages are
required on the Render container.

The layout mirrors the boutique aesthetic: serif brand header in forest green,
gold accents, cream zebra shading and compact tabular money columns.
"""

import io

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
INK = rl_colors.HexColor('#181716')
MUTED = rl_colors.HexColor('#63605A')
FAINT = rl_colors.HexColor('#8A745C')
GREEN = rl_colors.HexColor('#2E5A44')
CREAM = rl_colors.HexColor('#FAF9F6')
LINE = rl_colors.HexColor('#E8E5DF')
WHITE = rl_colors.white

PAGE = A4  # 595 x 842 pt
MARGIN = 15 * mm
RIGHT_ALIGN_FONT = 'Helvetica'

STYLE_BODY = ParagraphStyle(
    name='body',
    fontName='Helvetica',
    fontSize=8.5,
    leading=12,
    textColor=INK,
)
STYLE_MUTED = ParagraphStyle(
    name='muted',
    parent=STYLE_BODY,
    fontName='Helvetica',
    fontSize=7.5,
    leading=10.5,
    textColor=MUTED,
)
STYLE_FAINT = ParagraphStyle(
    name='faint',
    parent=STYLE_MUTED,
    fontSize=6.5,
    leading=9,
    textColor=FAINT,
)


def _money(minor):
    """``123456`` -> ``KES 1,234.56`` (locale-independent grouping)."""
    return 'KES {0:,.2f}'.format(float(minor) / 100.0)


def _hex(color):
    """reportlab color -> ``#RRGGBB`` for use in paragraph markup."""
    return '#%s' % color.hexval()[2:].upper()


def _humanize(value, fallback=''):
    value = str(value or '').strip()
    return value or fallback


def _draw_receipt_watermark(canvas, _document):
    """Draw a low-contrast repeating PAID pattern and MODEZA wordmark."""
    canvas.saveState()

    # Keep the repeated mark subtle enough to sit behind small receipt text.
    canvas.setFillColor(rl_colors.HexColor("#124E01"))
    canvas.setFont('Helvetica-Bold', 8)
    for y in range(42, int(PAGE[1]), 112):
        offset = 44 if (y // 112) % 2 else 0
        for x in range(-20 + offset, int(PAGE[0]) + 40, 112):
            canvas.saveState()
            canvas.translate(x, y)
            canvas.rotate(32)
            canvas.drawString(0, 0, 'PAID')
            canvas.restoreState()

    canvas.saveState()
    canvas.translate(PAGE[0] / 2, PAGE[1] / 2)
    canvas.rotate(32)
    canvas.setFillColor(rl_colors.HexColor("#124E01"))
    canvas.setFont('Times-Bold', 64)
    canvas.drawCentredString(0, 0, 'MODEZA')
    canvas.restoreState()
    canvas.restoreState()


def render_receipt_pdf(receipt):
    """Render ``receipt`` to PDF bytes (pure function, no I/O)."""
    order = receipt.order
    snapshot = receipt.snapshot or {}
    customer = snapshot.get('customer') or {}
    items = snapshot.get('items') or []
    subtotal = snapshot.get('subtotal_minor') or 0
    discount = snapshot.get('discount_minor') or 0
    shipping = snapshot.get('shipping_cost_minor') or 0
    tax = snapshot.get('tax_minor') or 0
    total = snapshot.get('total_minor') or receipt.amount_minor or 0
    coupon_code = snapshot.get('coupon_code') or ''
    paid = receipt.amount_minor or 0
    balance = max(total - paid, 0)

    issued_at = receipt.generated_at or timezone.now()
    issued_local = timezone.localtime(issued_at)

    brand = (getattr(settings, 'STORE_NAME', '')
             or 'MODEZA Boutique').split(' ')
    brand_name = brand[0] if brand else 'MODEZA'
    brand_sub = ' '.join(brand[1:]) or 'BOUTIQUE'
    store_phone = getattr(settings, 'STORE_PHONE', '+254 700 123 456')
    store_email = getattr(
        settings, 'STORE_RECEIPT_EMAIL', 'boutique.modeza.support@gmail.com')
    store_website = getattr(
        settings, 'STORE_RECEIPT_WEBSITE',
        'https://atlier-boutique.vercel.app/')
    store_address = getattr(settings, 'STORE_ADDRESS', 'Nairobi, Kenya')

    story = []

    # -- Header ------------------------------------------------------------
    header = Table(
        [
            [
                Paragraph(
                    f'<font name="Times-Bold" size="22" color="%s">{_html_escape(brand_name)}</font>'
                    f'<font name="Times-Roman" size="13" color="%s">&nbsp;{_html_escape(brand_sub)}</font>'
                    % (_hex(GREEN), _hex(FAINT)),
                    ParagraphStyle(
                        name='brand', alignment=TA_LEFT, leading=24),
                ),
                Paragraph(
                    '<font name="Helvetica-Bold" size="9" color="%s">OFFICIAL RECEIPT</font>'
                    '<br/><font name="Helvetica" size="7" color="%s">%s</font>'
                    '<br/><font name="Helvetica" size="7" color="%s">Issued %s</font>'
                    % (
                        _hex(GREEN),
                        _hex(INK),
                        _html_escape(receipt.receipt_number),
                        _hex(MUTED),
                        issued_local.strftime('%d %b %Y, %H:%M'),
                    ),
                    ParagraphStyle(name='hdr', alignment=TA_RIGHT, leading=10),
                ),
            ]
        ],
        colWidths=[PAGE[0] - 2 * MARGIN - 150, 150],
    )
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 6))
    story.append(_rule())

    # -- Billed to / order reference ----------------------------------------
    name = _humanize(customer.get('fullName') or customer.get('full_name')
                     or customer.get('name'), 'Guest Customer')
    address_lines = [
        value for value in (
            _humanize(customer.get('addressLine1')
                      or customer.get('address_line1')),
            _humanize(customer.get('addressLine2')
                      or customer.get('address_line2')),
        ) if value
    ]
    city = _humanize(customer.get('city'), '')
    county = _humanize(customer.get('county')
                       or customer.get('stateOrProvince'), '')
    place = ', '.join(part for part in (city, county) if part)
    email = _humanize(customer.get('email'))
    phone = _humanize(customer.get('phone'))
    billed_lines = ['<b>BILLED TO</b>', _html_escape(name)]
    if address_lines:
        billed_lines.extend(_html_escape(line) for line in address_lines)
    if place:
        billed_lines.append(_html_escape(place))
    if email:
        billed_lines.append(_html_escape(email))
    if phone:
        billed_lines.append(_html_escape(phone))

    ref_lines = ['<b>ORDER REFERENCE</b>']
    ref_lines.append(f'Order {_html_escape(order.order_number)}')
    placed = timezone.localtime(order.created_at).strftime('%d %b %Y')
    ref_lines.append(f'Placed {_html_escape(placed)}')
    if receipt.gateway_reference:
        ref_lines.append(
            f'M-Pesa Receipt: {_html_escape(receipt.gateway_reference)}')
    ref_lines.append(f'Payment: {_html_escape(_payment_label(order.payment_method))}')
    ref_lines.append(_html_escape(receipt.currency or 'KES'))

    details = Table(
        [
            [
                Paragraph('<br/>'.join(billed_lines), STYLE_MUTED),
                Paragraph(
                    '<br/>'.join(ref_lines),
                    ParagraphStyle(
                        name='order-reference', parent=STYLE_MUTED,
                        alignment=TA_RIGHT)),
            ]
        ],
        colWidths=[(PAGE[0] - 2 * MARGIN) / 2] * 2,
    )
    details.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 8),
        ('LEFTPADDING', (1, 0), (1, 0), 8),
        ('RIGHTPADDING', (1, 0), (1, 0), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TEXTCOLOR', (0, 0), (-1, -1), INK),
    ]))
    story.append(details)
    story.append(Spacer(1, 14))

    # -- Items table --------------------------------------------------------
    headers = ['ITEM', 'SKU', 'SIZE', 'COLOUR', 'QTY', 'UNIT PRICE', 'AMOUNT']
    widths = [206, 78, 44, 66, 28, 72, 72]
    # Normalize extra width into the description column.
    used = sum(widths)
    target = PAGE[0] - 2 * MARGIN
    widths[0] += target - used

    data = [headers]
    for idx, item in enumerate(items or []):
        desc = _html_escape(str(item.get('product_name') or ''))
        sku = _html_escape(str(item.get('variant_sku') or ''))
        size = _html_escape(str(item.get('variant_size') or ''))
        colour = _html_escape(str(item.get('variant_color') or ''))
        qty = item.get('quantity') or 0
        unit = _money(item.get('unit_price_minor') or 0)
        amount = _money(item.get('line_total_minor') or 0)
        data.append([
            Paragraph(desc, STYLE_BODY),
            Paragraph(sku, STYLE_BODY),
            Paragraph(size, STYLE_BODY),
            Paragraph(colour, STYLE_BODY),
            Paragraph(str(qty), STYLE_BODY),
            Paragraph(unit, STYLE_BODY),
            Paragraph(amount, STYLE_BODY),
        ])

    items_table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('BACKGROUND', (0, 0), (-1, 0), GREEN),
        ('TOPPADDING', (0, 0), (-1, 0), 5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('TEXTCOLOR', (0, 1), (-1, -1), INK),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, LINE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, CREAM]),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('ALIGN', (4, 1), (4, -1), 'CENTER'),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('ALIGN', (4, 0), (4, 0), 'CENTER'),
        ('ALIGN', (5, 0), (-1, 0), 'RIGHT'),
    ]
    items_table.setStyle(TableStyle(style))
    story.append(items_table)
    story.append(Spacer(1, 12))

    # -- Totals -------------------------------------------------------------
    rows = [_totals_row('Subtotal', _money(subtotal))]
    if discount:
        label = f'Promotion{(" (" + coupon_code + ")") if coupon_code else ""}'
        rows.append(_totals_row(label, f'-{_money(discount)}'))
    rows.extend([
        _totals_row('Shipping', _money(shipping)),
        _totals_row('VAT (16%)', _money(tax)),
        _totals_row('Total', _money(total), bold=True),
        _totals_row('Amount Paid', _money(paid)),
        _totals_row('Balance Due', _money(balance)),
    ])
    # Subtotal, optional promotion, shipping and VAT all precede Total.
    total_row = 3 + int(bool(discount))
    totals = Table(rows, colWidths=[target - 150, 150])
    totals.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (0, -1), MUTED),
        ('TEXTCOLOR', (1, 0), (1, -1), INK),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (1, 0), (1, 0), 16),
        ('RIGHTPADDING', (1, 0), (1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LINEABOVE', (0, total_row), (-1, total_row), 0.7, LINE),
        ('TOPPADDING', (0, total_row), (-1, total_row), 6),
        ('FONTNAME', (0, total_row), (-1, total_row), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, total_row), (-1, total_row), GREEN),
    ]))
    story.append(totals)
    story.append(Spacer(1, 16))

    # -- Footer -------------------------------------------------------------
    footer_lines = [
        'Thank you for shopping with Modeza Boutique.',
        'All items are final sale per the returns policy. Contact us',
        f'{store_address}  {store_phone}  {store_email}  {store_website}',
    ]
    if balance and balance > 0:
        footer_lines[0] += f' Balance due remains {_money(balance)}.'
    footer_style = ParagraphStyle(
        name='receipt-footer', parent=STYLE_FAINT, alignment=1,
        fontSize=7, leading=9)
    story.append(Paragraph('<br/>'.join(_html_escape(line) for line in footer_lines), footer_style))
    story.append(Spacer(1, 8))
    story.append(_rule())
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        'This is a computer-generated official receipt and does not require a '
        f'signature. Receipt {_html_escape(receipt.receipt_number)} issued in '
        'accordance with Modeza Boutique records.',
        ParagraphStyle(name='receipt-legal', parent=STYLE_FAINT, alignment=1),
    ))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f'Modeza Boutique Receipt {receipt.receipt_number}',
        author='Modeza Boutique',
        subject=f'Official receipt for order {order.order_number}',
    )
    doc.build(
        story,
        onFirstPage=_draw_receipt_watermark,
        onLaterPages=_draw_receipt_watermark,
    )
    buffer.seek(0)
    return buffer.getvalue()


def _rule():
    from reportlab.platypus import HRFlowable
    return HRFlowable(width='100%', thickness=0.7, color=LINE,
                      spaceBefore=2, spaceAfter=2)


def _totals_row(label, value, bold=False):
    font = 'Helvetica-Bold' if bold else 'Helvetica'
    label_text = f'<font name="{font}" color="#63605A">{_html_escape(label)}</font>'
    value_text = f'<font name="{font}" color="#181716">{_html_escape(value)}</font>'
    return [
        Paragraph(label_text, STYLE_BODY),
        Paragraph(value_text, STYLE_BODY),
    ]


def _payment_label(method):
    return {
        'mpesa': 'M-Pesa',
        'card': 'Card',
        'cash_on_delivery': 'Cash on Delivery',
        'pay_on_delivery': 'Pay on Delivery',
    }.get(method, (method or '').replace('_', ' ').title() or 'Paid')


def _html_escape(value):
    value = str(value or '')
    return (
        value.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
