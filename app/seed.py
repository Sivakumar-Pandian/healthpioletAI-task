from app.database import Base, SessionLocal, engine
from app.models import AppUser, Company, Location, LocationType, Product, Supplier, UserRole
from app.auth import hash_password


def seed_if_empty(db):
    default_pwd = hash_password("password123")
    
    # 1. Ensure default Company exists
    company = db.query(Company).filter(Company.name == "HealthPilot Healthcare Systems").first()
    if not company:
        company = Company(name="HealthPilot Healthcare Systems", code="HPILOT")
        db.add(company)
        db.flush()

    # Ensure master data records exist
    prod = db.query(Product).filter(Product.name.like("%Insulin Glargine%")).first()
    if not prod:
        prod = Product(
            name="Insulin Glargine 100 IU/ml",
            unit="vial",
            storage_condition="Refrigerated between 2°C and 8°C",
            purchase_price=500,
            tax_percent=5,
        )
        db.add(prod)

    sup = db.query(Supplier).filter(Supplier.name.like("%MediSupply%")).first()
    if not sup:
        sup = Supplier(name="MediSupply Pharmaceuticals Pvt. Ltd.", contact="orders@medisupply.example")
        db.add(sup)

    cw = db.query(Location).filter(Location.name.like("%Central%")).first()
    if not cw:
        cw = Location(name="Central Pharmacy Warehouse", type=LocationType.WAREHOUSE, company_id=company.id)
        db.add(cw)

    ba = db.query(Location).filter(Location.name == "Branch A").first()
    if not ba:
        ba = Location(name="Branch A", type=LocationType.BRANCH, company_id=company.id)
        db.add(ba)

    bb = db.query(Location).filter(Location.name == "Branch B").first()
    if not bb:
        bb = Location(name="Branch B", type=LocationType.BRANCH, company_id=company.id)
        db.add(bb)

    bc = db.query(Location).filter(Location.name == "Branch C").first()
    if not bc:
        bc = Location(name="Branch C", type=LocationType.BRANCH, company_id=company.id)
        db.add(bc)

    db.flush()

    # Create demo users if not present
    if not db.query(AppUser).filter(AppUser.email == "anita@healthpilot.org").first():
        db.add_all(
            [
                AppUser(
                    name="Anita Rao",
                    email="anita@healthpilot.org",
                    password_hash=default_pwd,
                    role=UserRole.BRANCH_STAFF,
                    company_id=company.id,
                    home_location_id=ba.id,
                ),
                AppUser(
                    name="Karthik Iyer",
                    email="karthik@healthpilot.org",
                    password_hash=default_pwd,
                    role=UserRole.BRANCH_STAFF,
                    company_id=company.id,
                    home_location_id=bb.id,
                ),
                AppUser(
                    name="Meena Pillai",
                    email="meena@healthpilot.org",
                    password_hash=default_pwd,
                    role=UserRole.CENTRAL_PURCHASING,
                    company_id=company.id,
                    home_location_id=None,
                ),
                AppUser(
                    name="Rahul Dev",
                    email="rahul@healthpilot.org",
                    password_hash=default_pwd,
                    role=UserRole.RECEIVING_STAFF,
                    company_id=company.id,
                    home_location_id=None,
                ),
            ]
        )
    db.commit()
    return True


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if seed_if_empty(db):
            print("Seeded master data with company and auth accounts")
        else:
            print("Already seeded, updated credentials if needed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
