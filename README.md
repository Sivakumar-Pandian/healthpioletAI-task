# HealthPilot.ai — Multi-Branch Hospital Pharmacy ERP

An ERP-style hospital pharmacy management system designed to track medicines through their entire lifecycle: **Store Requisitions → Supplier Purchase Orders → Goods Receipts & Quality Inspections → Non-Destructive Corrections → Supplier Settlement & Credit Notes → Inter-Store Transfers → Pharmacy Sales & Dispensing**.

---

## 🚀 Quick Run Instructions

### 1. Prerequisites & Environment Setup
```bash
# Clone repository and navigate to folder
cd "healthpioletAI task"

# Activate virtual environment (if available) or create one
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Seed Master Data & Initialize Database
```bash
PYTHONPATH=. python -m app.seed
```

### 3. Launch Local Server
```bash
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 🎭 Demo Scenario & One-Click Walkthrough

The application features a built-in automated scenario runner to demonstrate the exact candidate assignment workflow:

1. **One-Click Scenario Execution**: Navigate to **Demo Controls** on the top navigation bar (or visit `/demo/replay`). This will automatically reset previous transactions, execute all 7 scenario steps sequentially, and redirect you to the complete **Document Traceability Chain**.
2. **Reset Demo Data**: Click **Reset Demo Data** (`/demo/reset`) to clear all operational transactions and start a clean demonstration for live reviewer testing.
3. **Live Review Verification**: During review, you can log in as any branch user or central purchasing admin and raise a new store requisition for a different branch (e.g. Branch B or Branch C).

---

## 🔐 Test Credentials

| Role | Name | Email | Default Password | Location Scoping |
| :--- | :--- | :--- | :--- | :--- |
| **Branch Staff** | Anita Rao | `anita@healthpilot.org` | `password123` | Branch A |
| **Branch Staff** | Karthik Iyer | `karthik@healthpilot.org` | `password123` | Branch B |
| **Central Purchasing** | Meena Pillai | `meena@healthpilot.org` | `password123` | Central Pharmacy Warehouse |
| **Receiving Staff** | Rahul Dev | `rahul@healthpilot.org` | `password123` | Central Pharmacy Warehouse |

---

## 📊 Final Verified Stock Position (Assignment Validation)

Running the candidate scenario results in the exact mathematical stock position expected by the build brief:

| Category / Location | Batch | Usable Qty | Quarantined Qty | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Central Pharmacy Warehouse** | `IG-SEP26-01` | **40** | **20** | 40 Usable, 20 Quarantined (Temp > 8°C) |
| **Branch A Pharmacy** | `IG-SEP26-01` | **25** | 0 | 25 Usable (30 Received − 5 Dispensed) |
| **Sold & Dispensed (Branch A)** | `IG-SEP26-01` | **5** | 0 | Dispensed against Prescription `RX-88213` |
| **Missing from Supplier Delivery** | `IG-SEP26-01` | **10** | 0 | Noted on DN, Credit Note `MSP-CN-2026-09` issued |
| **Total Ordered Quantity** | `IG-SEP26-01` | **100** | — | Verified across document lifecycle |

---

## 📜 Standard ERP Terminology Used

- **Purchase Requisition (Store Requisition)**: Internal demand document raised by store staff.
- **Purchase Order (PO)**: Binding commercial document sent to external supplier (`MediSupply`).
- **Goods Receipt Note (GRN)**: Formal warehouse receiving document splitting physical, accepted, damaged, and missing items.
- **Inspection & Quarantine Record (GRN Correction)**: Non-destructive audit correction adjusting stock status without overwriting history.
- **3-Way Supplier Invoice Matching & Credit Note**: AP verification comparing PO, GRN, and Supplier Invoice to isolate disputed amounts (`₹15,750`).
- **Stock Transfer Order (STO) / Goods Transfer Note**: Two-stage stock movement with distinct `DISPATCHED` and `RECEIVED` states.
- **Pharmacy Dispensing / Sales Invoice**: Point-of-sale document recording retail price (`₹650`), tax (`5%`), prescription reference, and exact Cost of Goods Sold (`COGS = ₹500/vial`).
- **Double-Entry Stock Ledger**: Immutable transaction ledger logging `RECEIPT`, `CORRECTION`, `TRANSFER_OUT`, `TRANSFER_IN`, and `ISSUE` movements by batch and status.

---

## 📝 Key Design & Business Assumptions

1. **Audit Integrity (Non-Destructive Ledger)**: Completed receiving errors are never overwritten or hard-deleted. A `GrnCorrection` entry is posted, and two adjusting `StockLedgerEntry` rows (-30 usable, +20 quarantined) are appended to maintain strict financial audit compliance.
2. **Batch & Status Isolation**: Quarantined stock (damaged due to temperature logger exceeding 8°C) is tracked under `QUARANTINED` status and is systemically blocked from selection during transfers or dispensing.
3. **Store-Wise Location Scoping**: Branch users are restricted to viewing and managing inventory for their home location, while Central Purchasing and Admins have global visibility.

---

## 🛠️ Sources Studied, AI Tools & Third-Party Libraries

- **Industry Workflows Studied**: SAP ERP Materials Management (MM) document chains, Oracle NetSuite inventory movement status workflows, and WHO Good Distribution Practices (GDP) for cold-chain pharmaceutical tracking.
- **AI Tools Used**: Google DeepMind Antigravity AI coding assistant for architecture design, scenario test generation, and UI polish.
- **Core Libraries**:
  - `FastAPI` (Python web framework)
  - `SQLAlchemy` (ORM & database transaction engine)
  - `Jinja2` (Dynamic HTML templating)
  - `FPDF2` (PDF invoice and GRN document generation)
  - `qrcode` (Dynamic QR code generation for batch traceability)

---

## 🚫 Features Intentionally Excluded (Within 8-Hour Timebox)

- Automated EDI integration with external supplier ERP systems.
- Automated sensor IoT ingestion for real-time temperature loggers (photo attachment upload supported).
- Multi-currency conversion (focused on INR ₹ as per brief).
