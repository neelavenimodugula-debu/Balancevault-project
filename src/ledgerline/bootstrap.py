import sys
from uuid import uuid4

from sqlalchemy.orm import Session

from ledgerline.auth import hash_password
from ledgerline.config import get_settings
from ledgerline.database import SessionLocal, engine
from ledgerline.models import Account, Base, User, UserRole


def bootstrap_first_admin(session: Session | None = None) -> User | None:
    settings = get_settings()
    owns_session = False
    if session is None:
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        owns_session = True

    try:
        # Check if an admin already exists
        existing_admin = (
            session.query(User)
            .filter(
                (User.role == UserRole.ADMIN) | (User.role == "admin")
            )
            .first()
        )
        if existing_admin:
            print(f"Admin user already exists ({existing_admin.email}). Bootstrap skipped.")
            return existing_admin

        admin_email = settings.admin_email
        admin_pass = settings.admin_password.get_secret_value()

        if not admin_email or not admin_pass:
            print("Error: LEDGERLINE_ADMIN_EMAIL and LEDGERLINE_ADMIN_PASSWORD must be configured.")
            return None

        # Create first administrator
        admin_user = User(
            id=uuid4(),
            email=admin_email,
            password_hash=hash_password(admin_pass),
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(admin_user)

        # Create system clearing account if not present
        existing_clearing = (
            session.query(Account)
            .filter_by(is_system_account=True, name=settings.clearing_account_name)
            .first()
        )
        if not existing_clearing:
            clearing = Account(
                id=uuid4(),
                owner_user_id=None,
                name=settings.clearing_account_name,
                currency="INR",
                balance_minor=0,
                is_system_account=True,
            )
            session.add(clearing)

        session.commit()
        print(f"Successfully bootstrapped first administrator: {admin_email}")
        return admin_user
    finally:
        if owns_session:
            session.close()


if __name__ == "__main__":
    result = bootstrap_first_admin()
    if result is None:
        sys.exit(1)
    sys.exit(0)

