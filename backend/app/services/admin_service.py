"""Admin service — cross-user visibility for admin users.

Provides read-only access to all users, their activity summaries,
and their leads. No modification of another user's data is permitted.
"""
import bcrypt

from app import db
from app.exceptions import ConflictError, ResourceNotFoundError, ValidationException
from app.models.user import User
from sqlalchemy import text


class AdminService:
    """Service for admin-only cross-user data access."""

    def list_users(self) -> list[dict]:
        """Return all users ordered by created_at ascending.

        Excludes credential fields (password_hash).
        """
        result = db.session.execute(text("""
            SELECT user_id, email, display_name, is_active, is_admin, created_at
            FROM users
            ORDER BY created_at ASC
        """))
        rows = result.fetchall()
        return [
            {
                'user_id': row.user_id,
                'email': row.email,
                'display_name': row.display_name,
                'is_active': row.is_active,
                'is_admin': row.is_admin,
                'created_at': (
                    row.created_at.isoformat()
                    if row.created_at and hasattr(row.created_at, 'isoformat')
                    else row.created_at
                ),
            }
            for row in rows
        ]

    def get_user_summary(self, user_id: str) -> dict:
        """Return a user's profile plus activity counts.

        Raises ResourceNotFoundError if the user_id does not exist.
        """
        result = db.session.execute(text("""
            SELECT
                u.user_id, u.email, u.display_name, u.is_active, u.is_admin, u.created_at,
                (SELECT COUNT(*) FROM leads WHERE owner_user_id = u.user_id) AS lead_count,
                (SELECT COUNT(*) FROM marketing_lists WHERE user_id = u.user_id) AS marketing_list_count,
                (SELECT COUNT(*) FROM import_jobs WHERE user_id = u.user_id) AS import_job_count
            FROM users u
            WHERE u.user_id = :user_id
        """), {'user_id': user_id})
        row = result.fetchone()
        if row is None:
            raise ResourceNotFoundError(f'User {user_id} not found.')
        return {
            'user_id': row.user_id,
            'email': row.email,
            'display_name': row.display_name,
            'is_active': row.is_active,
            'is_admin': row.is_admin,
            'created_at': (
                row.created_at.isoformat()
                if row.created_at and hasattr(row.created_at, 'isoformat')
                else row.created_at
            ),
            'lead_count': row.lead_count,
            'marketing_list_count': row.marketing_list_count,
            'import_job_count': row.import_job_count,
        }

    def list_leads(
        self,
        owner_user_id: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        """Return a paginated list of leads across all users.

        Args:
            owner_user_id: Optional filter — only return leads for this user.
            page: 1-based page number.
            page_size: Number of results per page (max 200).

        Raises ValidationException if page_size > 200.
        """
        if page < 1:
            raise ValidationException('page must be >= 1.')
        if page_size < 1:
            raise ValidationException('page_size must be >= 1.')
        if page_size > 200:
            raise ValidationException('page_size cannot exceed 200.')

        offset = (page - 1) * page_size

        where_clause = 'WHERE l.owner_user_id = :owner_user_id' if owner_user_id else ''
        params: dict = {'page_size': page_size, 'offset': offset}
        if owner_user_id:
            params['owner_user_id'] = owner_user_id

        count_result = db.session.execute(text(f"""
            SELECT COUNT(*) AS total
            FROM leads l
            {where_clause}
        """), params)
        total_count = count_result.fetchone().total

        leads_result = db.session.execute(text(f"""
            SELECT
                l.id, l.owner_user_id, u.display_name AS owner_display_name,
                l.property_street, l.property_city, l.property_state,
                l.lead_status, l.lead_score, l.created_at
            FROM leads l
            JOIN users u ON u.user_id = l.owner_user_id
            {where_clause}
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT :page_size OFFSET :offset
        """), params)
        rows = leads_result.fetchall()

        leads = [
            {
                'id': row.id,
                'owner_user_id': row.owner_user_id,
                'owner_display_name': row.owner_display_name,
                'property_street': row.property_street,
                'property_city': row.property_city,
                'property_state': row.property_state,
                'lead_status': row.lead_status,
                'lead_score': row.lead_score,
                'created_at': (
                    row.created_at.isoformat()
                    if row.created_at and hasattr(row.created_at, 'isoformat')
                    else row.created_at
                ),
            }
            for row in rows
        ]

        return {
            'leads': leads,
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
        }

    def update_user(self, user_id: str, display_name: str | None, email: str | None) -> dict:
        """Update a user's display_name and/or email. Admin-only operation.

        Args:
            user_id: The user_id of the user to update.
            display_name: New display name (optional, non-empty, max 100 chars).
            email: New email address (optional, must contain '@', must be unique).

        Returns:
            Updated user dict (same shape as list_users rows — no password_hash).

        Raises:
            ValidationException: If neither field provided, or validation fails.
            ResourceNotFoundError: If the user_id does not exist.
            ConflictError: If the new email is already in use by another user.
        """
        # Normalise empty strings to None so callers can pass '' or None interchangeably.
        if display_name is not None and display_name.strip() == '':
            display_name = None
        if email is not None and email.strip() == '':
            email = None

        if display_name is None and email is None:
            raise ValidationException('At least one of display_name or email must be provided.')

        if display_name is not None:
            if len(display_name) > 100:
                raise ValidationException('display_name must be 100 characters or fewer.')

        if email is not None:
            if '@' not in email:
                raise ValidationException('email must contain @.')

        user = User.query.filter_by(user_id=user_id).first()
        if user is None:
            raise ResourceNotFoundError(f'User {user_id} not found.')

        if email is not None:
            email_lower = email.lower()
            conflict = User.query.filter(
                User.email_lower == email_lower,
                User.user_id != user_id,
            ).first()
            if conflict is not None:
                raise ConflictError('Email already in use.')
            user.email = email
            user.email_lower = email_lower

        if display_name is not None:
            user.display_name = display_name

        db.session.commit()

        return {
            'user_id': user.user_id,
            'email': user.email,
            'display_name': user.display_name,
            'is_active': user.is_active,
            'is_admin': user.is_admin,
            'created_at': (
                user.created_at.isoformat()
                if user.created_at and hasattr(user.created_at, 'isoformat')
                else user.created_at
            ),
        }

    def reset_user_password(self, user_id: str, new_password: str, requesting_admin_id: str) -> None:
        """Reset a user's password. Admin-only operation.

        Args:
            user_id: The user_id of the user whose password to reset.
            new_password: The new plaintext password (min 8 chars).
            requesting_admin_id: The user_id of the admin making the request.

        Raises:
            ValidationException: If new_password is < 8 chars or user_id == requesting_admin_id.
            ResourceNotFoundError: If the user_id does not exist.
        """
        if user_id == requesting_admin_id:
            raise ValidationException('Use the standard password change flow to update your own password.')

        if not new_password or len(new_password) < 8:
            raise ValidationException('Password must be at least 8 characters.')

        user = User.query.filter_by(user_id=user_id).first()
        if user is None:
            raise ResourceNotFoundError(f'User {user_id} not found.')

        user.password_hash = bcrypt.hashpw(
            new_password.encode('utf-8'),
            bcrypt.gensalt(rounds=12),
        ).decode('utf-8')
        user.password_set = True
        db.session.commit()
