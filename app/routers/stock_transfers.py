import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context, success_redirect
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
    ctx = header_context(db)
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
    ctx = header_context(db)
    ctx["transfers"] = (
        db.query(StockTransfer).order_by(StockTransfer.id.desc()).all()
    )
    return templates.TemplateResponse(request, "transfers_list.html", ctx)


@router.get("/new", response_class=HTMLResponse)
def new_transfer_form(
    request: Request,
    source_location_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
):
    locations = db.query(Location).order_by(Location.id).all()
    products = db.query(Product).order_by(Product.id).all()

    batches = []
    if source_location_id is not None and product_id is not None:
        batches = usable_batches_at(db, source_location_id, product_id)

    ctx = header_context(db)
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
        errors.append("Please select the person dispatching this transfer from the Acting as menu.")

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
    db.commit()
    return RedirectResponse(
        url=success_redirect("/transfers", f"{transfer.document_no} dispatched"),
        status_code=303,
    )


@router.post("/{transfer_id}/receive")
def receive_transfer(
    transfer_id: int,
    received_by_id: str = Form(""),
    db: Session = Depends(get_db),
):
    transfer = get_transfer_or_404(db, transfer_id)

    if transfer.status != StockTransferStatus.DISPATCHED:
        raise HTTPException(
            status_code=422,
            detail=f"Transfer {transfer.document_no} has already been received.",
        )

    try:
        by_id = int(received_by_id)
    except (TypeError, ValueError):
        by_id = None

    if by_id is None or db.get(AppUser, by_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Please select the person confirming receipt from the Acting as menu.",
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
    db.commit()
    return RedirectResponse(
        url=success_redirect("/transfers", f"{transfer.document_no} received"),
        status_code=303,
    )


@router.get("/{transfer_id}", response_class=HTMLResponse)
def transfer_detail(
    transfer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    transfer = get_transfer_or_404(db, transfer_id)
    ctx = header_context(db)
    ctx["transfer"] = transfer
    return templates.TemplateResponse(request, "transfers_detail.html", ctx)
