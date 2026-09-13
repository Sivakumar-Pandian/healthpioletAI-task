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

    if db.query(Product).first() is not None:
        # Update existing records with company and auth fields if missing
        for loc in db.query(Location).all():
            if not loc.company_id:
                loc.company_id = company.id
        
        branch_a = db.query(Location).filter(Location.name == "Branch A").first()
        branch_b = db.query(Location).filter(Location.name == "Branch B").first()
        
        anita = db.query(AppUser).filter(AppUser.name == "Anita Rao").first()
        if anita:
            if not anita.email: anita.email = "anita@healthpilot.org"
            if not anita.password_hash: anita.password_hash = default_pwd
            if not anita.company_id: anita.company_id = company.id
            if branch_a and not anita.home_location_id: anita.home_location_id = branch_a.id

        karthik = db.query(AppUser).filter(AppUser.name == "Karthik Iyer").first()
        if karthik:
            if not karthik.email: karthik.email = "karthik@healthpilot.org"
            if not karthik.password_hash: karthik.password_hash = default_pwd
            if not karthik.company_id: karthik.company_id = company.id
            if branch_b and not karthik.home_location_id: karthik.home_location_id = branch_b.id

        meena = db.query(AppUser).filter(AppUser.name == "Meena Pillai").first()
        if meena:
            if not meena.email: meena.email = "meena@healthpilot.org"
            if not meena.password_hash: meena.password_hash = default_pwd
            if not meena.company_id: meena.company_id = company.id

        rahul = db.query(AppUser).filter(AppUser.name == "Rahul Dev").first()
        if rahul:
            if not rahul.email: rahul.email = "rahul@healthpilot.org"
            if not rahul.password_hash: rahul.password_hash = default_pwd
            if not rahul.company_id: rahul.company_id = company.id

        db.commit()
        return False

    prod = Product(
        name="Insulin Glargine",
        unit="vial",
        storage_condition="2-8°C",
        purchase_price=500,
        tax_percent=5,
    )
    sup = Supplier(name="MedSupply Co", contact="orders@medsupply.example")
    cw = Location(name="Central Warehouse", type=LocationType.WAREHOUSE, company_id=company.id)
    ba = Location(name="Branch A", type=LocationType.BRANCH, company_id=company.id)
    bb = Location(name="Branch B", type=LocationType.BRANCH, company_id=company.id)
    bc = Location(name="Branch C", type=LocationType.BRANCH, company_id=company.id)

    db.add_all([prod, sup, cw, ba, bb, bc])
    db.flush()

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
