from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ledgerline.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from ledgerline.bootstrap import bootstrap_auditor, bootstrap_first_admin
from ledgerline.config import get_settings
from ledgerline.database import Base, engine, get_session
from ledgerline.models import (
    Account,
    AuditEvent,
    LedgerEntry,
    User,
    UserRole,
)
from ledgerline.rate_limit import check_redis_connection, rate_limiter
from ledgerline.services.ledger import (
    LedgerException,
    execute_deposit,
    execute_transfer,
    execute_withdrawal,
    reconcile_ledger_balances,
    record_audit_event,
    verify_ledger_hash_chain,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables exist if database is accessible
    try:
        Base.metadata.create_all(bind=engine)
        bootstrap_first_admin()
        bootstrap_auditor()
    except Exception as exc:
        print(f"Startup database initialization notice: {exc}")
    yield


SWAGGER_DESCRIPTION = """
### LedgerLine Financial Integrity Ledger & Money Movement API

Interactive Swagger API Testing Suite for LedgerLine.

#### Authentication Guide for Swagger:
1. **Register** a new user with `POST /auth/register` (or sign in with existing credentials via `POST /auth/login`).
2. Copy the returned `access_token` string.
3. Click the green **Authorize 🔓** button at the top-right of this page.
4. Paste your token into the **Value** field and click **Authorize**.
5. All protected endpoints (`/accounts`, `/transfers`, `/deposits`, `/withdrawals`, `/statements/{account_id}`, `/ledger/verify`, `/ledger/reconciliation`, `/audit/events`, `/users`) will now execute with your authenticated role!

#### Supported Roles & Permissions:
- **`admin`**: System overview, account management, all statements, `/users`, `/audit/events`, `/ledger/verify`, `/ledger/reconciliation`.
- **`account_holder`**: Own accounts only, transfers from own accounts, deposits & withdrawals, personal statements.
- **`auditor`**: Read-only inspection of accounts, statements, `/audit/events`, `/ledger/verify`, `/ledger/reconciliation`.
"""

app = FastAPI(
    title="LedgerLine API",
    version="1.0.0",
    description=SWAGGER_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "docExpansion": "list",
        "filter": True,
        "tryItOutEnabled": True,
    },
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(LedgerException)
async def ledger_exception_handler(request: Request, exc: LedgerException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


# --- Request & Response Schemas ---


EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"


class RegisterRequest(BaseModel):
    email: str = Field(pattern=EMAIL_REGEX)
    password: str = Field(min_length=8)
    full_name: str | None = None


class ProvisionAuditorRequest(BaseModel):
    email: str = Field(pattern=EMAIL_REGEX, description="Auditor email address")
    password: str = Field(min_length=8, description="Initial secure password for the auditor (min 8 characters)")
    full_name: str | None = Field(default=None, max_length=120)


class UserRoleUpdateRequest(BaseModel):
    role: UserRole = Field(description="Target role to assign: admin, auditor, account_holder")


class LoginRequest(BaseModel):
    email: str = Field(pattern=EMAIL_REGEX)
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    owner_user_id: UUID | None = None
    is_system_account: bool = False


class TransferRequest(BaseModel):
    source_account_id: UUID
    destination_account_id: UUID
    amount_minor: int = Field(gt=0, description="Amount in minor units (paise)")
    description: str = "Account transfer"


class DepositRequest(BaseModel):
    account_id: UUID
    amount_minor: int = Field(gt=0, description="Amount in minor units (paise)")
    description: str = "Account deposit"


class WithdrawalRequest(BaseModel):
    account_id: UUID
    amount_minor: int = Field(gt=0, description="Amount in minor units (paise)")
    description: str = "Account withdrawal"


# --- Health & Operations Endpoints ---


@app.get("/health", tags=["operations"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db", tags=["operations"])
def database_health_check(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unreachable: {exc}",
        )


@app.get("/health/redis", tags=["operations"])
def redis_health_check() -> dict[str, str]:
    ok, message = check_redis_connection()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis unreachable: {message}",
        )
    return {"status": "ok", "redis": message}


@app.get("/ready", tags=["operations"])
def readiness_check(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service not ready: Database unreachable: {exc}",
        )

    settings = get_settings()
    ok, message = check_redis_connection()
    if settings.environment.lower() == "production" and settings.strict_redis:
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Service not ready: Production requires connected Redis for rate limiting ({message})",
            )
        return {"status": "ready", "database": "connected", "redis": "connected"}

    return {
        "status": "ready",
        "database": "connected",
        "redis": "connected" if ok else f"unavailable ({message})",
    }


# --- Authentication Endpoints ---


@app.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["authentication"])
def register_user(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter(max_requests=20)),
) -> dict:
    existing = session.query(User).filter_by(email=payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists.",
        )

    # Security: Public registration can NEVER grant admin or auditor roles
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@app.post("/auth/login", tags=["authentication"])
def login_user(
    payload: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter(max_requests=30)),
) -> TokenResponse:
    user = session.query(User).filter_by(email=payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive.",
        )

    token = create_access_token(user)
    settings = get_settings()
    is_prod = settings.environment.lower() == "production"

    # Set secure HttpOnly cookie with SameSite protection against CSRF
    response.set_cookie(
        key="ledgerline_access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=settings.token_expiry_minutes * 60,
        path="/",
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={
            "id": str(user.id),
            "email": user.email,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        },
    )


