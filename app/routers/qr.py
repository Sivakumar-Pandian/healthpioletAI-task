from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.context import success_redirect
from app.database import get_db
from app.models import (
    GoodsReceiptNote,
    PurchaseOrder,
    Requisition,
    SalesInvoice,
    StockTransfer,
    SupplierInvoice,
)
from app.qr import generate_qr_bytes

router = APIRouter(prefix="/qr", tags=["qr"])


@router.get("/render")
def render_qr_code(data: str = Query(...)):
    """Returns a PNG image of the QR Code encoded with data."""
    if not data:
        raise HTTPException(status_code=400, detail="Data query param is required")
    png_bytes = generate_qr_bytes(data)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/scan")
def scan_lookup(code: str = Query(...), db: Session = Depends(get_db)):
    """Universal QR lookup & redirection endpoint."""
    raw_code = code.strip()
    if not raw_code:
        return RedirectResponse(url="/?error=Invalid+QR+code", status_code=303)

    # 1. If full URL, parse path if relative or internal, or extract document code from URL
    if raw_code.startswith("http://") or raw_code.startswith("https://"):
        parsed = urlparse(raw_code)
        if parsed.path:
            return RedirectResponse(url=parsed.path, status_code=303)

    clean = raw_code.upper()

    # 2. Check Requisition (REQ-)
    if clean.startswith("REQ"):
        req = db.query(Requisition).filter(Requisition.document_no.ilike(clean)).first()
        if req:
            return RedirectResponse(url=f"/requisitions/{req.id}", status_code=303)

    # 3. Check Purchase Order (PO-)
    if clean.startswith("PO"):
        po = db.query(PurchaseOrder).filter(PurchaseOrder.document_no.ilike(clean)).first()
        if po:
            return RedirectResponse(url=f"/purchase-orders/{po.id}", status_code=303)

    # 4. Check Goods Receipt Note (GRN-)
    if clean.startswith("GRN"):
        grn = db.query(GoodsReceiptNote).filter(GoodsReceiptNote.document_no.ilike(clean)).first()
        if grn:
            return RedirectResponse(url=f"/goods-receipts/{grn.id}", status_code=303)

    # 5. Check Stock Transfer (TRF-)
    if clean.startswith("TRF"):
        trf = db.query(StockTransfer).filter(StockTransfer.document_no.ilike(clean)).first()
        if trf:
            return RedirectResponse(url=f"/transfers/{trf.id}", status_code=303)

    # 6. Check Supplier Invoice (INV-)
    if clean.startswith("INV"):
        inv = db.query(SupplierInvoice).filter(SupplierInvoice.document_no.ilike(clean)).first()
        if inv:
            return RedirectResponse(url=f"/supplier-invoices/{inv.id}", status_code=303)

    # 7. Check Dispensing / Sales Receipt (DISP-)
    if clean.startswith("DISP"):
        disp = db.query(SalesInvoice).filter(SalesInvoice.document_no.ilike(clean)).first()
        if disp:
            return RedirectResponse(url=f"/dispensing/{disp.id}", status_code=303)

    # 8. Check Batch Number or fallback trace search
    grn_batch = db.query(GoodsReceiptNote).filter(GoodsReceiptNote.batch_number.ilike(clean)).first()
    if grn_batch:
        return RedirectResponse(url=f"/traceability/{grn_batch.batch_number}", status_code=303)

    # Fallback to traceability search page
    return RedirectResponse(
        url=f"/traceability?batch={clean}",
        status_code=303,
    )
