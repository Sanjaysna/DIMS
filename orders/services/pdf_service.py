import io
from decimal import Decimal
from django.template import Context, Template
from xhtml2pdf import pisa

from orders.models import Invoice


INVOICE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Invoice #{{ invoice.id }}</title>
    <style>
        @page {
            size: letter;
            margin: 2cm;
            @bottom-right {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9pt;
                color: #718096;
            }
        }
        body {
            font-family: Helvetica, Arial, sans-serif;
            color: #1a202c;
            font-size: 10pt;
            line-height: 1.5;
        }
        .header-table {
            width: 100%;
            margin-bottom: 25px;
            border-bottom: 2px solid #2b6cb0;
            padding-bottom: 15px;
        }
        .brand-title {
            font-size: 20pt;
            font-weight: bold;
            color: #2b6cb0;
        }
        .brand-sub {
            font-size: 9pt;
            color: #718096;
        }
        .invoice-title {
            font-size: 16pt;
            font-weight: bold;
            text-align: right;
            color: #2d3748;
        }
        .meta-table {
            width: 100%;
            margin-bottom: 20px;
        }
        .meta-label {
            font-size: 8pt;
            color: #718096;
            text-transform: uppercase;
            font-weight: bold;
        }
        .meta-value {
            font-size: 10pt;
            font-weight: bold;
            color: #2d3748;
        }
        .items-table {
            width: 100%;
            margin-top: 15px;
            margin-bottom: 20px;
        }
        .items-table th {
            background-color: #ebf8ff;
            color: #2b6cb0;
            font-size: 9pt;
            text-transform: uppercase;
            padding: 8px 10px;
            text-align: left;
            border-bottom: 1px solid #cbd5e0;
        }
        .items-table td {
            padding: 8px 10px;
            border-bottom: 1px solid #e2e8f0;
            font-size: 9.5pt;
        }
        .text-right {
            text-align: right;
        }
        .text-center {
            text-align: center;
        }
        .total-box {
            width: 100%;
            margin-top: 10px;
        }
        .total-label {
            font-size: 12pt;
            font-weight: bold;
            color: #2d3748;
            text-align: right;
            padding-right: 15px;
        }
        .total-amount {
            font-size: 14pt;
            font-weight: bold;
            color: #2b6cb0;
            text-align: right;
        }
        .footer-note {
            margin-top: 40px;
            padding-top: 15px;
            border-top: 1px solid #e2e8f0;
            font-size: 8.5pt;
            color: #a0aec0;
            text-align: center;
        }
    </style>
</head>
<body>
    <table class="header-table">
        <tr>
            <td style="vertical-align: middle;">
                <div class="brand-title">DiSMS Enterprise</div>
                <div class="brand-sub">Distribution Intelligent Management System</div>
            </td>
            <td style="vertical-align: middle;" class="text-right">
                <div class="invoice-title">INVOICE</div>
                <div style="font-size: 10pt; color: #4a5568;">#INV-{{ invoice.id }}</div>
            </td>
        </tr>
    </table>

    <table class="meta-table">
        <tr>
            <td style="width: 50%; vertical-align: top;">
                <div class="meta-label">Billed To (Customer / Store)</div>
                <div class="meta-value">{{ store_name }}</div>
                <div style="font-size: 9pt; color: #718096;">Account ID: #{{ store_id }}</div>
            </td>
            <td style="width: 50%; vertical-align: top;" class="text-right">
                <div class="meta-label">Order Number</div>
                <div class="meta-value">{{ invoice.order.order_number }}</div>
                <div class="meta-label" style="margin-top: 6px;">Invoice Date</div>
                <div style="font-size: 9pt; color: #4a5568;">{{ invoice.created_at|date:"Y-m-d H:i" }}</div>
            </td>
        </tr>
    </table>

    <table class="items-table">
        <thead>
            <tr>
                <th style="width: 20%;">SKU</th>
                <th style="width: 40%;">Description</th>
                <th style="width: 12%;" class="text-center">Qty</th>
                <th style="width: 14%;" class="text-right">Unit Price</th>
                <th style="width: 14%;" class="text-right">Total</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td style="font-family: monospace; font-weight: bold;">{{ item.sku.sku }}</td>
                <td>{{ item.sku.name }}</td>
                <td class="text-center">{{ item.quantity }}</td>
                <td class="text-right">${{ item.unit_price }}</td>
                <td class="text-right" style="font-weight: bold;">${{ item.line_total }}</td>
            </tr>
            {% empty %}
            <tr>
                <td colspan="5" class="text-center" style="color: #a0aec0; padding: 20px;">
                    No line items recorded on this invoice.
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <table class="total-box">
        <tr>
            <td style="width: 70%;"></td>
            <td style="width: 30%;">
                <table style="width: 100%;">
                    <tr>
                        <td class="total-label">Grand Total:</td>
                        <td class="total-amount">${{ invoice.invoice_total }}</td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>

    <div class="footer-note">
        This is an official computer-generated invoice issued by DiSMS Warehouse Logistics.<br>
        All goods billed subject to standard fulfillment terms and condition agreements.
    </div>
</body>
</html>
"""


def generate_invoice_pdf(invoice: Invoice) -> bytes:
    """
    Renders an HTML invoice for the provided Invoice record and converts it
    to a PDF document using xhtml2pdf. Returns the binary PDF data as bytes.
    """
    store = getattr(invoice.order, 'store', None) or getattr(invoice.order, 'approved_by', None)
    store_name = store.get_full_name() or store.username if store else "Warehouse Customer"
    store_id = store.id if store else "N/A"

    items = list(invoice.items.select_related('sku').all())

    template = Template(INVOICE_HTML_TEMPLATE)
    context = Context({
        'invoice': invoice,
        'store_name': store_name,
        'store_id': store_id,
        'items': items,
    })
    html_content = template.render(context)

    buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=buffer)

    if pisa_status.err:
        raise RuntimeError(f"xhtml2pdf error occurred while generating Invoice #{invoice.id}: {pisa_status.err}")

    return buffer.getvalue()
