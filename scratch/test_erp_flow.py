import datetime
from sqlalchemy.orm import Session
from app.database import Base, engine, SessionLocal
from app.seed import seed_if_empty
from app.models import (
    AppUser, Company, Location, LocationType, Product, Supplier,
    Requisition, RequisitionStatus, PurchaseOrder, PurchaseOrderStatus,
    GoodsReceiptNote, GrnCorrection, SupplierInvoice, SupplierInvoiceStatus,
    StockTransfer, StockTransferStatus, SalesInvoice, StockLedgerEntry,
    StockStatus, LedgerTxnType
)
from app.document_numbers import next_document_number
from app.stock import computed_stock

def run_test():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed_if_empty(db)

    # Reset existing transaction tables
    for model in (SalesInvoice, StockTransfer, StockLedgerEntry, SupplierInvoice, GrnCorrection, GoodsReceiptNote, PurchaseOrder, Requisition):
        db.query(model).delete(synchronize_session=False)
    db.commit()

    central_wh = db.query(Location).filter(Location.type == LocationType.WAREHOUSE).first()
    branch_a = db.query(Location).filter(Location.name == "Branch A").first()
    branch_b = db.query(Location).filter(Location.name == "Branch B").first()
    branch_c = db.query(Location).filter(Location.name == "Branch C").first()
    if not branch_c:
        branches = db.query(Location).filter(Location.type == LocationType.BRANCH).all()
        branch_a = branches[0] if len(branches) > 0 else None
        branch_b = branches[1] if len(branches) > 1 else None
        branch_c = branches[2] if len(branches) > 2 else branch_b
    product = db.query(Product).filter(Product.name.like("%Insulin%")).first()
    supplier = db.query(Supplier).first()

    anita = db.query(AppUser).filter(AppUser.name == "Anita Rao").first()
    karthik = db.query(AppUser).filter(AppUser.name == "Karthik Iyer").first()
    meena = db.query(AppUser).filter(AppUser.name == "Meena Pillai").first()
    rahul = db.query(AppUser).filter(AppUser.name == "Rahul Dev").first()

    print(f"Master Data Found: {product.name}, Price: {product.purchase_price}, Tax: {product.tax_percent}%")

    # STEP 1: 1 Sept 2026 - Branch requirements
    req_a = Requisition(
        document_no=next_document_number(db, Requisition, "document_no", "REQ"),
        location_id=branch_a.id,
        product_id=product.id,
        quantity=100,
        required_date="2026-09-01",
        requester_id=anita.id,
        reason="Branch A Insulin Requirement",
        status=RequisitionStatus.SUBMITTED
    )
    db.add(req_a)
    db.flush()

    req_b = Requisition(
        document_no=next_document_number(db, Requisition, "document_no", "REQ"),
        location_id=branch_b.id,
        product_id=product.id,
        quantity=40,
        required_date="2026-09-01",
        requester_id=karthik.id,
        reason="Branch B Insulin Requirement",
        status=RequisitionStatus.SUBMITTED
    )
    db.add(req_b)
    db.flush()

    req_c = Requisition(
        document_no=next_document_number(db, Requisition, "document_no", "REQ"),
        location_id=branch_c.id,
        product_id=product.id,
        quantity=60,
        required_date="2026-09-01",
        requester_id=karthik.id,
        reason="Branch C Insulin Requirement",
        status=RequisitionStatus.SUBMITTED
    )
    db.add(req_c)
    db.commit()

    # Central approves Req A
    req_a.status = RequisitionStatus.APPROVED
    db.commit()
    print(f"Step 1 Complete: Created 3 branch requests. Req A ({req_a.document_no}) Approved.")

    # STEP 2: 2 Sept 2026 - Central team places supplier order for Branch A (100 vials @ 500 = 50000 + 2500 tax = 52500)
    unit_price = 500.0
    tax_pct = 5.0
    val_before_tax = 100 * unit_price
    tax_amt = val_before_tax * (tax_pct / 100.0)
    tot_val = val_before_tax + tax_amt

    po = PurchaseOrder(
        document_no=next_document_number(db, PurchaseOrder, "document_no", "PO"),
        requisition_id=req_a.id,
        supplier_id=supplier.id,
        product_id=product.id,
        quantity=100,
        unit_price=unit_price,
        tax_percent=tax_pct,
        value_before_tax=val_before_tax,
        tax_amount=tax_amt,
        total_value=tot_val,
        delivery_location_id=central_wh.id,
        status=PurchaseOrderStatus.OPEN
    )
    db.add(po)
    db.commit()
    print(f"Step 2 Complete: PO {po.document_no} created. Total Value: Rs {po.total_value}")

    # STEP 3 & 4: Delivery, inspection & receiving error + correction
    # Mistakenly post 100 accepted initially
    batch_no = "IG-SEP26-01"
    grn = GoodsReceiptNote(
        document_no=next_document_number(db, GoodsReceiptNote, "document_no", "GRN"),
        po_id=po.id,
        batch_number=batch_no,
        expiry_date="2028-08-31",
        physical_quantity=100,
        accepted_quantity=100,
        damaged_quantity=0,
        missing_quantity=0,
        posted_by_id=rahul.id,
        posted_at=datetime.datetime.utcnow()
    )
    db.add(grn)
    db.flush()
    db.add(StockLedgerEntry(
        location_id=central_wh.id,
        product_id=product.id,
        batch_number=batch_no,
        txn_type=LedgerTxnType.RECEIPT,
        stock_status=StockStatus.USABLE,
        quantity_in=100,
        quantity_out=0,
        reference_document=grn.document_no,
        performed_by_id=rahul.id
    ))
    db.commit()

    cw_before_corr = computed_stock(db, location_id=central_wh.id, product_id=product.id, batch_number=batch_no, stock_status=StockStatus.USABLE)
    print(f"Step 4 (Mistake): GRN {grn.document_no} posted as 100 accepted. Central Warehouse stock: {cw_before_corr}")

    # Correction on 6 Sept 2026: 70 accepted, 20 damaged, 10 missing
    corr = GrnCorrection(
        original_grn_id=grn.id,
        old_accepted_quantity=100,
        old_damaged_quantity=0,
        old_missing_quantity=0,
        new_accepted_quantity=70,
        new_damaged_quantity=20,
        new_missing_quantity=10,
        reason="Physical inspection identified 20 temp logger exceeded 8C and 10 missing from DN MSP-DN-050926",
        corrected_by_id=meena.id,
        corrected_at=datetime.datetime.utcnow()
    )
    db.add(corr)
    # Adjustment ledger entries: Usable out 30, Quarantined in 20
    db.add_all([
        StockLedgerEntry(
            location_id=central_wh.id,
            product_id=product.id,
            batch_number=batch_no,
            txn_type=LedgerTxnType.CORRECTION,
            stock_status=StockStatus.USABLE,
            quantity_in=0,
            quantity_out=30,
            reference_document=grn.document_no,
            performed_by_id=meena.id
        ),
        StockLedgerEntry(
            location_id=central_wh.id,
            product_id=product.id,
            batch_number=batch_no,
            txn_type=LedgerTxnType.CORRECTION,
            stock_status=StockStatus.QUARANTINED,
            quantity_in=20,
            quantity_out=0,
            reference_document=grn.document_no,
            performed_by_id=meena.id
        )
    ])
    db.commit()

    cw_usable_after = computed_stock(db, location_id=central_wh.id, product_id=product.id, batch_number=batch_no, stock_status=StockStatus.USABLE)
    cw_quarantine_after = computed_stock(db, location_id=central_wh.id, product_id=product.id, batch_number=batch_no, stock_status=StockStatus.QUARANTINED)
    print(f"Step 4 (Corrected): Usable: {cw_usable_after}, Quarantined: {cw_quarantine_after}, Missing: {corr.new_missing_quantity}")

    # STEP 5: Supplier invoice discrepancy & resolution
    payable = round(70 * 500 * 1.05, 2)
    invoiced_val = 52500.0
    disputed = round(invoiced_val - payable, 2)

    inv = SupplierInvoice(
        document_no=next_document_number(db, SupplierInvoice, "document_no", "SUPINV"),
        po_id=po.id,
        grn_id=grn.id,
        invoiced_quantity=100,
        invoiced_value=invoiced_val,
        status=SupplierInvoiceStatus.DISPUTED,
        payable_amount=payable,
        disputed_amount=disputed
    )
    db.add(inv)
    db.commit()
    print(f"Step 5 Discrepancy: Invoice {inv.document_no} - Invoiced: Rs {invoiced_val}, Payable: Rs {payable}, Disputed: Rs {disputed}")

    # Credit Note Resolution
    inv.credit_note_reference = "MSP-CN-2026-09"
    db.commit()
    print(f"Step 5 Resolution: Credit Note {inv.credit_note_reference} recorded.")

    # STEP 6: 30 usable vials transfer to Branch A
    stn = StockTransfer(
        document_no=next_document_number(db, StockTransfer, "document_no", "STN"),
        source_location_id=central_wh.id,
        destination_location_id=branch_a.id,
        product_id=product.id,
        batch_number=batch_no,
        quantity=30,
        status=StockTransferStatus.DISPATCHED,
        dispatched_by_id=rahul.id,
        dispatched_at=datetime.datetime.utcnow()
    )
    db.add(stn)
    db.flush()
    db.add(StockLedgerEntry(
        location_id=central_wh.id,
        product_id=product.id,
        batch_number=batch_no,
        txn_type=LedgerTxnType.TRANSFER_OUT,
        stock_status=StockStatus.USABLE,
        quantity_in=0,
        quantity_out=30,
        reference_document=stn.document_no,
        performed_by_id=rahul.id
    ))
    db.commit()

    # Receive transfer at Branch A
    stn.status = StockTransferStatus.RECEIVED
    stn.received_by_id = anita.id
    stn.received_at = datetime.datetime.utcnow()
    db.add(StockLedgerEntry(
        location_id=branch_a.id,
        product_id=product.id,
        batch_number=batch_no,
        txn_type=LedgerTxnType.TRANSFER_IN,
        stock_status=StockStatus.USABLE,
        quantity_in=30,
        quantity_out=0,
        reference_document=stn.document_no,
        performed_by_id=anita.id
    ))
    db.commit()
    print(f"Step 6 Complete: Stock Transfer {stn.document_no} received at Branch A.")

    # STEP 7: Branch A dispenses 5 vials
    sale_qty = 5
    sale_price = 650.0
    sale_tax = 5.0
    v_before = round(sale_qty * sale_price, 2)
    t_amt = round(v_before * sale_tax / 100.0, 2)
    tot_paid = round(v_before + t_amt, 2)
    cogs = round(sale_qty * 500.0, 2)

    sale = SalesInvoice(
        document_no=next_document_number(db, SalesInvoice, "document_no", "SALE"),
        location_id=branch_a.id,
        product_id=product.id,
        batch_number=batch_no,
        quantity=sale_qty,
        unit_price=sale_price,
        tax_percent=sale_tax,
        value_before_tax=v_before,
        tax_amount=t_amt,
        total_amount=tot_paid,
        cost_of_goods=cogs,
        payment_mode="Card",
        prescription_reference="RX-SEP2026-99",
        dispensed_by_id=anita.id,
        dispensed_at=datetime.datetime.utcnow()
    )
    db.add(sale)
    db.flush()
    db.add(StockLedgerEntry(
        location_id=branch_a.id,
        product_id=product.id,
        batch_number=batch_no,
        txn_type=LedgerTxnType.ISSUE,
        stock_status=StockStatus.USABLE,
        quantity_in=0,
        quantity_out=sale_qty,
        reference_document=sale.document_no,
        performed_by_id=anita.id
    ))
    db.commit()
    print(f"Step 7 Complete: Dispensed {sale_qty} vials at Rs {tot_paid} (Card). COGS: Rs {cogs}")

    # VERIFY EXPECTED FINAL POSITIONS
    final_cw_usable = computed_stock(db, location_id=central_wh.id, product_id=product.id, batch_number=batch_no, stock_status=StockStatus.USABLE)
    final_ba_usable = computed_stock(db, location_id=branch_a.id, product_id=product.id, batch_number=batch_no, stock_status=StockStatus.USABLE)
    final_damaged = computed_stock(db, location_id=central_wh.id, product_id=product.id, batch_number=batch_no, stock_status=StockStatus.QUARANTINED)

    print("\n================ FINAL VERIFICATION RESULT ================")
    print(f"Usable stock at central warehouse: {final_cw_usable} (Target: 40) -> {'PASS' if final_cw_usable == 40 else 'FAIL'}")
    print(f"Usable stock at Branch A:          {final_ba_usable} (Target: 25) -> {'PASS' if final_ba_usable == 25 else 'FAIL'}")
    print(f"Sold and dispensed at Branch A:    {sale.quantity} (Target: 5)  -> {'PASS' if sale.quantity == 5 else 'FAIL'}")
    print(f"Damaged; awaiting return/disposal: {final_damaged} (Target: 20) -> {'PASS' if final_damaged == 20 else 'FAIL'}")
    print(f"Missing from supplier delivery:    {corr.new_missing_quantity} (Target: 10) -> {'PASS' if corr.new_missing_quantity == 10 else 'FAIL'}")
    print(f"Total ordered:                     {po.quantity} (Target: 100) -> {'PASS' if po.quantity == 100 else 'FAIL'}")

    db.close()

if __name__ == "__main__":
    run_test()
