from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import (
    get_acting_user,
    header_context,
    scoped_location_ids,
    success_redirect,
)
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    GoodsReceiptNote,
    PurchaseOrder,
    SupplierInvoice,
    SupplierInvoiceStatus,
    UserRole,
)
from app.pdf_export import supplier_invoice_pdf
from app.image_export import pdf_bytes_to_png
from app.stock import effective_accepted_quantity
from app.traceability import build_chain

router = APIRouter(prefix="/supplier-invoices", tags=["supplier-invoices"])
templates = Jinja2Templates(directory="templates")


def get_grn_or_404(db: Session, grn_id: int):
    grn = db.get(GoodsReceiptNote, grn_id)
    if grn is None:
        raise HTTPException(status_code=404, detail="Goods receipt note not found")
    return grn


def get_invoice_or_404(db: Session, invoice_id: int):
    invoice = db.get(SupplierInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Supplier invoice not found")
    return invoice


def get_invoice_for_grn(db: Session, grn_id: int):
    return (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.grn_id == grn_id)
        .first()
    )


def invoice_form_data(invoiced_quantity="", invoiced_value=""):
    return {
        "invoiced_quantity": str(invoiced_quantity),
        "invoiced_value": str(invoiced_value),
    }


def invoice_form_response(
    request: Request,
    db: Session,
    grn: GoodsReceiptNote | None,
    available_grns: list[GoodsReceiptNote],
    error_messages: list[str],
    form_data: dict,
    status_code: int = 422,
):
    context = header_context(db, request)
    eff_accepted = effective_accepted_quantity(db, grn) if grn else 0
    expected_payable = (
        round(
            eff_accepted
            * grn.purchase_order.unit_price
            * (1 + grn.purchase_order.tax_percent / 100),
            2,
        )
        if grn
        else 0
    )
    context.update(
        {
            "goods_receipt": grn,
            "purchase_order": grn.purchase_order if grn else None,
            "available_grns": available_grns,
            "effective_accepted": eff_accepted,
            "expected_payable": expected_payable,
            "error_messages": error_messages,
            "form_data": form_data,
        }
    )
    return templates.TemplateResponse(
        request,
        "supplier_invoices_new.html",
        context,
        status_code=status_code,
    )


def parse_invoice_quantity(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Please enter a whole number for invoiced quantity.",
        )
    if parsed < 0:
        raise HTTPException(
            status_code=422,
            detail="Invoiced quantity cannot be negative.",
        )
    return parsed


def parse_invoice_value(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Please enter a valid amount for invoiced value.",
        )
    if parsed < 0:
        raise HTTPException(
            status_code=422,
            detail="Invoiced value cannot be negative.",
        )
    return parsed


def friendly_error_messages(detail):
    if isinstance(detail, list):
        return [str(message) for message in detail]
    return [str(detail)]


