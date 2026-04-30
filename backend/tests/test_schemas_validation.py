"""Tests for lead management Marshmallow schemas."""
import pytest
from marshmallow import ValidationError

from app.schemas import (
    AnalyzeLeadRequestSchema,
    BulkEnrichRequestSchema,
    EnrichLeadRequestSchema,
    FieldMappingRequestSchema,
    ImportAuthRequestSchema,
    ImportHeadersQuerySchema,
    ImportJobsQuerySchema,
    ImportSheetsQuerySchema,
    ImportStartRequestSchema,
    LeadDetailResponseSchema,
    LeadListQuerySchema,
    MarketingListAddMembersSchema,
    MarketingListCreateSchema,
    MarketingListMembersQuerySchema,
    MarketingListRemoveMembersSchema,
    MarketingListRenameSchema,
    MarketingListsQuerySchema,
    OutreachStatusUpdateSchema,
    ScoringWeightsQuerySchema,
    ScoringWeightsUpdateSchema,
)


# ---------------------------------------------------------------------------
# LeadListQuerySchema
# ---------------------------------------------------------------------------

class TestLeadListQuerySchema:
    def setup_method(self):
        self.schema = LeadListQuerySchema()

    def test_defaults(self):
        result = self.schema.load({})
        assert result['page'] == 1
        assert result['per_page'] == 20
        assert result['sort_by'] == 'created_at'
        assert result['sort_order'] == 'desc'

    def test_valid_filters(self):
        result = self.schema.load({
            'property_type': 'SINGLE_FAMILY',
            'city': 'Austin',
            'state': 'TX',
            'zip': '78701',
            'owner_name': 'Smith',
            'score_min': 50.0,
            'score_max': 90.0,
            'marketing_list_id': 3,
            'sort_by': 'lead_score',
            'sort_order': 'asc',
        })
        assert result['property_type'] == 'SINGLE_FAMILY'
        assert result['score_min'] == 50.0
        assert result['sort_by'] == 'lead_score'

    def test_score_min_greater_than_max_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({'score_min': 80, 'score_max': 20})
        assert 'score_min' in str(exc_info.value.messages)

    def test_invalid_sort_field_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'sort_by': 'invalid_field'})

    def test_invalid_sort_order_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'sort_order': 'sideways'})

    def test_page_below_min_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'page': 0})

    def test_per_page_above_max_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'per_page': 101})

    def test_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'score_min': -1})
        with pytest.raises(ValidationError):
            self.schema.load({'score_max': 101})


# ---------------------------------------------------------------------------
# AnalyzeLeadRequestSchema
# ---------------------------------------------------------------------------

class TestAnalyzeLeadRequestSchema:
    def setup_method(self):
        self.schema = AnalyzeLeadRequestSchema()

    def test_valid(self):
        result = self.schema.load({'user_id': 'user123'})
        assert result['user_id'] == 'user123'

    def test_missing_user_id(self):
        with pytest.raises(ValidationError):
            self.schema.load({})

    def test_empty_user_id(self):
        with pytest.raises(ValidationError):
            self.schema.load({'user_id': ''})


# ---------------------------------------------------------------------------
# ScoringWeightsUpdateSchema
# ---------------------------------------------------------------------------

class TestScoringWeightsUpdateSchema:
    def setup_method(self):
        self.schema = ScoringWeightsUpdateSchema()

    def test_valid_weights(self):
        result = self.schema.load({
            'user_id': 'test',
            'property_characteristics_weight': 0.30,
            'data_completeness_weight': 0.20,
            'owner_situation_weight': 0.30,
            'location_desirability_weight': 0.20,
        })
        assert result['user_id'] == 'test'

    def test_weights_not_summing_to_one_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self.schema.load({
                'user_id': 'test',
                'property_characteristics_weight': 0.5,
                'data_completeness_weight': 0.5,
                'owner_situation_weight': 0.5,
                'location_desirability_weight': 0.5,
            })
        assert 'sum to 1.0' in str(exc_info.value.messages)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({
                'user_id': 'test',
                'property_characteristics_weight': -0.1,
                'data_completeness_weight': 0.4,
                'owner_situation_weight': 0.4,
                'location_desirability_weight': 0.3,
            })

    def test_weight_above_one_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({
                'user_id': 'test',
                'property_characteristics_weight': 1.1,
                'data_completeness_weight': 0.0,
                'owner_situation_weight': 0.0,
                'location_desirability_weight': 0.0,
            })

    def test_missing_weight_field_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({
                'user_id': 'test',
                'property_characteristics_weight': 0.5,
                # missing other weights
            })


# ---------------------------------------------------------------------------
# FieldMappingRequestSchema
# ---------------------------------------------------------------------------

class TestFieldMappingRequestSchema:
    def setup_method(self):
        self.schema = FieldMappingRequestSchema()

    def test_valid_mapping(self):
        result = self.schema.load({
            'user_id': 'u1',
            'spreadsheet_id': 's1',
            'sheet_name': 'Sheet1',
            'mapping': {
                'Phone': 'phone_1',
            },
        })
        assert 'phone_1' in result['mapping'].values()

    def test_any_single_field_mapping_accepted(self):
        """No required DB fields — any non-empty mapping is valid."""
        result = self.schema.load({
            'user_id': 'u1',
            'spreadsheet_id': 's1',
            'sheet_name': 'Sheet1',
            'mapping': {'Col A': 'phone_1'},
        })
        assert result['mapping'] == {'Col A': 'phone_1'}

    def test_empty_mapping_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({
                'user_id': 'u1',
                'spreadsheet_id': 's1',
                'sheet_name': 'Sheet1',
                'mapping': {},
            })

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            self.schema.load({'mapping': {'A': 'property_street'}})


