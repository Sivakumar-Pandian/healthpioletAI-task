import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import get_acting_user, header_context, scoped_location_ids, success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    AppUser,
    LedgerTxnType,
    Location,
    Product,
    SalesInvoice,
    StockLedgerEntry,
    StockStatus,
    UserRole,
)
from app.stock import all_batches_at, computed_stock

router = APIRouter(prefix="/dispensing", tags=["dispensing"])
templates = Jinja2Templates(directory="templates")

PAYMENT_MODES = ["Cash", "Card", "Insurance"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_sale_or_404(db: Session, sale_id: int) -> SalesInvoice:
    sale = db.get(SalesInvoice, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Sales invoice not found")
    return sale


def dispensing_form_context(
    db: Session,
    form_data: dict,
    error_messages: list,
):
    """Build the full template context for GET and re-render-on-error cases."""
    locations = db.query(Location).order_by(Location.id).all()
    products = db.query(Product).order_by(Product.id).all()

    # Recompute batch options for chosen location/product
    loc_id = form_data.get("location_id")
    prod_id = form_data.get("product_id")
    batches = []  # list of (batch_number, usable_qty, quarantined_qty)
    selected_product = None
    if loc_id and prod_id:
        try:
            batches = all_batches_at(db, int(loc_id), int(prod_id))
        except (ValueError, TypeError):
            pass
        try:
            selected_product = db.get(Product, int(prod_id))
        except (ValueError, TypeError):
            pass

    return {
        "locations": locations,
        "products": products,
        "batches": batches,
        "selected_product": selected_product,
        "payment_modes": PAYMENT_MODES,
        "form_data": form_data,
        "error_messages": error_messages,
    }


def dispensing_form_response(
    request: Request,
    db: Session,
    error_messages: list,
    form_data: dict,
    status_code: int = 422,
):
    ctx = header_context(db, request)
    ctx.update(dispensing_form_context(db, form_data, error_messages))
    return templates.TemplateResponse(
        request, "dispensing_new.html", ctx, status_code=status_code
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_dispensing(request: Request, db: Session = Depends(get_db)):
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    query = db.query(SalesInvoice).order_by(SalesInvoice.id.desc())
    if loc_ids is not None:
        query = query.filter(SalesInvoice.location_id.in_(loc_ids))
    ctx["sales"] = query.all()
    return templates.TemplateResponse(request, "dispensing_list.html", ctx)


@router.get("/new", response_class=HTMLResponse)
def new_dispensing_form(
    request: Request,
    location_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
):
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    if acting_user and acting_user.role == UserRole.BRANCH_STAFF and acting_user.home_location_id:
        location_id = acting_user.home_location_id
    elif location_id is None:
        first_loc = db.query(Location).order_by(Location.id).first()
        location_id = first_loc.id if first_loc else None

    # Pre-fetch product defaults
    selected_product = None
    if product_id is not None:
        selected_product = db.get(Product, product_id)

    batches = []
    if location_id is not None and product_id is not None:
        batches = all_batches_at(db, location_id, product_id)

    ctx.update(
        {
            "locations": db.query(Location).order_by(Location.id).all(),
            "products": db.query(Product).order_by(Product.id).all(),
            "batches": batches,
            "selected_product": selected_product,
            "payment_modes": PAYMENT_MODES,
            "form_data": {
                "location_id": location_id or "",
                "product_id": product_id or "",
                "batch_number": "",
                "quantity": "",
                "unit_price": selected_product.purchase_price if selected_product else "",
                "tax_percent": selected_product.tax_percent if selected_product else "",
                "payment_mode": "Cash",
                "prescription_reference": "",
                "dispensed_by_id": "",
            },
            "error_messages": [],
        }
    )
    return templates.TemplateResponse(request, "dispensing_new.html", ctx)


@router.post("/new")
def create_dispensing(
    request: Request,
    location_id: str = Form(""),
    product_id: str = Form(""),
    batch_number: str = Form(""),
    quantity: str = Form(""),
    unit_price: str = Form(""),
    tax_percent: str = Form(""),
    payment_mode: str = Form(""),
    prescription_reference: str = Form(""),
    dispensed_by_id: str = Form(""),
    db: Session = Depends(get_db),
):
    acting_user = get_acting_user(db, request)
    if acting_user and acting_user.role == UserRole.BRANCH_STAFF and acting_user.home_location_id:
        location_id = str(acting_user.home_location_id)

    form_data = {
        "location_id": location_id,
        "product_id": product_id,
        "batch_number": batch_number,
        "quantity": quantity,
        "unit_price": unit_price,
        "tax_percent": tax_percent,
        "payment_mode": payment_mode,
        "prescription_reference": prescription_reference,
        "dispensed_by_id": dispensed_by_id,
    }

    # --- Parse IDs --------------------------------------------------------
    def parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def parse_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    loc_id = parse_int(location_id)
    prod_id = parse_int(product_id)
    by_id = parse_int(dispensed_by_id)
    if by_id is None and acting_user:
        by_id = acting_user.id

    errors = []

    if loc_id is None:
        errors.append("Please select a dispensing location.")
    if prod_id is None:
        errors.append("Please select a product.")
    if not batch_number.strip():
        errors.append("Please select a batch number.")
    if by_id is None or db.get(AppUser, by_id) is None:
        errors.append(
            "Please select the person dispensing."
        )

    qty = parse_int(quantity)
    if qty is None:
        errors.append("Please enter a whole number for quantity.")
    elif qty <= 0:
        errors.append("Quantity must be greater than zero.")

    unit_price_f = parse_float(unit_price)
    if unit_price_f is None or unit_price_f < 0:
        errors.append("Please enter a valid unit price (≥ 0).")

    tax_pct_f = parse_float(tax_percent)
    if tax_pct_f is None or tax_pct_f < 0:
        errors.append("Please enter a valid tax percent (≥ 0).")

    if payment_mode not in PAYMENT_MODES:
        errors.append(f"Payment mode must be one of: {', '.join(PAYMENT_MODES)}.")

    if errors:
        return dispensing_form_response(request, db, errors, form_data)

    # --- Validate location and product exist ------------------------------
    location = db.get(Location, loc_id)
    product = db.get(Product, prod_id)
    if location is None:
        errors.append("Location not found.")
    if product is None:
        errors.append("Product not found.")
    if errors:
        return dispensing_form_response(request, db, errors, form_data)

    # --- Server-side stock check (never trust client max) ----------------
    available_qty = computed_stock(
        db,
        location_id=loc_id,
        product_id=prod_id,
        batch_number=batch_number.strip(),
        stock_status=StockStatus.USABLE,
    )
    if available_qty <= 0:
        return dispensing_form_response(
            request,
            db,
            [
                f"Batch {batch_number.strip()!r} has no usable stock at {location.name}. "
                f"It may be fully quarantined or does not exist at that location."
            ],
            form_data,
        )
    if qty > available_qty:
        return dispensing_form_response(
            request,
            db,
            [
                f"Requested quantity ({qty}) exceeds usable stock for batch "
                f"{batch_number.strip()!r} at {location.name} ({available_qty} available)."
            ],
            form_data,
        )

    # --- Server-side financial computation --------------------------------
    value_before_tax = round(qty * unit_price_f, 2)
    tax_amount = round(value_before_tax * tax_pct_f / 100, 2)
    total_amount = round(value_before_tax + tax_amount, 2)
    cost_of_goods = round(qty * product.purchase_price, 2)

    # --- Save SalesInvoice -----------------------------------------------
    sale = SalesInvoice(
        document_no=next_document_number(db, SalesInvoice, "document_no", "SALE"),
        location_id=loc_id,
        product_id=prod_id,
        batch_number=batch_number.strip(),
        quantity=qty,
        unit_price=unit_price_f,
        tax_percent=tax_pct_f,
        value_before_tax=value_before_tax,
        tax_amount=tax_amount,
        total_amount=total_amount,
        cost_of_goods=cost_of_goods,
        payment_mode=payment_mode,
        prescription_reference=prescription_reference.strip() or None,
        dispensed_by_id=by_id,
        dispensed_at=datetime.datetime.utcnow(),
    )
    db.add(sale)
    db.flush()  # populate sale.document_no before ledger

    # --- Post ISSUE ledger entry -----------------------------------------
    db.add(
        StockLedgerEntry(
            location_id=loc_id,
            product_id=prod_id,
            batch_number=batch_number.strip(),
            txn_type=LedgerTxnType.ISSUE,
            stock_status=StockStatus.USABLE,
            quantity_in=0,
            quantity_out=qty,
            reference_document=sale.document_no,
            performed_by_id=by_id,
        )
    )
    db.commit()
    return RedirectResponse(
        url=success_redirect("/dispensing", f"{sale.document_no} recorded"),
        status_code=303,
    )


from app.models import GoodsReceiptNote
from app.traceability import build_chain


@router.get("/{sale_id}", response_class=HTMLResponse)
def dispensing_detail(
    sale_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    sale = get_sale_or_404(db, sale_id)
    ctx = header_context(db, request)
    acting_user = ctx["acting_user"]
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and sale.location_id not in loc_ids:
        raise HTTPException(
            status_code=403, detail="Forbidden: You do not have access to this sales invoice"
        )

    ctx["sale"] = sale
    grn = (
        db.query(GoodsReceiptNote)
        .filter(GoodsReceiptNote.batch_number == sale.batch_number)
        .first()
    )
    if grn and grn.purchase_order:
        ctx["chain_steps"] = build_chain(db, grn.purchase_order.requisition_id)
    return templates.TemplateResponse(request, "dispensing_detail.html", ctx)


from fastapi import Response
from app.pdf_export import sales_invoice_pdf
from app.image_export import pdf_bytes_to_png


@router.get("/{sale_id}/image")
def download_sales_invoice_image(
    sale_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    sale = get_sale_or_404(db, sale_id)
    acting_user = get_acting_user(db, request)
    loc_ids = scoped_location_ids(db, acting_user)
    if loc_ids is not None and sale.location_id not in loc_ids:
        raise HTTPException(
            status_code=403, detail="Forbidden: You do not have access to this sales invoice"
        )

    pdf_bytes = sales_invoice_pdf(sale)
    dispensed_at_str = sale.dispensed_at.strftime("%Y-%m-%d %H:%M") if sale.dispensed_at else "-"
    rows = [
        ("Location", sale.location.name),
        ("Product", sale.product.name),
        ("Batch Number", sale.batch_number),
        ("Quantity", str(sale.quantity)),
        ("Payment Mode", sale.payment_mode),
        ("Prescription Ref", sale.prescription_reference or "-"),
        ("Unit Price", f"INR {sale.unit_price:,.2f}"),
        ("Tax Percent", f"{sale.tax_percent}%"),
        ("Value Before Tax", f"INR {sale.value_before_tax:,.2f}"),
        ("Tax Amount", f"INR {sale.tax_amount:,.2f}"),
        ("Total Amount", f"INR {sale.total_amount:,.2f}"),
        ("Cost Basis (Internal)", f"INR {sale.cost_of_goods:,.2f}"),
        ("Dispensed By", sale.dispensed_by.name),
        ("Dispensed At", dispensed_at_str),
    ]
    png_bytes = pdf_bytes_to_png(pdf_bytes, "SALES INVOICE / DISPENSING RECEIPT", sale.document_no, rows)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{sale.document_no}.png"'},
    )