@router.get("", response_class=HTMLResponse)
def list_supplier_invoices(request: Request, db: Session = Depends(get_db)):
    context = header_context(db, request)
    acting_user = context["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)

    query = db.query(SupplierInvoice).order_by(SupplierInvoice.id)
    if loc_ids is not None:
        query = query.join(PurchaseOrder).filter(PurchaseOrder.delivery_location_id.in_(loc_ids))

    context["supplier_invoices"] = query.all()
    return templates.TemplateResponse(request, "supplier_invoices_list.html", context)


@router.get("/new", response_class=HTMLResponse)
def new_supplier_invoice_form(
    request: Request,
    grn_id: int | None = None,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if not acting_user or acting_user.role not in (UserRole.CENTRAL_PURCHASING, UserRole.COMPANY_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Central Purchasing or Company Admin can process supplier invoices.",
        )
    loc_ids = scoped_location_ids(db, acting_user)

    subquery = db.query(SupplierInvoice.grn_id).subquery()
    grn_query = db.query(GoodsReceiptNote).filter(~GoodsReceiptNote.id.in_(subquery))
    if loc_ids is not None:
        grn_query = grn_query.join(PurchaseOrder).filter(PurchaseOrder.delivery_location_id.in_(loc_ids))
    available_grns = grn_query.order_by(GoodsReceiptNote.id.desc()).all()

    grn = None
    if grn_id is not None:
        grn = get_grn_or_404(db, grn_id)
        if loc_ids is not None and grn.purchase_order.delivery_location_id not in loc_ids:
            raise HTTPException(status_code=403, detail="Access denied for this branch")
        if get_invoice_for_grn(db, grn.id):
            raise HTTPException(
                status_code=422,
                detail="A supplier invoice already exists for this goods receipt.",
            )
    elif available_grns:
        grn = available_grns[0]

    invoiced_qty = effective_accepted_quantity(db, grn) if grn else ""
    invoiced_val = (
        round(
            effective_accepted_quantity(db, grn)
            * grn.purchase_order.unit_price
            * (1 + grn.purchase_order.tax_percent / 100),
            2,
        )
        if grn
        else ""
    )

    return invoice_form_response(
        request,
        db,
        grn,
        available_grns,
        [],
        invoice_form_data(
            invoiced_quantity=invoiced_qty,
            invoiced_value=invoiced_val,
        ),
        status_code=200,
    )


@router.post("/new")
def create_supplier_invoice(
    request: Request,
    grn_id: int = Form(...),
    invoiced_quantity: str = Form(""),
    invoiced_value: str = Form(""),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if not acting_user or acting_user.role not in (UserRole.CENTRAL_PURCHASING, UserRole.COMPANY_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Central Purchasing or Company Admin can process supplier invoices.",
        )
    grn = get_grn_or_404(db, grn_id)
    po = db.get(PurchaseOrder, grn.po_id)
    if po is None:
        raise HTTPException(status_code=422, detail="Purchase order not found")

    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and po.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    form_data = invoice_form_data(invoiced_quantity, invoiced_value)

    subquery = db.query(SupplierInvoice.grn_id).subquery()
    grn_query = db.query(GoodsReceiptNote).filter(~GoodsReceiptNote.id.in_(subquery))
    if loc_ids is not None:
        grn_query = grn_query.join(PurchaseOrder).filter(PurchaseOrder.delivery_location_id.in_(loc_ids))
    available_grns = grn_query.order_by(GoodsReceiptNote.id.desc()).all()

    if get_invoice_for_grn(db, grn.id):
        return invoice_form_response(
            request,
            db,
            grn,
            available_grns,
            ["A supplier invoice already exists for this goods receipt."],
            form_data,
        )

    try:
        parsed_quantity = parse_invoice_quantity(invoiced_quantity)
        parsed_value = round(parse_invoice_value(invoiced_value), 2)
    except HTTPException as exc:
        return invoice_form_response(
            request,
            db,
            grn,
            available_grns,
            friendly_error_messages(exc.detail),
            form_data,
        )

    effective_accepted = effective_accepted_quantity(db, grn)
    payable_amount = round(
        effective_accepted * po.unit_price * (1 + po.tax_percent / 100), 2
    )
    if parsed_quantity != effective_accepted:
        status = SupplierInvoiceStatus.DISPUTED
        disputed_amount = round(parsed_value - payable_amount, 2)
    else:
        status = SupplierInvoiceStatus.MATCHED
        disputed_amount = 0

    invoice = SupplierInvoice(
        document_no=next_document_number(
            db, SupplierInvoice, "document_no", "SUPINV"
        ),
        po_id=po.id,
        grn_id=grn.id,
        invoiced_quantity=parsed_quantity,
        invoiced_value=parsed_value,
        status=status,
        payable_amount=payable_amount,
        disputed_amount=disputed_amount,
    )
    db.add(invoice)
    db.commit()
    return RedirectResponse(
        url=success_redirect("/supplier-invoices", f"{invoice.document_no} created"),
        status_code=303,
    )


@router.get("/{invoice_id}", response_class=HTMLResponse)
def supplier_invoice_detail(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    invoice = get_invoice_or_404(db, invoice_id)
    context = header_context(db, request)
    acting_user = context["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and invoice.purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    context.update(
        {
            "supplier_invoice": invoice,
            "effective_accepted": effective_accepted_quantity(
                db, invoice.goods_receipt_note
            ),
            "chain_steps": build_chain(db, invoice.purchase_order.requisition_id),
        }
    )
    return templates.TemplateResponse(
        request, "supplier_invoices_detail.html", context
    )


@router.post("/{invoice_id}/resolve")
def resolve_supplier_invoice(
    invoice_id: int,
    request: Request,
    credit_note_reference: str = Form(""),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if not acting_user or acting_user.role not in (UserRole.CENTRAL_PURCHASING, UserRole.COMPANY_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Central Purchasing or Company Admin can resolve disputed invoices.",
        )
    invoice = get_invoice_or_404(db, invoice_id)
    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and invoice.purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    if invoice.status != SupplierInvoiceStatus.DISPUTED:
        raise HTTPException(
            status_code=422,
            detail="Only disputed supplier invoices can record a credit note.",
        )
    if not credit_note_reference.strip():
        raise HTTPException(
            status_code=422,
            detail="Please enter a credit note reference.",
        )
    invoice.credit_note_reference = credit_note_reference.strip()
    db.commit()
    return RedirectResponse(
        url=success_redirect(
            f"/supplier-invoices/{invoice.id}",
            f"Credit note recorded for {invoice.document_no}",
        ),
        status_code=303,
    )


@router.get("/{invoice_id}/image")
def download_supplier_invoice_image(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    invoice = get_invoice_or_404(db, invoice_id)
    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and invoice.purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    pdf_bytes = supplier_invoice_pdf(invoice)
    status_str = invoice.status.value if hasattr(invoice.status, "value") else str(invoice.status)
    rows = [
        ("Purchase Order", invoice.purchase_order.document_no),
        ("Goods Receipt Note", invoice.goods_receipt_note.document_no),
        ("Invoiced Quantity", str(invoice.invoiced_quantity)),
        ("Invoiced Value", f"INR {invoice.invoiced_value:,.2f}"),
        ("Payable Amount", f"INR {invoice.payable_amount:,.2f}"),
        ("Disputed Amount", f"INR {invoice.disputed_amount:,.2f}"),
        ("Status", status_str),
        ("Credit Note Ref", invoice.credit_note_reference or "-"),
    ]
    png_bytes = pdf_bytes_to_png(pdf_bytes, "SUPPLIER INVOICE", invoice.document_no, rows)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{invoice.document_no}.png"'},
    )
