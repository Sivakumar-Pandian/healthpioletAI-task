import urllib.request
import urllib.parse
import json
from app.database import SessionLocal
from app.models import (
    AppUser, Requisition, PurchaseOrder, GoodsReceiptNote,
    SupplierInvoice, StockTransfer, SalesInvoice, StockLedgerEntry,
    Location, RequisitionStatus, PurchaseOrderStatus, Product, Supplier
)

db = SessionLocal()
anita = db.query(AppUser).filter(AppUser.name == "Anita Rao").first()
karthik = db.query(AppUser).filter(AppUser.name == "Karthik Iyer").first()
meena = db.query(AppUser).filter(AppUser.name == "Meena Pillai").first()

anita_id = anita.id
karthik_id = karthik.id
meena_id = meena.id

branch_a = db.query(Location).filter(Location.name == "Branch A").first()
branch_b = db.query(Location).filter(Location.name == "Branch B").first()
branch_a_id = branch_a.id
branch_b_id = branch_b.id

product = db.query(Product).first()
product_id = product.id
supplier = db.query(Supplier).first()
supplier_id = supplier.id

# 1. Ensure a Branch B Requisition and Purchase Order exist
req_b = db.query(Requisition).filter(Requisition.location_id == branch_b_id).first()
if not req_b:
    req_b = Requisition(
        document_no="REQ-TEST-BRANCH-B",
        location_id=branch_b_id,
        product_id=product_id,
        quantity=20,
        required_date="2026-10-01",
        requester_id=karthik_id,
        status=RequisitionStatus.SUBMITTED
    )
    db.add(req_b)
    db.commit()
    db.refresh(req_b)

po_b = db.query(PurchaseOrder).filter(PurchaseOrder.delivery_location_id == branch_b_id).first()
if not po_b:
    po_b = PurchaseOrder(
        document_no="PO-TEST-BRANCH-B",
        requisition_id=req_b.id,
        supplier_id=supplier_id,
        delivery_location_id=branch_b_id,
        product_id=product_id,
        quantity=20,
        unit_price=100.0,
        tax_percent=5.0,
        value_before_tax=2000.0,
        tax_amount=100.0,
        total_value=2100.0,
        status=PurchaseOrderStatus.OPEN
    )
    db.add(po_b)
    db.commit()
    db.refresh(po_b)

req_b_id = req_b.id
po_b_id = po_b.id

db.close()

base_url = "http://127.0.0.1:8000"

print("--- Testing Dashboard and Branch Scoping ---")

# Test Root Dashboard GET for Anita and Meena
for uid in [anita_id, meena_id]:
    req = urllib.request.Request(f"{base_url}/?acting_as_id={uid}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
print("✓ Root Dashboard '/' loads successfully for all user roles")

# 1. Header Locked Dropdown for Anita (Branch Staff)
req = urllib.request.Request(f"{base_url}/requisitions?acting_as_id={anita_id}")
with urllib.request.urlopen(req) as resp:
    html = resp.read().decode("utf-8")
    assert "disabled" in html, "Header location dropdown must be disabled for Branch Staff"
    assert "Branch A" in html, "Locked location dropdown must show Branch A"
print("✓ Base template dropdown locked to home branch for Anita Rao")

# 2. Detail 403 checks for Anita accessing Branch B documents
for endpoint in [f"/requisitions/{req_b_id}", f"/purchase-orders/{po_b_id}"]:
    url = f"{base_url}{endpoint}?acting_as_id={anita_id}"
    try:
        urllib.request.urlopen(url)
        assert False, f"Should have failed with 403 for {endpoint}"
    except urllib.error.HTTPError as e:
        assert e.code == 403, f"Expected 403 for {endpoint}, got {e.code}"
print("✓ 403 Forbidden properly returned for unauthorized detail views")

# 3. Create route location forcing: Requisitions
form_data = urllib.parse.urlencode({
    "product_id": str(product_id),
    "quantity": "10",
    "required_date": "2026-10-15",
    "reason": "Tampered Location Test",
    "location_id": str(branch_b_id), # submitting Branch B deliberately
    "requester_id": str(anita_id),
}).encode("utf-8")

req = urllib.request.Request(f"{base_url}/requisitions/new?acting_as_id={anita_id}", data=form_data, method="POST")
with urllib.request.urlopen(req) as resp:
    assert resp.status in (200, 303)

db = SessionLocal()
latest_req = db.query(Requisition).order_by(Requisition.id.desc()).first()
assert latest_req.location_id == branch_a_id, f"Server should force location_id to {branch_a_id}, got {latest_req.location_id}"
print(f"✓ Requisition creation forced location_id server-side to Branch A ({latest_req.document_no})")
db.close()

# 4. Central Purchasing (Meena Pillai) sees unrestricted views
req = urllib.request.Request(f"{base_url}/requisitions/{req_b_id}?acting_as_id={meena_id}")
with urllib.request.urlopen(req) as resp:
    assert resp.status == 200
print("✓ Central Purchasing (Meena) has unrestricted access to Branch B documents")

print("--- ALL SCOPING TESTS COMPLETED SUCCESSFULLY! ---")
