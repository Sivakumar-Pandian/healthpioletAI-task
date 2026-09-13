"""
Traceability chain builder — given a Requisition, walks the document chain
and returns a list of step dicts ready for the _chain_strip.html include.

Each step dict has:
  type         – short type label ('REQ', 'PO', 'GRN', 'INV', 'STN', 'SALE')
  label        – human-readable type name
  doc_no       – document number (font-mono)
  url          – detail page URL
  status       – status string (or None)
  status_color – 'green' | 'amber' | 'red' | 'grey'
  corrected    – bool (True if this step has a GrnCorrection)
  detail_lines – list of short "Key: Value" strings shown under doc_no in detail view
"""

from sqlalchemy.orm import Session

from app.models import (
    GoodsReceiptNote,
    GrnCorrection,
    PurchaseOrder,
    Requisition,
    SalesInvoice,
    StockTransfer,
    SupplierInvoice,
)


def _pill_color(status: str | None) -> str:
    """Map a status string to a colour token understood by the template."""
    if status is None:
        return "grey"
    s = status.upper()
    if s in {"APPROVED", "RECEIVED", "MATCHED", "CLOSED"}:
        return "green"
    if s in {"REJECTED", "DISPUTED"}:
        return "red"
    if s in {"DISPATCHED", "PARTIALLY_RECEIVED"}:
        return "amber"
    # SUBMITTED, OPEN, DRAFT, CORRECTED, …
    return "grey"


def build_chain(db: Session, requisition_id: int) -> list[dict]:
    """Build and return the ordered list of chain step dicts for a requisition."""
    steps: list[dict] = []

    # -----------------------------------------------------------------
    # Step 1 — Requisition
    # -----------------------------------------------------------------
    req: Requisition | None = db.get(Requisition, requisition_id)
    if req is None:
        return steps

    steps.append(
        {
            "type": "REQ",
            "label": "Requisition",
            "doc_no": req.document_no,
            "url": f"/requisitions/{req.id}",
            "status": req.status.value,
            "status_color": _pill_color(req.status.value),
            "corrected": False,
            "detail_lines": [
                f"Location: {req.location.name}",
                f"Product: {req.product.name}",
                f"Qty requested: {req.quantity}",
                f"Required by: {req.required_date}",
            ],
        }
    )

    # -----------------------------------------------------------------
    # Step 2 — Purchase Order (first one for this requisition)
    # -----------------------------------------------------------------
    po: PurchaseOrder | None = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.requisition_id == req.id)
        .order_by(PurchaseOrder.id)
        .first()
    )
    if po is None:
        return steps

    steps.append(
        {
            "type": "PO",
            "label": "Purchase Order",
            "doc_no": po.document_no,
            "url": f"/purchase-orders/{po.id}",
            "status": po.status.value,
            "status_color": _pill_color(po.status.value),
            "corrected": False,
            "detail_lines": [
                f"Supplier: {po.supplier.name}",
                f"Qty: {po.quantity}",
                f"Total: ₹{po.total_value:,.2f}",
                f"Delivery: {po.delivery_location.name}",
            ],
        }
    )

    # -----------------------------------------------------------------
    # Step 3 — Goods Receipt Note
    # -----------------------------------------------------------------
    grn: GoodsReceiptNote | None = (
        db.query(GoodsReceiptNote)
        .filter(GoodsReceiptNote.po_id == po.id)
        .order_by(GoodsReceiptNote.id)
        .first()
    )
    if grn is None:
        return steps

    correction: GrnCorrection | None = (
        db.query(GrnCorrection)
        .filter(GrnCorrection.original_grn_id == grn.id)
        .first()
    )
    eff_acc = correction.new_accepted_quantity if correction else grn.accepted_quantity
    eff_dmg = correction.new_damaged_quantity if correction else grn.damaged_quantity

    steps.append(
        {
            "type": "GRN",
            "label": "Goods Receipt",
            "doc_no": grn.document_no,
            "url": f"/goods-receipts/{grn.id}",
            "status": "CORRECTED" if correction else "RECEIVED",
            "status_color": "green" if not correction else "amber",
            "corrected": correction is not None,
            "detail_lines": [
                f"Batch: {grn.batch_number}",
                f"Physical: {grn.physical_quantity}",
                f"Accepted: {eff_acc}{'*' if correction else ''}",
                f"Damaged: {eff_dmg}{'*' if correction else ''}",
            ],
        }
    )

    # -----------------------------------------------------------------
    # Step 4 — Supplier Invoice
    # -----------------------------------------------------------------
    inv: SupplierInvoice | None = (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.grn_id == grn.id)
        .order_by(SupplierInvoice.id)
        .first()
    )
    if inv is None:
        return steps

    inv_detail = [
        f"Invoiced qty: {inv.invoiced_quantity}",
        f"Payable: ₹{inv.payable_amount:,.2f}",
    ]
    if inv.disputed_amount:
        inv_detail.append(f"Disputed: ₹{inv.disputed_amount:,.2f}")

    steps.append(
        {
            "type": "INV",
            "label": "Supplier Invoice",
            "doc_no": inv.document_no,
            "url": f"/supplier-invoices/{inv.id}",
            "status": inv.status.value,
            "status_color": _pill_color(inv.status.value),
            "corrected": False,
            "detail_lines": inv_detail,
        }
    )

    # -----------------------------------------------------------------
    # Step 5 — Stock Transfer (loose match: source = PO delivery_location,
    #           same product, same batch as GRN)
    # -----------------------------------------------------------------
    transfer: StockTransfer | None = (
        db.query(StockTransfer)
        .filter(
            StockTransfer.source_location_id == po.delivery_location_id,
            StockTransfer.product_id == po.product_id,
            StockTransfer.batch_number == grn.batch_number,
        )
        .order_by(StockTransfer.id)
        .first()
    )
    if transfer is None:
        return steps

    steps.append(
        {
            "type": "STN",
            "label": "Stock Transfer",
            "doc_no": transfer.document_no,
            "url": f"/transfers/{transfer.id}",
            "status": transfer.status.value,
            "status_color": _pill_color(transfer.status.value),
            "corrected": False,
            "detail_lines": [
                f"From: {transfer.source_location.name}",
                f"To: {transfer.destination_location.name}",
                f"Qty: {transfer.quantity}",
                f"Batch: {transfer.batch_number}",
            ],
        }
    )

    # -----------------------------------------------------------------
    # Step 6 — Sales Invoice (loose match: at transfer destination,
    #           same product, same batch)
    # -----------------------------------------------------------------
    sale: SalesInvoice | None = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.location_id == transfer.destination_location_id,
            SalesInvoice.product_id == po.product_id,
            SalesInvoice.batch_number == grn.batch_number,
        )
        .order_by(SalesInvoice.id)
        .first()
    )
    if sale is None:
        return steps

    steps.append(
        {
            "type": "SALE",
            "label": "Sales Invoice",
            "doc_no": sale.document_no,
            "url": f"/dispensing/{sale.id}",
            "status": "DISPENSED",
            "status_color": "green",
            "corrected": False,
            "detail_lines": [
                f"Batch: {sale.batch_number}",
                f"Qty dispensed: {sale.quantity}",
                f"Total: ₹{sale.total_amount:,.2f}",
                f"Payment: {sale.payment_mode}",
            ],
        }
    )

    return steps