# ---------------------------------------------------------------------------
# ImportStartRequestSchema
# ---------------------------------------------------------------------------

class TestImportStartRequestSchema:
    def setup_method(self):
        self.schema = ImportStartRequestSchema()

    def test_valid(self):
        result = self.schema.load({
            'user_id': 'u1',
            'spreadsheet_id': 'abc123',
            'sheet_name': 'Sheet1',
        })
        assert result['field_mapping_id'] is None

    def test_with_field_mapping_id(self):
        result = self.schema.load({
            'user_id': 'u1',
            'spreadsheet_id': 'abc123',
            'sheet_name': 'Sheet1',
            'field_mapping_id': 42,
        })
        assert result['field_mapping_id'] == 42

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            self.schema.load({})


# ---------------------------------------------------------------------------
# ImportJobsQuerySchema
# ---------------------------------------------------------------------------

class TestImportJobsQuerySchema:
    def setup_method(self):
        self.schema = ImportJobsQuerySchema()

    def test_defaults(self):
        result = self.schema.load({})
        assert result['page'] == 1
        assert result['per_page'] == 20
        assert result['user_id'] is None
        assert result['status'] is None

    def test_valid_status_filter(self):
        result = self.schema.load({'status': 'completed'})
        assert result['status'] == 'completed'

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'status': 'invalid'})


# ---------------------------------------------------------------------------
# OutreachStatusUpdateSchema
# ---------------------------------------------------------------------------

class TestOutreachStatusUpdateSchema:
    def setup_method(self):
        self.schema = OutreachStatusUpdateSchema()

    def test_valid_statuses(self):
        for status in ['not_contacted', 'contacted', 'responded', 'converted', 'opted_out']:
            result = self.schema.load({'status': status})
            assert result['status'] == status

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'status': 'unknown'})

    def test_missing_status_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({})


# ---------------------------------------------------------------------------
# EnrichLeadRequestSchema / BulkEnrichRequestSchema
# ---------------------------------------------------------------------------

class TestEnrichLeadRequestSchema:
    def setup_method(self):
        self.schema = EnrichLeadRequestSchema()

    def test_valid(self):
        result = self.schema.load({'source_name': 'county_records'})
        assert result['source_name'] == 'county_records'

    def test_missing_source_name(self):
        with pytest.raises(ValidationError):
            self.schema.load({})

    def test_empty_source_name(self):
        with pytest.raises(ValidationError):
            self.schema.load({'source_name': ''})


class TestBulkEnrichRequestSchema:
    def setup_method(self):
        self.schema = BulkEnrichRequestSchema()

    def test_valid(self):
        result = self.schema.load({'lead_ids': [1, 2, 3], 'source_name': 'mls'})
        assert len(result['lead_ids']) == 3

    def test_empty_lead_ids_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'lead_ids': [], 'source_name': 'mls'})

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            self.schema.load({})


# ---------------------------------------------------------------------------
# MarketingList Schemas
# ---------------------------------------------------------------------------

class TestMarketingListCreateSchema:
    def setup_method(self):
        self.schema = MarketingListCreateSchema()

    def test_valid_without_filters(self):
        result = self.schema.load({'name': 'Hot Leads', 'user_id': 'u1'})
        assert result['filter_criteria'] is None

    def test_valid_with_filters(self):
        result = self.schema.load({
            'name': 'Austin Leads',
            'user_id': 'u1',
            'filter_criteria': {'city': 'Austin', 'state': 'TX'},
        })
        assert result['filter_criteria']['city'] == 'Austin'

    def test_missing_name(self):
        with pytest.raises(ValidationError):
            self.schema.load({'user_id': 'u1'})


class TestMarketingListRenameSchema:
    def setup_method(self):
        self.schema = MarketingListRenameSchema()

    def test_valid(self):
        result = self.schema.load({'name': 'New Name'})
        assert result['name'] == 'New Name'

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'name': ''})


class TestMarketingListAddMembersSchema:
    def setup_method(self):
        self.schema = MarketingListAddMembersSchema()

    def test_valid(self):
        result = self.schema.load({'lead_ids': [1, 2, 3]})
        assert result['lead_ids'] == [1, 2, 3]

    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'lead_ids': []})


class TestMarketingListRemoveMembersSchema:
    def setup_method(self):
        self.schema = MarketingListRemoveMembersSchema()

    def test_valid(self):
        result = self.schema.load({'lead_ids': [5]})
        assert result['lead_ids'] == [5]

    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'lead_ids': []})


# ---------------------------------------------------------------------------
# ImportAuthRequestSchema
# ---------------------------------------------------------------------------

class TestImportAuthRequestSchema:
    def setup_method(self):
        self.schema = ImportAuthRequestSchema()

    def test_valid(self):
        result = self.schema.load({
            'credentials': {'client_id': 'abc', 'client_secret': 'xyz'},
            'user_id': 'u1',
        })
        assert result['user_id'] == 'u1'

    def test_default_user_id(self):
        result = self.schema.load({
            'credentials': {'client_id': 'abc'},
        })
        assert result['user_id'] == 'default'

    def test_empty_credentials_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({'credentials': {}})

    def test_missing_credentials_rejected(self):
        with pytest.raises(ValidationError):
            self.schema.load({})
