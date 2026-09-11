from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context, success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    GoodsReceiptNote,
    PurchaseOrder,
    SupplierInvoice,
    SupplierInvoiceStatus,
)
from app.stock import effective_accepted_quantity

router = APIRouter(prefix="/supplier-invoices", tags=["supplier-invoices"])
templates = Jinja2Templates(directory="templates")


def get_invoice_or_404(db: Session, invoice_id: int):
    invoice = db.get(SupplierInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Supplier invoice not found")
    return invoice


def get_grn_or_404(db: Session, grn_id: int):
    grn = db.get(GoodsReceiptNote, grn_id)
    if grn is None:
        raise HTTPException(status_code=404, detail="Goods receipt note not found")
    return grn


def get_invoice_for_grn(db: Session, grn_id: int):
    return (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.grn_id == grn_id)
        .first()
    )


def invoice_form_data(invoiced_quantity="", invoiced_value=""):
    return {
        "invoiced_quantity": invoiced_quantity,
        "invoiced_value": invoiced_value,
    }


def invoice_form_response(
    request: Request,
    db: Session,
    grn: GoodsReceiptNote,
    error_messages: list[str],
    form_data: dict,
    status_code: int = 422,
):
    po = grn.purchase_order
    effective_accepted = effective_accepted_quantity(db, grn)
    context = header_context(db)
    context.update(
        {
            "goods_receipt": grn,
            "purchase_order": po,
            "effective_accepted": effective_accepted,
            "expected_payable": round(
                effective_accepted * po.unit_price * (1 + po.tax_percent / 100), 2
            ),
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
        quantity = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Please enter a whole number for invoiced quantity.",
        )
    if quantity < 0:
        raise HTTPException(
            status_code=422,
            detail="Please enter zero or a positive number for invoiced quantity.",
        )
    return quantity


def parse_invoice_value(value):
    try:
        invoice_value = float(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Please enter a number for invoiced value.",
        )
    if invoice_value < 0:
        raise HTTPException(
            status_code=422,
            detail="Please enter zero or a positive number for invoiced value.",
        )
    return invoice_value


def friendly_error_messages(detail):
    if isinstance(detail, list):
        return [str(message) for message in detail]
    return [str(detail)]


@router.get("", response_class=HTMLResponse)
def list_supplier_invoices(request: Request, db: Session = Depends(get_db)):
    context = header_context(db)
    context["supplier_invoices"] = (
        db.query(SupplierInvoice).order_by(SupplierInvoice.id).all()
    )
    return templates.TemplateResponse(
        request, "supplier_invoices_list.html", context
    )


@router.get("/new", response_class=HTMLResponse)
def new_supplier_invoice_form(
    grn_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    grn = get_grn_or_404(db, grn_id)
    if get_invoice_for_grn(db, grn.id):
        raise HTTPException(
            status_code=422,
            detail="A supplier invoice already exists for this goods receipt.",
        )

    return invoice_form_response(
        request,
        db,
        grn,
        [],
        invoice_form_data(
            invoiced_quantity=effective_accepted_quantity(db, grn),
            invoiced_value=round(
                effective_accepted_quantity(db, grn)
                * grn.purchase_order.unit_price
                * (1 + grn.purchase_order.tax_percent / 100),
                2,
            ),
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
    grn = get_grn_or_404(db, grn_id)
    po = db.get(PurchaseOrder, grn.po_id)
    if po is None:
        raise HTTPException(status_code=422, detail="Purchase order not found")
    form_data = invoice_form_data(invoiced_quantity, invoiced_value)

    if get_invoice_for_grn(db, grn.id):
        return invoice_form_response(
            request,
            db,
            grn,
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
    context = header_context(db)
    context.update(
        {
            "supplier_invoice": invoice,
            "effective_accepted": effective_accepted_quantity(
                db, invoice.goods_receipt_note
            ),
        }
    )
    return templates.TemplateResponse(
        request, "supplier_invoices_detail.html", context
    )


@router.post("/{invoice_id}/resolve")
def resolve_supplier_invoice(
    invoice_id: int,
    credit_note_reference: str = Form(""),
    db: Session = Depends(get_db),
):
    invoice = get_invoice_or_404(db, invoice_id)
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
