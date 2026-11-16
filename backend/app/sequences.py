from sqlalchemy import text
from sqlalchemy.orm import Session


# Tables whose rows are sometimes inserted with explicit IDs
# (seed.py)
TABLES_WITH_ID_SEQUENCE = [
    "tenants",
    "users",
    "applications",
    "devices",
]


def reset_id_sequences(db: Session):
    """
    PostgreSQL does not advance an id sequence when a row is inserted
    with an explicit id. Afterwards the next normal insert would reuse
    an existing id and fail with "duplicate key value violates unique
    constraint". This moves every sequence to MAX(id).
    """
    if db.bind and db.bind.dialect.name != "postgresql":
        return

    for table in TABLES_WITH_ID_SEQUENCE:
        db.execute(
            text(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    (SELECT MAX(id) FROM {table}) IS NOT NULL
                )
                """
            )
        )

    db.commit()


if __name__ == "__main__":
    from app.database import SessionLocal

    db = SessionLocal()

    try:
        reset_id_sequences(db)
        print("ID sequences reset.")
    finally:
        db.close()
