from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import StockLedgerEntry


def computed_stock(
    db: Session,
    location_id=None,
    product_id=None,
    batch_number=None,
    stock_status=None,
):
    """Return the net stock for the requested ledger slice."""
    query = db.query(
        func.coalesce(func.sum(StockLedgerEntry.quantity_in), 0),
        func.coalesce(func.sum(StockLedgerEntry.quantity_out), 0),
    )

    if location_id is not None:
        query = query.filter(StockLedgerEntry.location_id == location_id)
    if product_id is not None:
        query = query.filter(StockLedgerEntry.product_id == product_id)
    if batch_number is not None:
        query = query.filter(StockLedgerEntry.batch_number == batch_number)
    if stock_status is not None:
        query = query.filter(StockLedgerEntry.stock_status == stock_status)

    quantity_in, quantity_out = query.one()
    return int(quantity_in) - int(quantity_out)
