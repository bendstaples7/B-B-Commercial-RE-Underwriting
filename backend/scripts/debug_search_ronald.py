"""Debug why /api/search returns empty for Ronald J in browser."""
from dotenv import load_dotenv

load_dotenv()

from app import create_app, db
from app.models.lead import Property as Lead
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.search_service import SearchService, tokenize_query
from sqlalchemy import or_, text


def main():
    app = create_app()
    with app.app_context():
        print('tokens:', tokenize_query('ronald j'))

        ronald_leads = Lead.query.filter(
            or_(
                Lead.owner_last_name.ilike('%jutkins%'),
                Lead.owner_first_name.ilike('%ronald%'),
            )
        ).limit(10).all()
        print('\nRonald/Jutkins leads in DB:')
        for lead in ronald_leads:
            print(
                f'  id={lead.id} name={lead.owner_first_name} {lead.owner_last_name} '
                f'owner_user_id={lead.owner_user_id}'
            )

        users = User.query.filter(User.is_active.is_(True)).order_by(User.email_lower).limit(20).all()
        print('\nActive users (sample):')
        for u in users:
            print(f'  {u.user_id} {u.email_lower} admin={u.is_admin}')

        ben = User.query.filter_by(email_lower='ben.d.staples.7@gmail.com').first()
        if ben:
            svc = SearchService()
            for q in ['ronald j', 'Ronald J', 'jutkins']:
                r = svc.search(q, user_id=ben.user_id, is_admin=ben.is_admin, page=1, per_page=5)
                print(f"\nSearch as Ben ({ben.user_id}): q={q!r} total={r.leads_total}")

        # Try each user that might be logged in as "B"
        for u in users:
            if u.email_lower and 'ben' in u.email_lower:
                r = SearchService().search('ronald j', user_id=u.user_id, is_admin=u.is_admin, page=1, per_page=5)
                if r.leads_total > 0:
                    print(f"  MATCH for {u.email_lower}: {r.leads_total} leads")

        # Simulate HTTP with JWT against running server
        if ben:
            token = AuthService().issue_token(ben)
            import json
            import urllib.request

            for q in ['ronald%20j', 'Ronald%20J']:
                req = urllib.request.Request(
                    f'http://127.0.0.1:5000/api/search?q={q}&page=1&per_page=5',
                    headers={'Authorization': f'Bearer {token}'},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                print(f"\nHTTP running server q={q}: leads_total={data.get('leads_total')}")

            # Fresh app test client (same code on disk, not stale process)
            with app.test_client() as client:
                for q in ['ronald j', 'Ronald J']:
                    resp = client.get(
                        f'/api/search?q={q}&page=1&per_page=5',
                        headers={'Authorization': f'Bearer {token}'},
                    )
                    data = resp.get_json()
                    print(f"Test client q={q!r}: status={resp.status_code} leads_total={data.get('leads_total')}")


if __name__ == '__main__':
    main()
