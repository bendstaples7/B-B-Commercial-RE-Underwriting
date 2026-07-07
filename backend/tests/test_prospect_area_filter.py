"""Tests for prospect geographic area filter."""
from app.models.motivation_signal import ProspectAreaFilter, ProspectCandidate
from app.services.prospect_area_filter_service import (
    apply_area_filter_to_candidates,
    point_in_polygon,
    polygon_ring,
    save_area_filter,
)


def _north_side_polygon() -> dict:
    return {
        'type': 'Polygon',
        'coordinates': [[
            [-87.72, 41.92],
            [-87.62, 41.92],
            [-87.62, 42.02],
            [-87.72, 42.02],
            [-87.72, 41.92],
        ]],
    }


def _south_side_polygon() -> dict:
    return {
        'type': 'Polygon',
        'coordinates': [[
            [-87.72, 41.64],
            [-87.62, 41.64],
            [-87.62, 41.74],
            [-87.72, 41.74],
            [-87.72, 41.64],
        ]],
    }


class TestPointInPolygon:
    def test_inside_rectangle(self):
        ring = polygon_ring(_north_side_polygon())
        assert ring is not None
        assert point_in_polygon(41.97, -87.67, ring) is True

    def test_outside_rectangle(self):
        ring = polygon_ring(_north_side_polygon())
        assert ring is not None
        assert point_in_polygon(41.70, -87.67, ring) is False


class TestProspectAreaFilterService:
    def test_save_and_apply_filter(self, app, db_session):
        save_area_filter(
            'user-1',
            enabled=True,
            geometry=_north_side_polygon(),
            label='North Side',
        )
        north = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street='100 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            latitude=41.97,
            longitude=-87.67,
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='stacked',
            external_key='stacked:north',
            status='pending',
        )
        south = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0001',
            property_street='200 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            latitude=41.70,
            longitude=-87.67,
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='stacked',
            external_key='stacked:south',
            status='pending',
        )
        db_session.add_all([north, south])
        db_session.commit()

        filtered, stats = apply_area_filter_to_candidates([north, south], 'user-1')
        assert stats.filter_enabled is True
        assert stats.total_unfiltered == 2
        assert stats.total_filtered == 1
        assert filtered[0].id == north.id

    def test_filter_disabled_returns_all(self, app, db_session):
        row = ProspectAreaFilter(
            user_id='user-1',
            enabled=False,
            geometry=_north_side_polygon(),
        )
        db_session.add(row)
        candidate = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street='100 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            latitude=41.70,
            longitude=-87.67,
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='stacked',
            external_key='stacked:one',
            status='pending',
        )
        db_session.add(candidate)
        db_session.commit()

        filtered, stats = apply_area_filter_to_candidates([candidate], 'user-1')
        assert stats.filter_enabled is False
        assert len(filtered) == 1

    def test_enabled_invalid_geometry_reports_filter_enabled(self, app, db_session):
        row = ProspectAreaFilter(
            user_id='user-1',
            enabled=True,
            geometry={'type': 'Polygon', 'coordinates': []},
        )
        db_session.add(row)
        candidate = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street='100 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            latitude=41.70,
            longitude=-87.67,
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='stacked',
            external_key='stacked:invalid-geom',
            status='pending',
        )
        db_session.add(candidate)
        db_session.commit()

        filtered, stats = apply_area_filter_to_candidates([candidate], 'user-1')
        assert stats.filter_enabled is True
        assert len(filtered) == 1


class TestProspectQueueAreaFilter:
    def test_list_and_count_respect_area_filter(self, app, db_session):
        from app.services.prospect_review_service import count_pending_candidates, list_candidates

        save_area_filter('user-1', enabled=True, geometry=_south_side_polygon())

        south = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0000',
            property_street='100 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            latitude=41.70,
            longitude=-87.67,
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='stacked',
            external_key='stacked:south-only',
            status='pending',
        )
        north = ProspectCandidate(
            owner_user_id='user-1',
            pin='14-28-400-008-0001',
            property_street='200 MAIN ST',
            property_city='Chicago',
            property_state='IL',
            latitude=41.97,
            longitude=-87.67,
            primary_signal_type='TAX_ANNUAL_SALE',
            motivation_score=15.0,
            source_feed='stacked',
            external_key='stacked:north-only',
            status='pending',
        )
        db_session.add_all([south, north])
        db_session.commit()

        rows, total, stats = list_candidates('user-1', status='pending')
        assert total == 1
        assert rows[0].id == south.id
        assert stats['hidden_outside_area'] == 1
        assert count_pending_candidates('user-1') == 1