def build_narrative(db: Session, requisition_id: int) -> str:
    """Generate a short plain-English narrative paragraph from real DB values."""
    req: Requisition | None = db.get(Requisition, requisition_id)
    if req is None:
        return ""

    sentences: list[str] = []

    loc_name = req.location.name
    prod_name = req.product.name
    sentences.append(
        f"{loc_name} requested {req.quantity} units of {prod_name} "
        f"(status: {req.status.value.lower()})."
    )

    po: PurchaseOrder | None = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.requisition_id == req.id)
        .order_by(PurchaseOrder.id)
        .first()
    )
    if po is None:
        sentences.append("No purchase order has been raised yet.")
        return " ".join(sentences)

    sentences.append(
        f"A purchase order ({po.document_no}) for {po.quantity} units was placed "
        f"with {po.supplier.name} (₹{po.total_value:,.2f} incl. tax), "
        f"to be delivered to {po.delivery_location.name}."
    )

    grn: GoodsReceiptNote | None = (
        db.query(GoodsReceiptNote)
        .filter(GoodsReceiptNote.po_id == po.id)
        .order_by(GoodsReceiptNote.id)
        .first()
    )
    if grn is None:
        sentences.append("No goods receipt has been posted yet.")
        return " ".join(sentences)

    correction: GrnCorrection | None = (
        db.query(GrnCorrection)
        .filter(GrnCorrection.original_grn_id == grn.id)
        .first()
    )

    eff_acc = correction.new_accepted_quantity if correction else grn.accepted_quantity
    eff_dmg = correction.new_damaged_quantity if correction else grn.damaged_quantity

    grn_sentence = (
        f"{grn.physical_quantity} units physically arrived (batch {grn.batch_number}); "
        f"{eff_acc} accepted as usable"
    )
    if eff_dmg:
        grn_sentence += f", {eff_dmg} quarantined/damaged"
    if correction:
        grn_sentence += " (figures updated by a GRN correction)"
    grn_sentence += "."
    sentences.append(grn_sentence)

    inv: SupplierInvoice | None = (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.grn_id == grn.id)
        .order_by(SupplierInvoice.id)
        .first()
    )
    if inv is None:
        sentences.append("No supplier invoice has been recorded yet.")
        return " ".join(sentences)

    if inv.status.value == "DISPUTED":
        inv_sentence = (
            f"The supplier's invoice ({inv.document_no}) for {inv.invoiced_quantity} units "
            f"is disputed — ₹{inv.disputed_amount:,.2f} outstanding, "
            f"₹{inv.payable_amount:,.2f} agreed payable."
        )
    else:
        inv_sentence = (
            f"The supplier's invoice ({inv.document_no}) for {inv.invoiced_quantity} units "
            f"is matched — ₹{inv.payable_amount:,.2f} payable."
        )
    sentences.append(inv_sentence)

    transfer: StockTransfer | None = (
        db.query(StockTransfer)
        .filter(
            StockTransfer.source_location_id == po.delivery_location_id,
            StockTransfer.product_id == po.product_id,
            StockTransfer.batch_number == grn.batch_number,
        )
        .order_by(StockTransfer.id)
        .first()
    )
    if transfer is None:
        sentences.append("No stock transfer has been dispatched yet.")
        return " ".join(sentences)

    txn_status = transfer.status.value.lower()
    sentences.append(
        f"{transfer.quantity} units were {txn_status} from {transfer.source_location.name} "
        f"to {transfer.destination_location.name} ({transfer.document_no})."
    )

    sale: SalesInvoice | None = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.location_id == transfer.destination_location_id,
            SalesInvoice.product_id == po.product_id,
            SalesInvoice.batch_number == grn.batch_number,
        )
        .order_by(SalesInvoice.id)
        .first()
    )
    if sale is None:
        sentences.append("No units have been dispensed to a patient yet.")
        return " ".join(sentences)

    sentences.append(
        f"{sale.quantity} unit{'s' if sale.quantity != 1 else ''} "
        f"{'have' if sale.quantity != 1 else 'has'} been dispensed "
        f"(₹{sale.total_amount:,.2f} total, {sale.payment_mode})."
    )

    return " ".join(sentences)