@app.post("/auth/logout", tags=["authentication"])
def logout_user(response: Response) -> dict[str, str]:
    settings = get_settings()
    is_prod = settings.environment.lower() == "production"
    response.delete_cookie(
        key="ledgerline_access_token",
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_prod,
    )
    return {"status": "ok", "message": "Signed out successfully"}


@app.get("/auth/me", tags=["authentication"])
def get_current_user_profile(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        "is_active": current_user.is_active,
    }


@app.get("/users", tags=["users"])
def list_workspace_users(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    _rate=Depends(rate_limiter()),
) -> list[dict]:
    users = session.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@app.post(
    "/users/auditors",
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
    summary="Provision a new Auditor account or promote user (Administrator Only)",
    description="Securely provisions an Auditor account with read-only inspection privileges. Strictly restricted to authorized Administrators. Logs immutable audit event.",
)
def provision_auditor_account(
    payload: ProvisionAuditorRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    existing = session.query(User).filter_by(email=payload.email).first()
    if existing:
        if existing.role == UserRole.AUDITOR or str(existing.role) == "auditor":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email address is already an auditor.",
            )
        # Promote existing account holder to auditor
        old_role = str(existing.role.value if hasattr(existing.role, "value") else existing.role)
        existing.role = UserRole.AUDITOR
        if payload.password:
            existing.password_hash = hash_password(payload.password)
        session.commit()
        session.refresh(existing)

        record_audit_event(
            session=session,
            actor_id=current_user.id,
            action="PROMOTE_AUDITOR",
            outcome="success",
            details={
                "target_user_id": str(existing.id),
                "email": existing.email,
                "old_role": old_role,
                "new_role": "auditor",
                "admin_actor": current_user.email,
            },
        )
        return {
            "id": str(existing.id),
            "email": existing.email,
            "role": existing.role.value if hasattr(existing.role, "value") else str(existing.role),
            "status": "promoted",
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
        }

    # Create brand new Auditor user
    auditor = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.AUDITOR,
        is_active=True,
    )
    session.add(auditor)
    session.commit()
    session.refresh(auditor)

    record_audit_event(
        session=session,
        actor_id=current_user.id,
        action="PROVISION_AUDITOR",
        outcome="success",
        details={
            "target_user_id": str(auditor.id),
            "email": auditor.email,
            "role": "auditor",
            "admin_actor": current_user.email,
        },
    )

    return {
        "id": str(auditor.id),
        "email": auditor.email,
        "role": auditor.role.value if hasattr(auditor.role, "value") else str(auditor.role),
        "status": "created",
        "created_at": auditor.created_at.isoformat() if auditor.created_at else None,
    }


@app.patch(
    "/users/{user_id}/role",
    tags=["users"],
    summary="Update or promote a user's role (Administrator Only)",
    description="Promotes or updates a user's assigned role. Strictly restricted to authorized Administrators. Logs immutable audit event.",
)
def update_user_role(
    user_id: UUID,
    payload: UserRoleUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.id == current_user.id and payload.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot demote their own account.",
        )

    old_role = str(target_user.role.value if hasattr(target_user.role, "value") else target_user.role)
    new_role_str = str(payload.role.value if hasattr(payload.role, "value") else payload.role)

    target_user.role = payload.role
    session.commit()
    session.refresh(target_user)

    record_audit_event(
        session=session,
        actor_id=current_user.id,
        action="UPDATE_USER_ROLE",
        outcome="success",
        details={
            "target_user_id": str(target_user.id),
            "email": target_user.email,
            "old_role": old_role,
            "new_role": new_role_str,
            "admin_actor": current_user.email,
        },
    )

    return {
        "id": str(target_user.id),
        "email": target_user.email,
        "role": new_role_str,
        "is_active": target_user.is_active,
        "created_at": target_user.created_at.isoformat() if target_user.created_at else None,
    }


# --- Account Management Endpoints ---


