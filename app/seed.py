from app.database import Base, SessionLocal, engine
from app.models import AppUser, Location, LocationType, Product, Supplier, UserRole


def seed_if_empty(db):
    if db.query(Product).first() is not None:
        # Update home_location_id for existing users if missing
        branch_a = db.query(Location).filter(Location.name == "Branch A").first()
        branch_b = db.query(Location).filter(Location.name == "Branch B").first()
        if branch_a and branch_b:
            anita = db.query(AppUser).filter(AppUser.name == "Anita Rao").first()
            if anita and not anita.home_location_id:
                anita.home_location_id = branch_a.id
            karthik = db.query(AppUser).filter(AppUser.name == "Karthik Iyer").first()
            if karthik and not karthik.home_location_id:
                karthik.home_location_id = branch_b.id
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
    cw = Location(name="Central Warehouse", type=LocationType.WAREHOUSE)
    ba = Location(name="Branch A", type=LocationType.BRANCH)
    bb = Location(name="Branch B", type=LocationType.BRANCH)
    bc = Location(name="Branch C", type=LocationType.BRANCH)

    db.add_all([prod, sup, cw, ba, bb, bc])
    db.flush()

    db.add_all(
        [
            AppUser(name="Anita Rao", role=UserRole.BRANCH_STAFF, home_location_id=ba.id),
            AppUser(name="Karthik Iyer", role=UserRole.BRANCH_STAFF, home_location_id=bb.id),
            AppUser(name="Meena Pillai", role=UserRole.CENTRAL_PURCHASING, home_location_id=None),
            AppUser(name="Rahul Dev", role=UserRole.RECEIVING_STAFF, home_location_id=None),
        ]
    )
    db.commit()
    return True


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if seed_if_empty(db):
            print("Seeded master data with home_location_id for branch staff")
        else:
            print("Already seeded, updated home_location_id if needed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
