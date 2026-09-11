from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context, success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    AppUser,
    GoodsReceiptNote,
    GrnCorrection,
    LedgerTxnType,
    PurchaseOrder,
    PurchaseOrderStatus,
    StockLedgerEntry,
    StockStatus,
)
from app.stock import computed_stock

router = APIRouter(prefix="/goods-receipts", tags=["goods-receipts"])
templates = Jinja2Templates(directory="templates")


def get_purchase_order_or_404(db: Session, purchase_order_id: int):
    purchase_order = db.get(PurchaseOrder, purchase_order_id)
    if purchase_order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return purchase_order


def get_goods_receipt_or_404(db: Session, receipt_id: int):
    receipt = db.get(GoodsReceiptNote, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Goods receipt note not found")
    return receipt


def get_receipt_for_po(db: Session, purchase_order_id: int):
    return (
        db.query(GoodsReceiptNote)
        .filter(GoodsReceiptNote.po_id == purchase_order_id)
        .first()
    )


def get_correction_for_receipt(db: Session, receipt_id: int):
    return (
        db.query(GrnCorrection)
        .filter(GrnCorrection.original_grn_id == receipt_id)
        .first()
    )


def validate_receipt_quantities(
    physical_quantity: int,
    accepted_quantity: int,
    damaged_quantity: int,
    missing_quantity: int,
    ordered_quantity: int,
):
    if any(
        quantity < 0
        for quantity in (
            physical_quantity,
            accepted_quantity,
            damaged_quantity,
            missing_quantity,
        )
    ):
        raise HTTPException(
            status_code=422,
            detail="Please enter zero or a positive number for each quantity.",
        )

    errors = []
    if accepted_quantity + damaged_quantity != physical_quantity:
        errors.append(
            f"The quantities do not add up: accepted ({accepted_quantity}) + damaged ({damaged_quantity}) "
            f"equals {accepted_quantity + damaged_quantity}, but physical quantity is {physical_quantity}."
        )
    if physical_quantity + missing_quantity != ordered_quantity:
        errors.append(
            f"The receipt does not match the purchase order: physical ({physical_quantity}) + missing ({missing_quantity}) "
            f"equals {physical_quantity + missing_quantity}, but the PO quantity is {ordered_quantity}."
        )
    if errors:
        raise HTTPException(status_code=422, detail=errors)


def receipt_form_data(
    batch_number="",
    expiry_date="",
    physical_quantity="",
    accepted_quantity="",
    damaged_quantity="",
    missing_quantity="",
    posted_by_id="",
):
    return {
        "batch_number": batch_number,
        "expiry_date": expiry_date,
        "physical_quantity": physical_quantity,
        "accepted_quantity": accepted_quantity,
        "damaged_quantity": damaged_quantity,
        "missing_quantity": missing_quantity,
        "posted_by_id": posted_by_id,
    }


def receipt_form_response(
    request: Request,
    db: Session,
    purchase_order: PurchaseOrder,
    error_messages: list[str],
    form_data: dict,
):
    context = header_context(db)
    context.update(
        {
            "purchase_order": purchase_order,
            "error_messages": error_messages,
            "form_data": form_data,
        }
    )
    return templates.TemplateResponse(
        request,
        "goods_receipts_new.html",
        context,
        status_code=422,
    )


def correction_form_data(
    accepted_quantity="",
    damaged_quantity="",
    missing_quantity="",
    reason="",
    corrected_by_id="",
):
    return {
        "accepted_quantity": accepted_quantity,
        "damaged_quantity": damaged_quantity,
        "missing_quantity": missing_quantity,
        "reason": reason,
        "corrected_by_id": corrected_by_id,
    }


def correction_form_response(
    request: Request,
    db: Session,
    receipt: GoodsReceiptNote,
    error_messages: list[str],
    form_data: dict,
    status_code: int = 422,
):
    context = header_context(db)
    context.update(
        {
            "goods_receipt": receipt,
            "purchase_order": receipt.purchase_order,
            "error_messages": error_messages,
            "form_data": form_data,
        }
    )
    return templates.TemplateResponse(
        request,
        "goods_receipts_correct.html",
        context,
        status_code=status_code,
    )


def parse_quantity(value, label: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=f"Please enter a whole number for {label}.",
        )


def friendly_error_messages(detail):
    if isinstance(detail, list):
        return [str(message) for message in detail]
    return [str(detail)]


@router.get("", response_class=HTMLResponse)
def list_goods_receipts(request: Request, db: Session = Depends(get_db)):
    context = header_context(db)
    context["goods_receipts"] = (
        db.query(GoodsReceiptNote).order_by(GoodsReceiptNote.id).all()
    )
    return templates.TemplateResponse(request, "goods_receipts_list.html", context)


@router.get("/new", response_class=HTMLResponse)
def new_goods_receipt_form(
    po_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    purchase_order = get_purchase_order_or_404(db, po_id)
    if get_receipt_for_po(db, purchase_order.id):
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["This purchase order already has a goods receipt and cannot be received again."],
            receipt_form_data(),
        )
    if purchase_order.status not in (
        PurchaseOrderStatus.OPEN,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
    ):
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["This purchase order is already closed and cannot receive goods."],
            receipt_form_data(),
        )

    context = header_context(db)
    context.update(
        {
            "purchase_order": purchase_order,
            "form_data": receipt_form_data(),
            "error_messages": [],
        }
    )
    return templates.TemplateResponse(request, "goods_receipts_new.html", context)