@app.post("/accounts", status_code=status.HTTP_201_CREATED, tags=["accounts"])
def create_account(
    payload: AccountCreateRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.ACCOUNT_HOLDER)),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    is_admin = current_user.role == UserRole.ADMIN or str(current_user.role) == "admin"

    # Non-admins cannot create system accounts or assign accounts to other users
    if not is_admin:
        if payload.is_system_account:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators may create system accounts.",
            )
        owner_id = current_user.id
        is_system = False
    else:
        owner_id = payload.owner_user_id if not payload.is_system_account else None
        is_system = payload.is_system_account

    account = Account(
        name=payload.name,
        currency=payload.currency.upper(),
        owner_user_id=owner_id,
        balance_minor=0,
        is_system_account=is_system,
    )
    session.add(account)
    session.commit()
    session.refresh(account)

    return {
        "id": str(account.id),
        "name": account.name,
        "currency": account.currency,
        "balance_minor": account.balance_minor,
        "is_system_account": account.is_system_account,
        "owner_user_id": str(account.owner_user_id) if account.owner_user_id else None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


@app.get("/accounts", tags=["accounts"])
def list_accounts(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> list[dict]:
    is_privileged = current_user.role in (UserRole.ADMIN, UserRole.AUDITOR) or str(
        current_user.role
    ) in ("admin", "auditor")

    if is_privileged:
        accounts = session.query(Account).all()
    else:
        accounts = session.query(Account).filter_by(owner_user_id=current_user.id).all()

    return [
        {
            "id": str(acc.id),
            "name": acc.name,
            "currency": acc.currency,
            "balance_minor": acc.balance_minor,
            "is_system_account": acc.is_system_account,
            "owner_user_id": str(acc.owner_user_id) if acc.owner_user_id else None,
            "created_at": acc.created_at.isoformat() if acc.created_at else None,
        }
        for acc in accounts
    ]


@app.get("/accounts/{account_id}", tags=["accounts"])
def get_account_detail(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_privileged = current_user.role in (UserRole.ADMIN, UserRole.AUDITOR) or str(
        current_user.role
    ) in ("admin", "auditor")

    if not is_privileged and account.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access to this account",
        )

    return {
        "id": str(account.id),
        "name": account.name,
        "currency": account.currency,
        "balance_minor": account.balance_minor,
        "is_system_account": account.is_system_account,
        "owner_user_id": str(account.owner_user_id) if account.owner_user_id else None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


# --- Money Movement Endpoints ---


@app.post("/transfers", tags=["money-movement"])
def transfer_money(
    payload: TransferRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.ACCOUNT_HOLDER)),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    return execute_transfer(
        session=session,
        actor=current_user,
        source_account_id=payload.source_account_id,
        destination_account_id=payload.destination_account_id,
        amount_minor=payload.amount_minor,
        idempotency_key=idempotency_key,
        path="/transfers",
        description=payload.description,
    )


@app.post("/deposits", tags=["money-movement"])
def deposit_money(
    payload: DepositRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.ACCOUNT_HOLDER)),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    return execute_deposit(
        session=session,
        actor=current_user,
        account_id=payload.account_id,
        amount_minor=payload.amount_minor,
        idempotency_key=idempotency_key,
        path="/deposits",
        description=payload.description,
    )


@app.post("/withdrawals", tags=["money-movement"])
def withdraw_money(
    payload: WithdrawalRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.ACCOUNT_HOLDER)),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    return execute_withdrawal(
        session=session,
        actor=current_user,
        account_id=payload.account_id,
        amount_minor=payload.amount_minor,
        idempotency_key=idempotency_key,
        path="/withdrawals",
        description=payload.description,
    )


# --- Ledger, Statements & Audit Endpoints ---


@app.get("/statements/{account_id}", tags=["ledger"])
def get_account_statement(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    _rate=Depends(rate_limiter()),
) -> dict:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_privileged = current_user.role in (UserRole.ADMIN, UserRole.AUDITOR) or str(
        current_user.role
    ) in ("admin", "auditor")
    if not is_privileged and account.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access to this statement",
        )

    entries = (
        session.query(LedgerEntry)
        .filter_by(account_id=account_id)
        .order_by(LedgerEntry.entry_sequence.asc())
        .all()
    )

    return {
        "account_id": str(account.id),
        "account_name": account.name,
        "currency": account.currency,
        "current_balance_minor": account.balance_minor,
        "entries": [
            {
                "id": str(e.id),
                "journal_transaction_id": str(e.journal_transaction_id),
                "amount_minor": e.amount_minor,
                "balance_after_minor": e.balance_after_minor,
                "entry_sequence": e.entry_sequence,
                "entry_hash": e.entry_hash,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


@app.get("/ledger/verify", tags=["ledger"])
def verify_ledger_integrity(
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AUDITOR)),
    session: Session = Depends(get_session),
) -> dict:
    return verify_ledger_hash_chain(session)


@app.get("/ledger/reconciliation", tags=["ledger"])
def reconcile_ledger(
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AUDITOR)),
    session: Session = Depends(get_session),
) -> dict:
    return reconcile_ledger_balances(session)


@app.get("/audit/events", tags=["audit"])
def list_audit_events(
    account_id: UUID | None = None,
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AUDITOR)),
    session: Session = Depends(get_session),
    limit: int = 100,
) -> list[dict]:
    query = session.query(AuditEvent)
    if account_id:
        query = query.filter_by(account_id=account_id)
    events = query.order_by(AuditEvent.created_at.desc()).limit(limit).all()

    return [
        {
            "id": str(ev.id),
            "actor_user_id": str(ev.actor_user_id) if ev.actor_user_id else None,
            "account_id": str(ev.account_id) if ev.account_id else None,
            "action": ev.action,
            "outcome": ev.outcome,
            "details": ev.details,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
    ]


# Mount static assets
static_directory = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_directory, html=True), name="dashboard")
