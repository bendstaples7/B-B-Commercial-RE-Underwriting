"""Authentication service — user creation, credential verification, and JWT lifecycle."""
import uuid
from datetime import datetime, timedelta

import bcrypt
import jwt
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.exceptions import ConflictError, PasswordSetupRequiredException, ValidationException
from app.models.user import User


class AuthService:
    """Handles user account creation, authentication, and JWT issuance/verification."""

    TOKEN_LIFETIME_SECONDS = 30 * 24 * 3600  # 30 days

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, email: str, password: str, display_name: str) -> User:
        """Create a new user account.

        Args:
            email: The user's email address (stored as-is; email_lower is derived).
            password: Plaintext password — hashed with bcrypt work factor 12.
            display_name: Human-readable display name (max 100 chars).

        Returns:
            The newly created and committed ``User`` instance.

        Raises:
            ValidationException: If any required field is absent or empty.
            ConflictError: If a user with the same email (case-insensitive) already exists.
        """
        # Validate required fields
        if not email or not email.strip():
            raise ValidationException("Email is required.", field="email")
        if not password or not password.strip():
            raise ValidationException("Password is required.", field="password")
        if not display_name or not display_name.strip():
            raise ValidationException("Display name is required.", field="display_name")

        email_lower = email.lower()

        # Hash password with bcrypt work factor 12
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        ).decode("utf-8")

        user = User(
            user_id=str(uuid.uuid4()),
            email=email,
            email_lower=email_lower,
            password_hash=password_hash,
            display_name=display_name,
            is_active=True,
            password_set=True,   # create_user always sets a real password hash
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        try:
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ConflictError("Email already registered.")

        return user

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, email: str, password: str) -> User | None:
        """Verify credentials and return the matching active User, or None.

        Uses case-insensitive email lookup via the ``email_lower`` column.
        Returns ``None`` for wrong password or inactive user — never reveals which.

        Args:
            email: The submitted email address.
            password: The submitted plaintext password.

        Returns:
            The authenticated ``User`` instance, or ``None`` on failure.
        """
        if not email or not password:
            return None

        user = User.query.filter_by(email_lower=email.lower()).first()

        if user is None:
            # Run a dummy check at the same cost factor as real password checks
            # to prevent timing attacks that reveal whether an email exists.
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=12)))
            return None

        # Users provisioned by an admin may have no password yet (empty hash).
        # Skip bcrypt entirely — there is nothing to verify against — and raise
        # PasswordSetupRequiredException so the caller can issue a setup token.
        # Note: both checks below are intentional:
        #   - empty password_hash: migration-seeded user with no hash at all
        #   - password_set==False: user whose hash may exist but was never confirmed
        # The second check (password_set) runs after is_active to avoid leaking
        # account existence for users who submit a wrong password.
        if not user.password_hash:
            if not user.is_active:
                return None
            raise PasswordSetupRequiredException(user)

        if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
            return None

        if not user.is_active:
            return None

        # Raise after confirming the user is active to avoid leaking account
        # existence for totally wrong passwords.
        if not user.password_set:
            raise PasswordSetupRequiredException(user)

        return user

    # ------------------------------------------------------------------
    # JWT lifecycle
    # ------------------------------------------------------------------

    def issue_setup_token(self, user: User) -> str:
        """Issue a short-lived setup JWT for a user who has not yet set their password.

        This token can ONLY be used with POST /api/auth/set-password.
        It is explicitly rejected by require_auth.

        Claims: sub, setup_required=True, iat, exp (1 hour lifetime).
        No is_admin claim — this token cannot authenticate any other endpoint.
        """
        now = datetime.utcnow()
        payload = {
            "sub": user.user_id,
            "setup_required": True,
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        return jwt.encode(
            payload,
            current_app.config["SECRET_KEY"],
            algorithm="HS256",
        )

    def issue_token(self, user: User) -> str:
        """Issue a signed HS256 JWT for the given user.

        Claims: ``sub``, ``email``, ``display_name``, ``iat``, ``exp``.
        Lifetime: 30 days from issuance.

        Args:
            user: The authenticated ``User`` instance.

        Returns:
            A signed JWT string.
        """
        now = datetime.utcnow()
        payload = {
            "sub": user.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "is_admin": bool(user.is_admin),
            "iat": now,
            "exp": now + timedelta(seconds=self.TOKEN_LIFETIME_SECONDS),
        }
        return jwt.encode(
            payload,
            current_app.config["SECRET_KEY"],
            algorithm="HS256",
        )

    def verify_token(self, token: str) -> dict:
        """Decode and verify a JWT, returning its claims.

        Args:
            token: The raw JWT string (without the ``Bearer `` prefix).

        Returns:
            The decoded claims dictionary.

        Raises:
            jwt.ExpiredSignatureError: If the token's ``exp`` claim is in the past.
            jwt.InvalidTokenError: If the token is malformed or has an invalid signature.
        """
        return jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=["HS256"],
        )

    @staticmethod
    def email_domain_for_log(email: str) -> str:
        """Return the email domain for PII-safe auth failure logs.

        Never returns the local part. Missing or malformed addresses become
        ``unknown``.
        """
        if not email or "@" not in email:
            return "unknown"
        domain = email.rsplit("@", 1)[-1].strip().lower()
        return domain or "unknown"

    @staticmethod
    def token_lifetime_claims(token: str) -> dict[str, int]:
        """Decode ``iat``/``exp`` from a just-issued JWT for logging only.

        Does not verify the signature (caller already holds a token it just
        minted). Never returns or logs the token string itself.
        """
        claims = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        iat = int(claims["iat"])
        exp = int(claims["exp"])
        return {
            "iat": iat,
            "exp": exp,
            "lifetime_seconds": exp - iat,
        }
