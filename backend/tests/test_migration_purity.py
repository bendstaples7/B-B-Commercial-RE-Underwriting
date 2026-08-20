"""Tests for scripts/check_migration_purity.py."""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / 'scripts' / 'check_migration_purity.py'


def _load_mod():
    spec = importlib.util.spec_from_file_location('check_migration_purity', _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_bans_create_app_even_when_allowlisted(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'bad_heal.py'
    f.write_text(
        textwrap.dedent(
            '''
            def upgrade():
                from app import create_app
                app = create_app()
            '''
        ),
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('create_app' in v for v in viol)


def test_bans_qualified_create_app_even_when_allowlisted(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'bad_qualified.py'
    f.write_text(
        textwrap.dedent(
            '''
            import app

            def upgrade():
                app.create_app()
            '''
        ),
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('create_app' in v for v in viol)


def test_bans_multiline_aliased_create_app_even_when_allowlisted(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'bad_multiline.py'
    f.write_text(
        textwrap.dedent(
            '''
            from app import (
                create_app as make_app,
            )

            def upgrade():
                make_app()
            '''
        ),
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('create_app' in v for v in viol)


def test_bans_contact_service(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'bad_cs.py'
    f.write_text(
        'from app.services.contact_service import ContactService\n',
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('ContactService' in v for v in viol)


def test_bans_comma_import_create_app(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'comma_import.py'
    f.write_text(
        'from app import db, create_app\napp = create_app()\n',
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('create_app' in v for v in viol)


def test_bans_multiline_from_import(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'multiline.py'
    f.write_text(
        textwrap.dedent(
            '''
            from app.services.contact_service import (
                ContactService,
            )
            '''
        ),
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('ContactService' in v for v in viol)


def test_bans_contact_service_attribute_alias(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'contact_alias.py'
    f.write_text(
        textwrap.dedent(
            '''
            from app.services import contact_service

            Service = contact_service.ContactService

            def upgrade():
                Service()
            '''
        ),
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=True)
    assert any('ContactService' in v for v in viol)
    assert any('Service(...)' in v for v in viol)


def test_contact_service_call_reports_once(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'contact_call.py'
    f.write_text('ContactService()\n', encoding='utf-8')
    viol = mod.check_file(f, allowlisted=True)
    contact_violations = [v for v in viol if 'ContactService' in v]
    assert len(contact_violations) == 1


def test_allowlisted_app_import_ok(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'ok_helper.py'
    f.write_text(
        'from app.services.lead_merge_utils import dedup_street_key\n',
        encoding='utf-8',
    )
    assert mod.check_file(f, allowlisted=True) == []


def test_non_allowlisted_app_import_fails(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'new_bad.py'
    f.write_text(
        'from app.services.lead_merge_utils import dedup_street_key\n',
        encoding='utf-8',
    )
    viol = mod.check_file(f, allowlisted=False)
    assert any('allowlist' in v for v in viol)


def test_non_allowlisted_comma_app_import_fails(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'new_bad.py'
    f.write_text('import os, app\n', encoding='utf-8')
    viol = mod.check_file(f, allowlisted=False)
    assert any('allowlist' in v for v in viol)


def test_create_app_in_comment_ignored(tmp_path: Path):
    mod = _load_mod()
    f = tmp_path / 'comment_only.py'
    f.write_text(
        '# calls create_app() internally — documentation only\npass\n',
        encoding='utf-8',
    )
    assert mod.check_file(f, allowlisted=False) == []


def test_check_tree_real_chain_passes():
    mod = _load_mod()
    versions = _REPO / 'backend' / 'alembic_migrations' / 'versions'
    allow = _REPO / 'backend' / 'alembic_migrations' / 'purity_allowlist.txt'
    assert versions.is_dir()
    viol = mod.check_tree(versions, allow)
    assert viol == [], viol


def test_load_allowlist_skips_comments(tmp_path: Path):
    mod = _load_mod()
    p = tmp_path / 'al.txt'
    p.write_text('# comment\nfoo.py\n\n', encoding='utf-8')
    assert mod.load_allowlist(p) == {'foo.py'}
