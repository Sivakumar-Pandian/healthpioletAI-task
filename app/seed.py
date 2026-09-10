from app.database import Base, SessionLocal, engine
from app.models import AppUser, Location, LocationType, Product, Supplier, UserRole


def seed_if_empty(db):
    if db.query(Product).first() is not None:
        return False

    db.add_all(
        [
            Product(
                name="Insulin Glargine",
                unit="vial",
                storage_condition="2-8°C",
                purchase_price=500,
                tax_percent=5,
            ),
            Supplier(name="MedSupply Co", contact="orders@medsupply.example"),
            Location(name="Central Warehouse", type=LocationType.WAREHOUSE),
            Location(name="Branch A", type=LocationType.BRANCH),
            Location(name="Branch B", type=LocationType.BRANCH),
            Location(name="Branch C", type=LocationType.BRANCH),
            AppUser(name="Anita Rao", role=UserRole.BRANCH_STAFF),
            AppUser(name="Karthik Iyer", role=UserRole.BRANCH_STAFF),
            AppUser(name="Meena Pillai", role=UserRole.CENTRAL_PURCHASING),
            AppUser(name="Rahul Dev", role=UserRole.RECEIVING_STAFF),
        ]
    )
    db.commit()
    return True


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if seed_if_empty(db):
            print("Seeded 1 product, 1 supplier, 4 locations, and 4 users")
        else:
            print("Already seeded, skipping")
    finally:
        db.close()


if __name__ == "__main__":
    main()
