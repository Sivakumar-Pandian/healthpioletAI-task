from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.context import header_context
from app.database import get_db
from app.models import GoodsReceiptNote, StockLedgerEntry

router = APIRouter(prefix="/stock-ledger", tags=["stock-ledger"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
def stock_ledger(
    request: Request,
    location_id: int | None = Query(default=None),
    batch_number: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(StockLedgerEntry)
    if location_id is not None:
        query = query.filter(StockLedgerEntry.location_id == location_id)
    if batch_number:
        query = query.filter(StockLedgerEntry.batch_number == batch_number)

    entries = query.order_by(StockLedgerEntry.timestamp, StockLedgerEntry.id).all()
    running_balance = 0
    ledger_rows = []
    for entry in entries:
        running_balance += entry.quantity_in - entry.quantity_out
        ledger_rows.append({"entry": entry, "running_balance": running_balance})

    batch_options = [
        batch
        for (batch,) in db.query(StockLedgerEntry.batch_number)
        .distinct()
        .order_by(StockLedgerEntry.batch_number)
        .all()
    ]
    receipt_ids = {
        receipt.document_no: receipt.id
        for receipt in db.query(GoodsReceiptNote).all()
    }

    context = header_context(db)
    context.update(
        {
            "ledger_rows": ledger_rows,
            "batch_options": batch_options,
            "selected_location_id": location_id,
            "selected_batch_number": batch_number,
            "opening_balance": 0,
            "closing_balance": running_balance,
            "receipt_ids": receipt_ids,
        }
    )
    return templates.TemplateResponse(request, "stock_ledger.html", context)
