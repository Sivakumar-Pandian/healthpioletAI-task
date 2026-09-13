from fpdf import FPDF
from app.models import GoodsReceiptNote, GrnCorrection, PurchaseOrder, SalesInvoice, StockTransfer, SupplierInvoice


class CleanPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(23, 26, 29)  # text-ink
        self.cell(0, 8, "HealthPilot Ops", ln=True)
        self.set_draw_color(200, 200, 200)
        self.line(10, 18, 200, 18)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(138, 143, 135)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _create_base_pdf(doc_type_title: str, doc_no: str) -> CleanPDF:
    pdf = CleanPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(166, 100, 42)  # amber accent
    pdf.cell(0, 8, doc_type_title, ln=True)

    pdf.set_font("Courier", "B", 12)
    pdf.set_text_color(23, 26, 29)
    pdf.cell(0, 6, f"Document No: {doc_no}", ln=True)
    pdf.ln(4)
    return pdf


def _render_table(pdf: CleanPDF, pairs: list[tuple[str, str]]):
    pdf.set_draw_color(220, 220, 220)
    for key, val in pairs:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(239, 241, 234)  # bg-paper tint
        pdf.set_text_color(50, 50, 50)
        pdf.cell(60, 8, f" {key}", border=1, fill=True)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(23, 26, 29)
        pdf.cell(130, 8, f" {val}", border=1, ln=True, fill=True)


def purchase_order_pdf(po: PurchaseOrder) -> bytes:
    pdf = _create_base_pdf("PURCHASE ORDER", po.document_no)
    pairs = [
        ("Supplier", po.supplier.name),
        ("Product", po.product.name),
        ("Quantity", f"{po.quantity} {po.product.unit}"),
        ("Delivery Location", po.delivery_location.name),
        ("Unit Price", f"INR {po.unit_price:,.2f}"),
        ("Tax Percent", f"{po.tax_percent}%"),
        ("Value Before Tax", f"INR {po.value_before_tax:,.2f}"),
        ("Tax Amount", f"INR {po.tax_amount:,.2f}"),
        ("Total Value", f"INR {po.total_value:,.2f}"),
        ("Status", po.status.value),
    ]
    _render_table(pdf, pairs)
    return bytes(pdf.output())


def grn_pdf(grn: GoodsReceiptNote, correction: GrnCorrection | None = None) -> bytes:
    pdf = _create_base_pdf("GOODS RECEIPT NOTE", grn.document_no)
    pairs = [
        ("Purchase Order", grn.purchase_order.document_no),
        ("Supplier", grn.purchase_order.supplier.name),
        ("Product", grn.purchase_order.product.name),
        ("Location", grn.purchase_order.delivery_location.name),
        ("Batch Number", grn.batch_number),
        ("Expiry Date", grn.expiry_date),
        ("Physical Quantity", str(grn.physical_quantity)),
        ("Accepted Quantity", str(grn.accepted_quantity)),
        ("Damaged Quantity", str(grn.damaged_quantity)),
        ("Missing Quantity", str(grn.missing_quantity)),
        ("Posted By", grn.posted_by.name),
        ("Posted At", grn.posted_at.strftime("%Y-%m-%d %H:%M")),
    ]
    _render_table(pdf, pairs)

    if correction:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(155, 58, 46)  # red status
        pdf.cell(0, 6, "Note: See correction on file.", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(50, 50, 50)
        corr_info = (
            f"Corrected figures: Accepted={correction.new_accepted_quantity}, "
            f"Damaged={correction.new_damaged_quantity}, Missing={correction.new_missing_quantity} | "
            f"Reason: {correction.reason}"
        )
        pdf.multi_cell(0, 5, corr_info)

    return bytes(pdf.output())


def supplier_invoice_pdf(invoice: SupplierInvoice) -> bytes:
    pdf = _create_base_pdf("SUPPLIER INVOICE", invoice.document_no)
    pairs = [
        ("Purchase Order", invoice.purchase_order.document_no),
        ("Goods Receipt Note", invoice.goods_receipt_note.document_no),
        ("Invoiced Quantity", str(invoice.invoiced_quantity)),
        ("Invoiced Value", f"INR {invoice.invoiced_value:,.2f}"),
        ("Payable Amount", f"INR {invoice.payable_amount:,.2f}"),
        ("Disputed Amount", f"INR {invoice.disputed_amount:,.2f}"),
        ("Status", invoice.status.value),
        ("Credit Note Ref", invoice.credit_note_reference or "—"),
    ]
    _render_table(pdf, pairs)
    return bytes(pdf.output())


def sales_invoice_pdf(sale: SalesInvoice) -> bytes:
    pdf = _create_base_pdf("SALES INVOICE / DISPENSING RECEIPT", sale.document_no)
    pairs = [
        ("Location", sale.location.name),
        ("Product", sale.product.name),
        ("Batch Number", sale.batch_number),
        ("Quantity", str(sale.quantity)),
        ("Payment Mode", sale.payment_mode),
        ("Prescription Ref", sale.prescription_reference or "—"),
        ("Unit Price", f"INR {sale.unit_price:,.2f}"),
        ("Tax Percent", f"{sale.tax_percent}%"),
        ("Value Before Tax", f"INR {sale.value_before_tax:,.2f}"),
        ("Tax Amount", f"INR {sale.tax_amount:,.2f}"),
        ("Total Amount", f"INR {sale.total_amount:,.2f}"),
        ("Cost Basis (Internal)", f"INR {sale.cost_of_goods:,.2f}"),
        ("Dispensed By", sale.dispensed_by.name),
        ("Dispensed At", sale.dispensed_at.strftime("%Y-%m-%d %H:%M")),
    ]
    _render_table(pdf, pairs)
    return bytes(pdf.output())


def stock_transfer_pdf(transfer: StockTransfer) -> bytes:
    pdf = _create_base_pdf("STOCK TRANSFER RECEIPT / NOTE", transfer.document_no)
    pairs = [
        ("Source Location", transfer.source_location.name),
        ("Destination Location", transfer.destination_location.name),
        ("Product", transfer.product.name),
        ("Batch Number", transfer.batch_number),
        ("Quantity", str(transfer.quantity)),
        ("Status", transfer.status.value),
        ("Dispatched By", transfer.dispatched_by.name),
        ("Dispatched At", transfer.dispatched_at.strftime("%Y-%m-%d %H:%M")),
        ("Received By", transfer.received_by.name if transfer.received_by else "—"),
        ("Received At", transfer.received_at.strftime("%Y-%m-%d %H:%M") if transfer.received_at else "—"),
    ]
    _render_table(pdf, pairs)
    return bytes(pdf.output())
