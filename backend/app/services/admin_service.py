"""Admin service — cross-user visibility for admin users.

Provides read-only access to all users, their activity summaries,
and their leads. No modification of another user's data is permitted.
"""
from app import db
from app.exceptions import NotFoundError, ValidationError
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

        Raises NotFoundError if the user_id does not exist.
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
            raise NotFoundError(f'User {user_id} not found.')
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

        Raises ValidationError if page_size > 200.
        """
        if page_size > 200:
            raise ValidationError('page_size cannot exceed 200.')

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
            ORDER BY l.created_at DESC
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
