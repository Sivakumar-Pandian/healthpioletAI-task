import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.context import success_redirect
from app.database import get_db
from app.document_numbers import next_document_number
from app.models import (
    AppUser,
    GoodsReceiptNote,
    GrnCorrection,
    LedgerTxnType,
    Location,
    Product,
    PurchaseOrder,
    PurchaseOrderStatus,
    Requisition,
    RequisitionStatus,
    SalesInvoice,
    StockLedgerEntry,
    StockStatus,
    StockTransfer,
    StockTransferStatus,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceStatus,
)

router = APIRouter(prefix="/demo", tags=["demo"])


def reset_all_transactions(db: Session):
    """Delete all transaction rows in an order that respects foreign keys."""
    for model in (
        SalesInvoice,
        StockTransfer,
        StockLedgerEntry,
        SupplierInvoice,
        GrnCorrection,
        GoodsReceiptNote,
        PurchaseOrder,
        Requisition,
    ):
        db.query(model).delete(synchronize_session=False)
    db.commit()


def run_full_scenario(db: Session) -> int:
    """Run the complete demo scenario using real logic & dynamic master data lookups.
    
    Returns the requisition_id for redirection to /traceability/{requisition_id}.
    """
    # Look up master data dynamically by flexible name filters
    branch_a = db.query(Location).filter(Location.name == "Branch A").first()
    central_wh = db.query(Location).filter(Location.name.like("%Central%")).first()
    product = db.query(Product).filter(Product.name.like("%Insulin%")).first()
    supplier = db.query(Supplier).filter(Supplier.name.like("%Med%")).first()

    anita = db.query(AppUser).filter(AppUser.name == "Anita Rao").first()
    meena = db.query(AppUser).filter(AppUser.name == "Meena Pillai").first()
    rahul = db.query(AppUser).filter(AppUser.name == "Rahul Dev").first()
    karthik = db.query(AppUser).filter(AppUser.name == "Karthik Iyer").first()

    if not all([branch_a, central_wh, product, supplier, anita, meena, rahul, karthik]):
        raise HTTPException(
            status_code=500,
            detail="Seeded master data missing (locations, users, products, or suppliers).",
        )

    # 1. Create REQ-0001 (Branch A, Anita Rao, Insulin Glargine, 100 units) → Approve it
    req = Requisition(
        document_no=next_document_number(db, Requisition, "document_no", "REQ"),
        location_id=branch_a.id,
        product_id=product.id,
        quantity=100,
        required_date="2026-10-01",
        requester_id=anita.id,
        reason="Branch A stock replenishment",
        status=RequisitionStatus.SUBMITTED,
    )
    db.add(req)
    db.flush()
    req.status = RequisitionStatus.APPROVED
    db.commit()

    # 2. Create PO-0001 from REQ-0001 (MedSupply Co, ₹500 unit price, 5% tax, delivery to Central Warehouse)
    unit_price = 500.0
    tax_percent = 5.0
    val_before_tax = 100 * unit_price
    tax_amt = val_before_tax * tax_percent / 100.0
    tot_val = val_before_tax + tax_amt

    po = PurchaseOrder(
        document_no=next_document_number(db, PurchaseOrder, "document_no", "PO"),
        requisition_id=req.id,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=100,
        unit_price=unit_price,
        tax_percent=tax_percent,
        value_before_tax=val_before_tax,
        tax_amount=tax_amt,
        total_value=tot_val,
        delivery_location_id=central_wh.id,
        status=PurchaseOrderStatus.OPEN,
    )
    db.add(po)
    db.commit()

    # 3. Post GRN-0001 against PO-0001 (physical=90, accepted=90, damaged=0, missing=10)
    batch_num = "CORRTEST-1"
    grn = GoodsReceiptNote(
        document_no=next_document_number(db, GoodsReceiptNote, "document_no", "GRN"),
        po_id=po.id,
        batch_number=batch_num,
        expiry_date="2027-12-31",
        physical_quantity=90,
        accepted_quantity=90,
        damaged_quantity=0,
        missing_quantity=10,
        posted_by_id=rahul.id,
        posted_at=datetime.datetime.utcnow(),
    )
    db.add(grn)
    db.flush()

    # Post initial ledger entry for GRN-0001
    db.add(
        StockLedgerEntry(
            location_id=central_wh.id,
            product_id=product.id,
            batch_number=batch_num,
            txn_type=LedgerTxnType.RECEIPT,
            stock_status=StockStatus.USABLE,
            quantity_in=90,
            quantity_out=0,
            reference_document=grn.document_no,
            performed_by_id=rahul.id,
        )
    )
    po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED
    db.commit()

    # 4. Correct GRN-0001 (accepted=70, damaged=20, missing=10, reason="Miscounted damaged units on initial inspection", corrected by Meena Pillai)
    correction = GrnCorrection(
        original_grn_id=grn.id,
        old_accepted_quantity=90,
        old_damaged_quantity=0,
        old_missing_quantity=10,
        new_accepted_quantity=70,
        new_damaged_quantity=20,
        new_missing_quantity=10,
        reason="Miscounted damaged units on initial inspection",
        corrected_by_id=meena.id,
        corrected_at=datetime.datetime.utcnow(),
    )
    db.add(correction)

    # Post correction ledger entries (-20 usable, +20 quarantined)
    db.add_all(
        [
            StockLedgerEntry(
                location_id=central_wh.id,
                product_id=product.id,
                batch_number=batch_num,
                txn_type=LedgerTxnType.CORRECTION,
                stock_status=StockStatus.USABLE,
                quantity_in=0,
                quantity_out=20,
                reference_document=grn.document_no,
                performed_by_id=meena.id,
            ),
            StockLedgerEntry(
                location_id=central_wh.id,
                product_id=product.id,
                batch_number=batch_num,
                txn_type=LedgerTxnType.CORRECTION,
                stock_status=StockStatus.QUARANTINED,
                quantity_in=20,
                quantity_out=0,
                reference_document=grn.document_no,
                performed_by_id=meena.id,
            ),
        ]
    )
    db.commit()

    # 5. Create SUPINV-0001 (invoiced_quantity=100, invoiced_value=52500 -> DISPUTED)
    eff_accepted = 70
    payable = round(eff_accepted * po.unit_price * (1 + po.tax_percent / 100.0), 2)
    invoiced_val = 52500.0
    inv = SupplierInvoice(
        document_no=next_document_number(db, SupplierInvoice, "document_no", "SUPINV"),
        po_id=po.id,
        grn_id=grn.id,
        invoiced_quantity=100,
        invoiced_value=invoiced_val,
        status=SupplierInvoiceStatus.DISPUTED,
        payable_amount=payable,
        disputed_amount=round(invoiced_val - payable, 2),
    )
    db.add(inv)
    db.commit()

    # 6. Resolve SUPINV-0001 with credit_note_reference "CN-MEDSUPPLY-001"
    inv.credit_note_reference = "CN-MEDSUPPLY-001"
    db.commit()

    # 7. Create STN-0001 (30 units, Central Warehouse → Branch A, dispatched by Rahul Dev → received by Karthik Iyer)
    stn = StockTransfer(
        document_no=next_document_number(db, StockTransfer, "document_no", "STN"),
        source_location_id=central_wh.id,
        destination_location_id=branch_a.id,
        product_id=product.id,
        batch_number=batch_num,
        quantity=30,
        status=StockTransferStatus.DISPATCHED,
        dispatched_by_id=rahul.id,
        dispatched_at=datetime.datetime.utcnow(),
    )
    db.add(stn)
    db.flush()

    # Ledger: TRANSFER_OUT at Central Warehouse
    db.add(
        StockLedgerEntry(
            location_id=central_wh.id,
            product_id=product.id,
            batch_number=batch_num,
            txn_type=LedgerTxnType.TRANSFER_OUT,
            stock_status=StockStatus.USABLE,
            quantity_in=0,
            quantity_out=30,
            reference_document=stn.document_no,
            performed_by_id=rahul.id,
        )
    )
    db.commit()

    # Confirm receipt by Karthik Iyer
    stn.status = StockTransferStatus.RECEIVED
    stn.received_by_id = karthik.id
    stn.received_at = datetime.datetime.utcnow()

    # Ledger: TRANSFER_IN at Branch A
    db.add(
        StockLedgerEntry(
            location_id=branch_a.id,
            product_id=product.id,
            batch_number=batch_num,
            txn_type=LedgerTxnType.TRANSFER_IN,
            stock_status=StockStatus.USABLE,
            quantity_in=30,
            quantity_out=0,
            reference_document=stn.document_no,
            performed_by_id=karthik.id,
        )
    )
    db.commit()

    # 8. Create SALE-0001 (5 units at Branch A, ₹650 unit price, 5% tax, Cash, prescription ref "RX-88213", dispensed by Anita Rao)
    sale_qty = 5
    sale_unit_price = 650.0
    sale_tax_pct = 5.0
    val_before = round(sale_qty * sale_unit_price, 2)
    tax_val = round(val_before * sale_tax_pct / 100.0, 2)
    tot_amt = round(val_before + tax_val, 2)
    cog = round(sale_qty * product.purchase_price, 2)

    sale = SalesInvoice(
        document_no=next_document_number(db, SalesInvoice, "document_no", "SALE"),
        location_id=branch_a.id,
        product_id=product.id,
        batch_number=batch_num,
        quantity=sale_qty,
        unit_price=sale_unit_price,
        tax_percent=sale_tax_pct,
        value_before_tax=val_before,
        tax_amount=tax_val,
        total_amount=tot_amt,
        cost_of_goods=cog,
        payment_mode="Cash",
        prescription_reference="RX-88213",
        dispensed_by_id=anita.id,
        dispensed_at=datetime.datetime.utcnow(),
    )
    db.add(sale)
    db.flush()

    # Ledger: ISSUE at Branch A
    db.add(
        StockLedgerEntry(
            location_id=branch_a.id,
            product_id=product.id,
            batch_number=batch_num,
            txn_type=LedgerTxnType.ISSUE,
            stock_status=StockStatus.USABLE,
            quantity_in=0,
            quantity_out=sale_qty,
            reference_document=sale.document_no,
            performed_by_id=anita.id,
        )
    )
    db.commit()

    return req.id


@router.post("/reset")
def reset_demo_data(db: Session = Depends(get_db)):
    reset_all_transactions(db)
    return RedirectResponse(
        url=success_redirect("/", "Demo data reset — starting fresh."),
        status_code=303,
    )


@router.post("/replay")
def replay_demo_scenario(db: Session = Depends(get_db)):
    # Always reset first automatically before replaying
    reset_all_transactions(db)
    req_id = run_full_scenario(db)
    return RedirectResponse(
        url=success_redirect(
            f"/traceability/{req_id}",
            "Full demo scenario replayed — showing complete chain for REQ-0001.",
        ),
        status_code=303,
    )
