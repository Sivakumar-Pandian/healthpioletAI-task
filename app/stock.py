from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from app.models import GoodsReceiptNote, GrnCorrection, StockLedgerEntry, StockStatus


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


def effective_accepted_quantity(db: Session, grn: GoodsReceiptNote):
    correction = (
        db.query(GrnCorrection)
        .filter(GrnCorrection.original_grn_id == grn.id)
        .first()
    )
    if correction:
        return correction.new_accepted_quantity
    return grn.accepted_quantity


def usable_batches_at(db: Session, location_id: int, product_id: int = None):
    """Return list of (batch_number, quantity_available) for USABLE stock > 0 at location."""
    query = (
        db.query(distinct(StockLedgerEntry.batch_number))
        .filter(StockLedgerEntry.location_id == location_id)
    )
    if product_id is not None:
        query = query.filter(StockLedgerEntry.product_id == product_id)

    batches = [row[0] for row in query.all()]
    result = []
    for batch in sorted(batches):
        qty = computed_stock(
            db,
            location_id=location_id,
            product_id=product_id,
            batch_number=batch,
            stock_status=StockStatus.USABLE,
        )
        if qty > 0:
            result.append((batch, qty))
    return result


def all_batches_at(db: Session, location_id: int, product_id: int = None):
    """Return list of (batch_number, usable_qty, quarantined_qty) for ALL batches that have
    any stock (usable or quarantined) at the location. Useful for building a batch picker that
    shows quarantined-only batches as disabled options with a clear label."""
    query = (
        db.query(distinct(StockLedgerEntry.batch_number))
        .filter(StockLedgerEntry.location_id == location_id)
    )
    if product_id is not None:
        query = query.filter(StockLedgerEntry.product_id == product_id)

    batches = [row[0] for row in query.all()]
    result = []
    for batch in sorted(batches):
        usable = computed_stock(
            db,
            location_id=location_id,
            product_id=product_id,
            batch_number=batch,
            stock_status=StockStatus.USABLE,
        )
        quarantined = computed_stock(
            db,
            location_id=location_id,
            product_id=product_id,
            batch_number=batch,
            stock_status=StockStatus.QUARANTINED,
        )
        if usable > 0 or quarantined > 0:
            result.append((batch, usable, quarantined))
    return result