@router.post("/new")
def create_goods_receipt(
    request: Request,
    po_id: int = Form(...),
    batch_number: str = Form(""),
    expiry_date: str = Form(""),
    physical_quantity: str = Form(""),
    accepted_quantity: str = Form(""),
    damaged_quantity: str = Form(""),
    missing_quantity: str = Form(""),
    posted_by_id: str = Form(""),
    db: Session = Depends(get_db),
):
    purchase_order = get_purchase_order_or_404(db, po_id)
    form_data = receipt_form_data(
        batch_number,
        expiry_date,
        physical_quantity,
        accepted_quantity,
        damaged_quantity,
        missing_quantity,
        posted_by_id,
    )
    if get_receipt_for_po(db, purchase_order.id):
        return receipt_form_response(
            request=request,
            db=db,
            purchase_order=purchase_order,
            error_messages=["This purchase order already has a goods receipt and cannot be received again."],
            form_data=form_data,
        )
    if purchase_order.status not in (
        PurchaseOrderStatus.OPEN,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
    ):
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["This purchase order is already closed and cannot receive goods."],
            form_data,
        )
    if not batch_number.strip():
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["Please enter a batch number."],
            form_data,
        )
    if not expiry_date.strip():
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["Please enter an expiry date."],
            form_data,
        )
    try:
        posting_user_id = int(posted_by_id)
    except (TypeError, ValueError):
        posting_user_id = None
    if posting_user_id is None or db.get(AppUser, posting_user_id) is None:
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["Please select the person posting this receipt from the Acting as menu."],
            form_data,
        )

    try:
        physical_quantity = parse_quantity(physical_quantity, "physical quantity")
        accepted_quantity = parse_quantity(accepted_quantity, "accepted quantity")
        damaged_quantity = parse_quantity(damaged_quantity, "damaged quantity")
        missing_quantity = parse_quantity(missing_quantity, "missing quantity")
    except HTTPException as exc:
        return receipt_form_response(
            request,
            db,
            purchase_order,
            friendly_error_messages(exc.detail),
            form_data,
        )

    try:
        validate_receipt_quantities(
            physical_quantity,
            accepted_quantity,
            damaged_quantity,
            missing_quantity,
            purchase_order.quantity,
        )
    except HTTPException as exc:
        return receipt_form_response(
            request,
            db,
            purchase_order,
            friendly_error_messages(exc.detail),
            form_data,
        )

    receipt = GoodsReceiptNote(
        document_no=next_document_number(db, GoodsReceiptNote, "document_no", "GRN"),
        po_id=purchase_order.id,
        batch_number=batch_number.strip(),
        expiry_date=expiry_date,
        physical_quantity=physical_quantity,
        accepted_quantity=accepted_quantity,
        damaged_quantity=damaged_quantity,
        missing_quantity=missing_quantity,
        posted_by_id=posting_user_id,
    )
    db.add(receipt)
    db.flush()

    db.add_all(
        [
            StockLedgerEntry(
                location_id=purchase_order.delivery_location_id,
                product_id=purchase_order.product_id,
                batch_number=receipt.batch_number,
                txn_type=LedgerTxnType.RECEIPT,
                stock_status=StockStatus.USABLE,
                quantity_in=accepted_quantity,
                quantity_out=0,
                reference_document=receipt.document_no,
                performed_by_id=posting_user_id,
            ),
            StockLedgerEntry(
                location_id=purchase_order.delivery_location_id,
                product_id=purchase_order.product_id,
                batch_number=receipt.batch_number,
                txn_type=LedgerTxnType.DAMAGE,
                stock_status=StockStatus.QUARANTINED,
                quantity_in=damaged_quantity,
                quantity_out=0,
                reference_document=receipt.document_no,
                performed_by_id=posting_user_id,
            ),
        ]
    )
    purchase_order.status = (
        PurchaseOrderStatus.CLOSED
        if accepted_quantity == purchase_order.quantity
        else PurchaseOrderStatus.PARTIALLY_RECEIVED
    )
    db.commit()
    return RedirectResponse(
        url=success_redirect("/goods-receipts", f"{receipt.document_no} posted"),
        status_code=303,
    )


