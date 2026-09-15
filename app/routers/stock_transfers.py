import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import create_notification, get_acting_user, header_context, scoped_location_ids, success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    AppUser,
    LedgerTxnType,
    Location,
    Product,
    StockLedgerEntry,
    StockStatus,
    StockTransfer,
    StockTransferStatus,
    UserRole,
)
from app.stock import computed_stock, usable_batches_at

router = APIRouter(prefix="/transfers", tags=["stock-transfers"])
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_transfer_or_404(db: Session, transfer_id: int) -> StockTransfer:
    transfer = db.get(StockTransfer, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Stock transfer not found")
    return transfer


def transfer_form_response(
    request: Request,
    db: Session,
    error_messages: list,
    form_data: dict,
    status_code: int = 422,
):
    """Render the new-transfer form with error messages and pre-populated fields."""
    ctx = header_context(db, request)
    locations = db.query(Location).order_by(Location.id).all()
    products = db.query(Product).order_by(Product.id).all()

    # Recompute batch options for chosen source/product
    source_location_id = form_data.get("source_location_id")
    product_id = form_data.get("product_id")
    batches = []
    if source_location_id and product_id:
        try:
            batches = usable_batches_at(db, int(source_location_id), int(product_id))
        except (ValueError, TypeError):
            pass

    ctx.update(
        {
            "locations": locations,
            "products": products,
            "batches": batches,
            "form_data": form_data,
            "error_messages": error_messages,
        }
    )
    return templates.TemplateResponse(
        request, "transfers_new.html", ctx, status_code=status_code
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_transfers(request: Request, db: Session = Depends(get_db)):
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    query = db.query(StockTransfer).order_by(StockTransfer.id.desc())
    if loc_ids is not None:
        query = query.filter(
            (StockTransfer.source_location_id.in_(loc_ids))
            | (StockTransfer.destination_location_id.in_(loc_ids))
        )
    ctx["transfers"] = query.all()
    return templates.TemplateResponse(request, "transfers_list.html", ctx)


@router.get("/new", response_class=HTMLResponse)
def new_transfer_form(
    request: Request,
    source_location_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
):
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    if acting_user and acting_user.role == UserRole.BRANCH_STAFF and acting_user.home_location_id:
        source_location_id = acting_user.home_location_id

    locations = db.query(Location).order_by(Location.id).all()
    products = db.query(Product).order_by(Product.id).all()

    batches = []
    if source_location_id is not None and product_id is not None:
        batches = usable_batches_at(db, source_location_id, product_id)

    ctx.update(
        {
            "locations": locations,
            "products": products,
            "batches": batches,
            "form_data": {
                "source_location_id": source_location_id or "",
                "destination_location_id": "",
                "product_id": product_id or "",
                "batch_number": "",
                "quantity": "",
                "dispatched_by_id": "",
            },
            "error_messages": [],
        }
    )
    return templates.TemplateResponse(request, "transfers_new.html", ctx)


@router.post("/new")
def create_transfer(
    request: Request,
    source_location_id: str = Form(""),
    destination_location_id: str = Form(""),
    product_id: str = Form(""),
    batch_number: str = Form(""),
    quantity: str = Form(""),
    dispatched_by_id: str = Form(""),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if acting_user and acting_user.role == UserRole.BRANCH_STAFF and acting_user.home_location_id:
        source_location_id = str(acting_user.home_location_id)

    form_data = {
        "source_location_id": source_location_id,
        "destination_location_id": destination_location_id,
        "product_id": product_id,
        "batch_number": batch_number,
        "quantity": quantity,
        "dispatched_by_id": dispatched_by_id,
    }

    # --- Parse IDs --------------------------------------------------------
    def parse_int(value, label):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    src_id = parse_int(source_location_id, "source location")
    dst_id = parse_int(destination_location_id, "destination location")
    prod_id = parse_int(product_id, "product")
    by_id = parse_int(dispatched_by_id, "dispatched by")
    if by_id is None and acting_user:
        by_id = acting_user.id

    errors = []

    if src_id is None:
        errors.append("Please select a source location.")
    if dst_id is None:
        errors.append("Please select a destination location.")
    if prod_id is None:
        errors.append("Please select a product.")
    if not batch_number.strip():
        errors.append("Please select a batch number.")
    if by_id is None or db.get(AppUser, by_id) is None:
        errors.append("Please select the person dispatching this transfer.")

    qty = None
    try:
        qty = int(quantity)
        if qty <= 0:
            errors.append("Quantity must be greater than zero.")
    except (TypeError, ValueError):
        errors.append("Please enter a whole number for quantity.")

    if errors:
        return transfer_form_response(request, db, errors, form_data)

    # --- Business rule: source ≠ destination ------------------------------
    if src_id == dst_id:
        return transfer_form_response(
            request,
            db,
            ["Source and destination locations must be different."],
            form_data,
        )

    # --- Validate locations and product exist -----------------------------
    src_loc = db.get(Location, src_id)
    dst_loc = db.get(Location, dst_id)
    product = db.get(Product, prod_id)
    if src_loc is None:
        errors.append("Source location not found.")
    if dst_loc is None:
        errors.append("Destination location not found.")
    if product is None:
        errors.append("Product not found.")
    if errors:
        return transfer_form_response(request, db, errors, form_data)

    # --- Server-side stock check (never trust the client max) -------------
    available_qty = computed_stock(
        db,
        location_id=src_id,
        product_id=prod_id,
        batch_number=batch_number.strip(),
        stock_status=StockStatus.USABLE,
    )
    if available_qty <= 0:
        return transfer_form_response(
            request,
            db,
            [
                f"Batch {batch_number.strip()!r} has no usable stock at {src_loc.name}. "
                f"It may be fully quarantined or does not exist at that location."
            ],
            form_data,
        )
    if qty > available_qty:
        return transfer_form_response(
            request,
            db,
            [
                f"Requested quantity ({qty}) exceeds usable stock for batch "
                f"{batch_number.strip()!r} at {src_loc.name} ({available_qty} available)."
            ],
            form_data,
        )

    # --- Create the StockTransfer row ------------------------------------
    transfer = StockTransfer(
        document_no=next_document_number(db, StockTransfer, "document_no", "STN"),
        source_location_id=src_id,
        destination_location_id=dst_id,
        product_id=prod_id,
        batch_number=batch_number.strip(),
        quantity=qty,
        status=StockTransferStatus.DISPATCHED,
        dispatched_by_id=by_id,
        dispatched_at=datetime.datetime.utcnow(),
    )
    db.add(transfer)
    db.flush()  # get id / doc_no before posting ledger

    # --- Post TRANSFER_OUT ledger entry at the source location -----------
    db.add(
        StockLedgerEntry(
            location_id=src_id,
            product_id=prod_id,
            batch_number=batch_number.strip(),
            txn_type=LedgerTxnType.TRANSFER_OUT,
            stock_status=StockStatus.USABLE,
            quantity_in=0,
            quantity_out=qty,
            reference_document=transfer.document_no,
            performed_by_id=by_id,
        )
    )

    # --- Notify Destination Location Staff ---
    create_notification(
        db=db,
        title=f"Incoming Transfer {transfer.document_no}",
        message=f"{src_loc.name} dispatched {qty}x {product.name} (Batch: {batch_number.strip()}) to {dst_loc.name}",
        link=f"/transfers/{transfer.id}",
        target_location_id=dst_id,
        company_id=acting_user.company_id if acting_user else None,
        icon_type="transfer",
    )

    db.commit()
    return RedirectResponse(
        url=success_redirect("/transfers", f"{transfer.document_no} dispatched"),
        status_code=303,
    )


@router.post("/{transfer_id}/receive")
def receive_transfer(
    transfer_id: int,
    request: Request,
    received_by_id: str = Form(""),
    db: Session = Depends(get_db),
):
    transfer = get_transfer_or_404(db, transfer_id)
    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None:
        if (
            transfer.source_location_id not in loc_ids
            and transfer.destination_location_id not in loc_ids
        ):
            raise HTTPException(
                status_code=403, detail="Forbidden: You do not have access to this transfer"
            )

    if acting_user and acting_user.role == UserRole.BRANCH_STAFF:
        if acting_user.home_location_id != transfer.destination_location_id:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Only staff at the destination branch or Central/Admin users can confirm receipt.",
            )

    if transfer.status != StockTransferStatus.DISPATCHED:
        raise HTTPException(
            status_code=422,
            detail=f"Transfer {transfer.document_no} has already been received.",
        )

    try:
        by_id = int(received_by_id)
    except (TypeError, ValueError):
        by_id = acting_user.id if acting_user else None

    if by_id is None or db.get(AppUser, by_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Please select the person confirming receipt.",
        )

    transfer.received_by_id = by_id
    transfer.received_at = datetime.datetime.utcnow()
    transfer.status = StockTransferStatus.RECEIVED

    # --- Post TRANSFER_IN ledger entry at the destination location -------
    db.add(
        StockLedgerEntry(
            location_id=transfer.destination_location_id,
            product_id=transfer.product_id,
            batch_number=transfer.batch_number,
            txn_type=LedgerTxnType.TRANSFER_IN,
            stock_status=StockStatus.USABLE,
            quantity_in=transfer.quantity,
            quantity_out=0,
            reference_document=transfer.document_no,
            performed_by_id=by_id,
        )
    )

    # --- Notify Source Location / Dispatcher ---
    create_notification(
        db=db,
        title=f"Transfer Received {transfer.document_no}",
        message=f"Transfer {transfer.document_no} ({transfer.quantity}x {transfer.product.name}) received at {transfer.destination_location.name}",
        link=f"/transfers/{transfer.id}",
        user_id=transfer.dispatched_by_id,
        company_id=acting_user.company_id if acting_user else None,
        icon_type="check",
    )

    db.commit()
    return RedirectResponse(
        url=success_redirect("/transfers", f"{transfer.document_no} received"),
        status_code=303,
    )


from app.models import GoodsReceiptNote
from app.traceability import build_chain


from app.pdf_export import stock_transfer_pdf
from app.image_export import pdf_bytes_to_png


@router.get("/{transfer_id}/image")
def download_stock_transfer_image(
    transfer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    transfer = get_transfer_or_404(db, transfer_id)
    if loc_ids is not None:
        if (
            transfer.source_location_id not in loc_ids
            and transfer.destination_location_id not in loc_ids
        ):
            raise HTTPException(
                status_code=403, detail="Forbidden: You do not have access to this transfer"
            )

    pdf_bytes = stock_transfer_pdf(transfer)
    status_str = transfer.status.value if hasattr(transfer.status, "value") else str(transfer.status)
    dispatched_at_str = transfer.dispatched_at.strftime("%Y-%m-%d %H:%M") if transfer.dispatched_at else "-"
    rows = [
        ("Source Location", transfer.source_location.name),
        ("Destination Location", transfer.destination_location.name),
        ("Product", transfer.product.name),
        ("Batch Number", transfer.batch_number),
        ("Quantity", str(transfer.quantity)),
        ("Status", status_str),
        ("Dispatched By", transfer.dispatched_by.name),
        ("Dispatched At", dispatched_at_str),
        ("Received By", transfer.received_by.name if transfer.received_by else "-"),
        ("Received At", transfer.received_at.strftime("%Y-%m-%d %H:%M") if transfer.received_at else "-"),
    ]
    png_bytes = pdf_bytes_to_png(pdf_bytes, "STOCK TRANSFER NOTE", transfer.document_no, rows)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{transfer.document_no}.png"'},
    )


@router.get("/{transfer_id}", response_class=HTMLResponse)
def transfer_detail(
    transfer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    transfer = get_transfer_or_404(db, transfer_id)
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None:
        if (
            transfer.source_location_id not in loc_ids
            and transfer.destination_location_id not in loc_ids
        ):
            raise HTTPException(
                status_code=403, detail="Forbidden: You do not have access to this transfer"
            )

    ctx["transfer"] = transfer
    grn = (
        db.query(GoodsReceiptNote)
        .filter(GoodsReceiptNote.batch_number == transfer.batch_number)
        .first()
    )
    if grn and grn.purchase_order:
        ctx["chain_steps"] = build_chain(db, grn.purchase_order.requisition_id)
    return templates.TemplateResponse(request, "transfers_detail.html", ctx)
