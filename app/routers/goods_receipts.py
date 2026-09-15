import os
import time
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
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
    AppUser,
    GoodsReceiptNote,
    GrnCorrection,
    LedgerTxnType,
    PurchaseOrder,
    PurchaseOrderStatus,
    StockLedgerEntry,
    StockStatus,
    SupplierInvoice,
    UserRole,
)
from app.pdf_export import grn_pdf
from app.image_export import pdf_bytes_to_png
from app.stock import computed_stock

router = APIRouter(prefix="/goods-receipts", tags=["goods-receipts"])
templates = Jinja2Templates(directory="templates")

UPLOADS_DIR = "static/uploads/damage-photos"


def process_damage_photo(damage_photo: UploadFile | None, document_no: str) -> str | None:
    if not damage_photo or not damage_photo.filename:
        return None
    if not damage_photo.content_type or not damage_photo.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Damage photo must be an image file.")

    content = damage_photo.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Damage photo must be under 5MB.")

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    ext = os.path.splitext(damage_photo.filename)[1] or ".jpg"
    filename = f"{document_no}-{int(time.time())}{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    return f"uploads/damage-photos/{filename}"


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
    context = header_context(db, request)
    acting_user = context["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)

    query = db.query(GoodsReceiptNote).order_by(GoodsReceiptNote.id)
    if loc_ids is not None:
        query = query.join(PurchaseOrder).filter(PurchaseOrder.delivery_location_id.in_(loc_ids))

    context["goods_receipts"] = query.all()
    return templates.TemplateResponse(request, "goods_receipts_list.html", context)


def is_authorized_to_receive_po(acting_user: AppUser | None, po: PurchaseOrder) -> bool:
    if not acting_user:
        return False
    if acting_user.role in (UserRole.RECEIVING_STAFF, UserRole.CENTRAL_PURCHASING, UserRole.COMPANY_ADMIN):
        return True
    if acting_user.role == UserRole.BRANCH_STAFF and acting_user.home_location_id == po.delivery_location_id:
        return True
    return False


@router.get("/new", response_class=HTMLResponse)
def new_goods_receipt_form(
    po_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    purchase_order = get_purchase_order_or_404(db, po_id)
    if not is_authorized_to_receive_po(acting_user, purchase_order):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Receiving Staff, Central Purchasing, Company Admin, or Branch Staff assigned to the delivery branch can receive goods.",
        )
    context = header_context(db, request)
    context.update(
        {
            "purchase_order": purchase_order,
            "error_messages": [],
            "form_data": receipt_form_data(),
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
    damage_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request, acting_as_id=posted_by_id)
    purchase_order = get_purchase_order_or_404(db, po_id)
    if not is_authorized_to_receive_po(acting_user, purchase_order):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Receiving Staff, Central Purchasing, Company Admin, or Branch Staff assigned to the delivery branch can receive goods.",
        )
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")
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
        posting_user_id = acting_user.id if acting_user else None
    if posting_user_id is None or db.get(AppUser, posting_user_id) is None:
        return receipt_form_response(
            request,
            db,
            purchase_order,
            ["Please select the person receiving this shipment."],
            form_data,
        )

    try:
        parsed_physical_quantity = parse_quantity(physical_quantity, "physical quantity")
        parsed_accepted_quantity = parse_quantity(accepted_quantity, "accepted quantity")
        parsed_damaged_quantity = parse_quantity(damaged_quantity, "damaged quantity")
        parsed_missing_quantity = parse_quantity(missing_quantity, "missing quantity")
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
            parsed_physical_quantity,
            parsed_accepted_quantity,
            parsed_damaged_quantity,
            parsed_missing_quantity,
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

    doc_no = next_document_number(db, GoodsReceiptNote, "document_no", "GRN")
    photo_path = None
    if damage_photo and damage_photo.filename:
        try:
            photo_path = process_damage_photo(damage_photo, doc_no)
        except HTTPException as exc:
            return receipt_form_response(
                request,
                db,
                purchase_order,
                friendly_error_messages(exc.detail),
                form_data,
            )

    receipt = GoodsReceiptNote(
        document_no=doc_no,
        po_id=purchase_order.id,
        batch_number=batch_number.strip(),
        expiry_date=expiry_date,
        physical_quantity=parsed_physical_quantity,
        accepted_quantity=parsed_accepted_quantity,
        damaged_quantity=parsed_damaged_quantity,
        missing_quantity=parsed_missing_quantity,
        photo_path=photo_path,
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
    acting_user = get_acting_user(db, request)
    if not acting_user or acting_user.role not in (UserRole.RECEIVING_STAFF, UserRole.CENTRAL_PURCHASING, UserRole.COMPANY_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Receiving Staff, Central Purchasing, or Company Admin can record GRN corrections.",
        )
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
    damage_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request, acting_as_id=corrected_by_id)
    if not acting_user or acting_user.role not in (UserRole.RECEIVING_STAFF, UserRole.CENTRAL_PURCHASING, UserRole.COMPANY_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only Receiving Staff, Central Purchasing, or Company Admin can record GRN corrections.",
        )
    receipt = get_goods_receipt_or_404(db, receipt_id)
    purchase_order = receipt.purchase_order
    acting_user = get_acting_user(db, request, acting_as_id=corrected_by_id)
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")
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
        correcting_user_id = acting_user.id if acting_user else None
    if correcting_user_id is None or db.get(AppUser, correcting_user_id) is None:
        return correction_form_response(
            request,
            db,
            receipt,
            ["Please select the person posting this correction."],
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

    photo_path = None
    if damage_photo and damage_photo.filename:
        try:
            photo_path = process_damage_photo(damage_photo, f"CORR-{receipt.document_no}")
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
        photo_path=photo_path,
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


from app.traceability import build_chain


@router.get("/{receipt_id}", response_class=HTMLResponse)
def goods_receipt_detail(
    receipt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    receipt = get_goods_receipt_or_404(db, receipt_id)
    purchase_order = receipt.purchase_order
    context = header_context(db, request)
    acting_user = context["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)

    if loc_ids is not None and purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    context.update(
        {
            "goods_receipt": receipt,
            "correction": get_correction_for_receipt(db, receipt.id),
            "supplier_invoice": (
                db.query(SupplierInvoice)
                .filter(SupplierInvoice.grn_id == receipt.id)
                .first()
            ),
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
            "chain_steps": build_chain(db, purchase_order.requisition_id),
        }
    )
    return templates.TemplateResponse(
        request, "goods_receipts_detail.html", context
    )


@router.get("/{receipt_id}/image")
def download_goods_receipt_image(
    receipt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    receipt = get_goods_receipt_or_404(db, receipt_id)
    if loc_ids is not None and receipt.purchase_order.delivery_location_id not in loc_ids:
        raise HTTPException(status_code=403, detail="Access denied for this branch")

    correction = get_correction_for_receipt(db, receipt.id)
    pdf_bytes = grn_pdf(receipt, correction)
    posted_at_str = receipt.posted_at.strftime("%Y-%m-%d %H:%M") if receipt.posted_at else "-"
    rows = [
        ("Purchase Order", receipt.purchase_order.document_no),
        ("Supplier", receipt.purchase_order.supplier.name),
        ("Product", receipt.purchase_order.product.name),
        ("Location", receipt.purchase_order.delivery_location.name),
        ("Batch Number", receipt.batch_number),
        ("Expiry Date", receipt.expiry_date),
        ("Physical Quantity", str(receipt.physical_quantity)),
        ("Accepted Quantity", str(receipt.accepted_quantity)),
        ("Damaged Quantity", str(receipt.damaged_quantity)),
        ("Missing Quantity", str(receipt.missing_quantity)),
        ("Posted By", receipt.posted_by.name),
        ("Posted At", posted_at_str),
    ]
    if correction:
        rows.append(("Correction Reason", correction.reason))
        rows.append(("Corrected Accepted", str(correction.new_accepted_quantity)))
        rows.append(("Corrected Damaged", str(correction.new_damaged_quantity)))
    png_bytes = pdf_bytes_to_png(pdf_bytes, "GOODS RECEIPT NOTE", receipt.document_no, rows)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{receipt.document_no}.png"'},
    )