@router.get("/{receipt_id}/correct", response_class=HTMLResponse)
def correct_goods_receipt_form(
    receipt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    receipt = get_goods_receipt_or_404(db, receipt_id)
    if get_correction_for_receipt(db, receipt.id):
        raise HTTPException(
            status_code=422,
            detail="This goods receipt already has a correction.",
        )

    return correction_form_response(
        request,
        db,
        receipt,
        [],
        correction_form_data(
            accepted_quantity=receipt.accepted_quantity,
            damaged_quantity=receipt.damaged_quantity,
            missing_quantity=receipt.missing_quantity,
        ),
        status_code=200,
    )


@router.post("/{receipt_id}/correct")
def correct_goods_receipt(
    receipt_id: int,
    request: Request,
    accepted_quantity: str = Form(""),
    damaged_quantity: str = Form(""),
    missing_quantity: str = Form(""),
    reason: str = Form(""),
    corrected_by_id: str = Form(""),
    db: Session = Depends(get_db),
):
    receipt = get_goods_receipt_or_404(db, receipt_id)
    purchase_order = receipt.purchase_order
    form_data = correction_form_data(
        accepted_quantity,
        damaged_quantity,
        missing_quantity,
        reason,
        corrected_by_id,
    )

    if get_correction_for_receipt(db, receipt.id):
        return correction_form_response(
            request,
            db,
            receipt,
            ["This goods receipt already has a correction."],
            form_data,
        )
    if not reason.strip():
        return correction_form_response(
            request,
            db,
            receipt,
            ["Please enter a reason for this correction."],
            form_data,
        )

    try:
        correcting_user_id = int(corrected_by_id)
    except (TypeError, ValueError):
        correcting_user_id = None
    if correcting_user_id is None or db.get(AppUser, correcting_user_id) is None:
        return correction_form_response(
            request,
            db,
            receipt,
            ["Please select the person posting this correction from the Acting as menu."],
            form_data,
        )

    try:
        new_accepted_quantity = parse_quantity(accepted_quantity, "accepted quantity")
        new_damaged_quantity = parse_quantity(damaged_quantity, "damaged quantity")
        new_missing_quantity = parse_quantity(missing_quantity, "missing quantity")
    except HTTPException as exc:
        return correction_form_response(
            request,
            db,
            receipt,
            friendly_error_messages(exc.detail),
            form_data,
        )

    try:
        validate_receipt_quantities(
            receipt.physical_quantity,
            new_accepted_quantity,
            new_damaged_quantity,
            new_missing_quantity,
            purchase_order.quantity,
        )
    except HTTPException as exc:
        return correction_form_response(
            request,
            db,
            receipt,
            friendly_error_messages(exc.detail),
            form_data,
        )

    old_accepted_quantity = receipt.accepted_quantity
    old_damaged_quantity = receipt.damaged_quantity
    old_missing_quantity = receipt.missing_quantity
    correction = GrnCorrection(
        original_grn_id=receipt.id,
        old_accepted_quantity=old_accepted_quantity,
        old_damaged_quantity=old_damaged_quantity,
        old_missing_quantity=old_missing_quantity,
        new_accepted_quantity=new_accepted_quantity,
        new_damaged_quantity=new_damaged_quantity,
        new_missing_quantity=new_missing_quantity,
        reason=reason.strip(),
        corrected_by_id=correcting_user_id,
    )
    db.add(correction)

    usable_delta = new_accepted_quantity - old_accepted_quantity
    quarantined_delta = new_damaged_quantity - old_damaged_quantity
    db.add_all(
        [
            StockLedgerEntry(
                location_id=purchase_order.delivery_location_id,
                product_id=purchase_order.product_id,
                batch_number=receipt.batch_number,
                txn_type=LedgerTxnType.CORRECTION,
                stock_status=StockStatus.USABLE,
                quantity_in=max(usable_delta, 0),
                quantity_out=abs(min(usable_delta, 0)),
                reference_document=receipt.document_no,
                performed_by_id=correcting_user_id,
            ),
            StockLedgerEntry(
                location_id=purchase_order.delivery_location_id,
                product_id=purchase_order.product_id,
                batch_number=receipt.batch_number,
                txn_type=LedgerTxnType.CORRECTION,
                stock_status=StockStatus.QUARANTINED,
                quantity_in=max(quarantined_delta, 0),
                quantity_out=abs(min(quarantined_delta, 0)),
                reference_document=receipt.document_no,
                performed_by_id=correcting_user_id,
            ),
        ]
    )
    purchase_order.status = (
        PurchaseOrderStatus.CLOSED
        if new_accepted_quantity == purchase_order.quantity
        else PurchaseOrderStatus.PARTIALLY_RECEIVED
    )
    db.commit()
    return RedirectResponse(
        url=success_redirect(
            f"/goods-receipts/{receipt.id}", f"{receipt.document_no} corrected"
        ),
        status_code=303,
    )


@router.get("/{receipt_id}", response_class=HTMLResponse)
def goods_receipt_detail(
    receipt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    receipt = get_goods_receipt_or_404(db, receipt_id)
    purchase_order = receipt.purchase_order
    context = header_context(db)
    context.update(
        {
            "goods_receipt": receipt,
            "correction": get_correction_for_receipt(db, receipt.id),
            "usable_stock": computed_stock(
                db,
                location_id=purchase_order.delivery_location_id,
                product_id=purchase_order.product_id,
                batch_number=receipt.batch_number,
                stock_status=StockStatus.USABLE,
            ),
            "quarantined_stock": computed_stock(
                db,
                location_id=purchase_order.delivery_location_id,
                product_id=purchase_order.product_id,
                batch_number=receipt.batch_number,
                stock_status=StockStatus.QUARANTINED,
            ),
        }
    )
    return templates.TemplateResponse(request, "goods_receipts_detail.html", context)
