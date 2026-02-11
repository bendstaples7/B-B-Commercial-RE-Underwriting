"""Tests for ReportGenerator service."""
import pytest
from datetime import date, datetime
from app.services.report_generator import ReportGenerator
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition
from app.models.comparable_sale import ComparableSale
from app.models.ranked_comparable import RankedComparable
from app.models.valuation_result import ValuationResult, ComparableValuation
from app.models.analysis_session import AnalysisSession, WorkflowStep
from app.models.scenario import WholesaleScenario, FixFlipScenario, BuyHoldScenario, ScenarioType


@pytest.fixture
def report_generator():
    """Create ReportGenerator instance."""
    return ReportGenerator()


@pytest.fixture
def mock_session(app):
    """Create a mock analysis session with all data."""
    from app import db
    
    # Create session
    session = AnalysisSession(
        session_id='test-session-123',
        user_id='test-user',
        current_step=WorkflowStep.REPORT_GENERATION
    )
    db.session.add(session)
    db.session.flush()
    
    # Create subject property
    subject = PropertyFacts(
        session_id=session.id,
        address='123 Main St, Chicago, IL',
        property_type=PropertyType.MULTI_FAMILY,
        units=4,
        bedrooms=8,
        bathrooms=4.0,
        square_footage=3200,
        lot_size=5000,
        year_built=1920,
        construction_type=ConstructionType.BRICK,
        basement=True,
        parking_spaces=2,
        last_sale_price=400000.0,
        last_sale_date=date(2020, 5, 15),
        assessed_value=380000.0,
        annual_taxes=8000.0,
        zoning='R-4',
        interior_condition=InteriorCondition.AVERAGE,
        latitude=41.8781,
        longitude=-87.6298,
        data_source='MLS'
    )
    db.session.add(subject)
    
    # Create comparable sales
    comp1 = ComparableSale(
        session_id=session.id,
        address='456 Oak Ave, Chicago, IL',
        sale_date=date(2023, 10, 1),
        sale_price=425000.0,
        property_type=PropertyType.MULTI_FAMILY,
        units=4,
        bedrooms=8,
        bathrooms=4.0,
        square_footage=3100,
        lot_size=4800,
        year_built=1925,
        construction_type=ConstructionType.BRICK,
        interior_condition=InteriorCondition.AVERAGE,
        distance_miles=0.3,
        latitude=41.8790,
        longitude=-87.6300
    )
    db.session.add(comp1)
    db.session.flush()
    
    # Create ranked comparable
    ranked1 = RankedComparable(
        comparable_id=comp1.id,
        session_id=session.id,
        rank=1,
        total_score=92.5,
        recency_score=95.0,
        proximity_score=98.0,
        units_score=100.0,
        beds_baths_score=100.0,
        sqft_score=96.0,
        construction_score=100.0,
        interior_score=100.0
    )
    db.session.add(ranked1)
    
    # Create valuation result
    valuation_result = ValuationResult(
        session_id=session.id,
        conservative_arv=400000.0,
        likely_arv=425000.0,
        aggressive_arv=450000.0,
        all_valuations=[400000.0, 410000.0, 425000.0, 440000.0, 450000.0],
        key_drivers=[
            'Strong comparable sales in the area',
            'Recent renovations increase value',
            'High demand for multi-family properties'
        ]
    )
    db.session.add(valuation_result)
    db.session.flush()
    
    # Create comparable valuation
    comp_val = ComparableValuation(
        valuation_result_id=valuation_result.id,
        comparable_id=comp1.id,
        price_per_sqft=137.10,
        price_per_unit=106250.0,
        price_per_bedroom=53125.0,
        adjusted_value=425000.0,
        adjustments=[
            {'category': 'square_footage', 'difference': -100, 'adjustment_amount': -5000, 'explanation': 'Subject has 100 more sq ft'}
        ],
        narrative='This comparable is very similar to the subject property with matching units and condition.'
    )
    db.session.add(comp_val)
    
    # Create wholesale scenario
    wholesale = WholesaleScenario(
        session_id=session.id,
        scenario_type=ScenarioType.WHOLESALE,
        purchase_price=280000.0,
        mao=280000.0,
        contract_price=266000.0,
        assignment_fee_low=13300.0,
        assignment_fee_high=26600.0,
        estimated_repairs=0.0,
        summary={'strategy': 'wholesale'}
    )
    db.session.add(wholesale)
    
    db.session.commit()
    
    return session


def test_generate_report_structure(report_generator, mock_session):
    """Test that generate_report creates all required sections."""
    report = report_generator.generate_report(mock_session)
    
    assert 'session_id' in report
    assert report['session_id'] == 'test-session-123'
    assert 'generated_at' in report
    assert 'sections' in report
    
    sections = report['sections']
    assert 'section_a' in sections
    assert 'section_b' in sections
    assert 'section_c' in sections
    assert 'section_d' in sections
    assert 'section_e' in sections
    assert 'section_f' in sections


def test_format_section_a(report_generator, mock_session):
    """Test Section A: Property Facts formatting."""
    section = report_generator.format_section_a(mock_session.subject_property)
    
    assert section['title'] == 'Section A: Subject Property Facts'
    assert 'data' in section
    
    data = section['data']
    assert data['Address'] == '123 Main St, Chicago, IL'
    assert data['Property Type'] == 'Multi Family'
    assert data['Units'] == 4
    assert data['Bedrooms'] == 8
    assert data['Bathrooms'] == 4.0
    assert '3,200' in data['Square Footage']
    assert data['Construction Type'] == 'Brick'


def test_format_section_b(report_generator, mock_session):
    """Test Section B: Comparable Sales formatting."""
    comparables = mock_session.comparables.all()
    section = report_generator.format_section_b(mock_session.subject_property, comparables)
    
    assert section['title'] == 'Section B: Comparable Sales'
    assert 'columns' in section
    assert 'rows' in section
    
    # First row should be subject property
    assert len(section['rows']) == 2  # Subject + 1 comparable
    assert section['rows'][0]['Type'] == 'Subject Property'
    assert section['rows'][0]['Distance'] == 'Subject'
    
    # Second row should be comparable
    assert section['rows'][1]['Type'] == 'Comparable'
    assert '0.30 mi' in section['rows'][1]['Distance']


def test_format_section_c(report_generator, mock_session):
    """Test Section C: Weighted Ranking formatting."""
    ranked_comparables = mock_session.ranked_comparables.order_by(RankedComparable.rank).all()
    section = report_generator.format_section_c(ranked_comparables)
    
    assert section['title'] == 'Section C: Weighted Ranking'
    assert 'columns' in section
    assert 'rows' in section
    
    assert len(section['rows']) == 1
    row = section['rows'][0]
    assert row['Rank'] == 1
    assert '92.5' in row['Total Score']
    assert '95.0' in row['Recency (16%)']


def test_format_section_d(report_generator, mock_session):
    """Test Section D: Valuation Models formatting."""
    section = report_generator.format_section_d(mock_session.valuation_result)
    
    assert section['title'] == 'Section D: Valuation Models'
    assert 'valuations' in section
    
    assert len(section['valuations']) == 1
    valuation = section['valuations'][0]
    assert 'address' in valuation
    assert 'narrative' in valuation
    assert 'metrics' in valuation
    assert 'adjustments' in valuation


def test_format_section_e(report_generator, mock_session):
    """Test Section E: ARV Range formatting."""
    section = report_generator.format_section_e(mock_session.valuation_result)
    
    assert section['title'] == 'Section E: Final ARV Range'
    assert 'arv_range' in section
    
    arv_range = section['arv_range']
    assert 'Conservative (25th Percentile)' in arv_range
    assert 'Likely (Median)' in arv_range
    assert 'Aggressive (75th Percentile)' in arv_range
    assert '$400,000' in arv_range['Conservative (25th Percentile)']
    assert '$425,000' in arv_range['Likely (Median)']
    assert '$450,000' in arv_range['Aggressive (75th Percentile)']


def test_format_section_f(report_generator, mock_session):
    """Test Section F: Key Drivers formatting."""
    key_drivers = mock_session.valuation_result.key_drivers
    section = report_generator.format_section_f(key_drivers)
    
    assert section['title'] == 'Section F: Key Drivers'
    assert 'drivers' in section
    assert len(section['drivers']) == 3
    assert 'Strong comparable sales' in section['drivers'][0]


def test_export_to_excel(report_generator, mock_session):
    """Test Excel export functionality."""
    report = report_generator.generate_report(mock_session)
    excel_bytes = report_generator.export_to_excel(report)
    
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 0
    
    # Verify it's a valid Excel file by checking magic bytes
    # Excel files start with PK (ZIP format)
    assert excel_bytes[:2] == b'PK'


def test_scenario_formatting(report_generator, mock_session):
    """Test scenario analysis formatting."""
    scenarios = mock_session.scenarios.all()
    report = report_generator.generate_report(mock_session)
    
    assert 'scenarios' in report['sections']
    scenario_data = report['sections']['scenarios']
    
    assert 'wholesale' in scenario_data
    assert len(scenario_data['wholesale']) == 1
    
    wholesale = scenario_data['wholesale'][0]
    assert 'mao' in wholesale
    assert 'contract_price' in wholesale
    assert '$280,000' in wholesale['mao']


def test_commercial_property_report_terminology(app):
    """Test that commercial properties use appropriate terminology in reports."""
    with app.app_context():
        generator = ReportGenerator()
        
        # Create commercial property
        subject = PropertyFacts()
        subject.address = "789 Business Blvd"
        subject.property_type = PropertyType.COMMERCIAL
        subject.units = 1
        subject.bedrooms = 0
        subject.bathrooms = 2.0
        subject.square_footage = 5000
        subject.lot_size = 10000
        subject.year_built = 2000
        subject.construction_type = ConstructionType.BRICK
        subject.basement = False
        subject.parking_spaces = 20
        subject.assessed_value = 600000
        subject.annual_taxes = 15000
        subject.zoning = "C1"
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.data_source = "MLS"
        subject.user_modified_fields = []
        
        # Format Section A
        section_a = generator.format_section_a(subject)
        
        # Verify commercial property doesn't include bedrooms/bathrooms in main data
        # (they may be 0 but shouldn't be prominently displayed for commercial)
        assert section_a['property_type'] == 'commercial'
        assert 'Property Type' in section_a['data']
        assert section_a['data']['Property Type'] == 'Commercial'
        
        # Create mock valuation result for Section D
        from app.models.valuation_result import ValuationResult, ComparableValuation
        from app.models.comparable_sale import ComparableSale
        
        valuation_result = ValuationResult()
        valuation_result.conservative_arv = 550000
        valuation_result.likely_arv = 600000
        valuation_result.aggressive_arv = 650000
        valuation_result.all_valuations = [550000, 600000, 650000]
        valuation_result.key_drivers = ["Test driver"]
        
        comp = ComparableSale()
        comp.id = 1
        comp.address = "456 Commerce St"
        comp.sale_price = 580000
        
        comp_val = ComparableValuation()
        comp_val.comparable = comp
        comp_val.comparable_id = 1
        comp_val.price_per_sqft = 116.0
        comp_val.price_per_unit = 580000.0
        comp_val.price_per_bedroom = 600000.0  # This is income cap for commercial
        comp_val.adjusted_value = 590000.0
        comp_val.narrative = "Test narrative"
        comp_val.adjustments = []
        
        valuation_result.comparable_valuations = [comp_val]
        
        # Format Section D with commercial property type
        section_d = generator.format_section_d(valuation_result, PropertyType.COMMERCIAL)
        
        # Verify commercial terminology is used
        assert section_d['property_type'] == 'commercial'
        valuation = section_d['valuations'][0]
        
        # Check that "Income Capitalization" is used instead of "Price per Bedroom"
        assert 'Income Capitalization' in valuation['metrics']
        assert 'Price per Bedroom' not in valuation['metrics']


def test_residential_property_report_terminology(app):
    """Test that residential properties use appropriate terminology in reports."""
    with app.app_context():
        generator = ReportGenerator()
        
        # Create residential property
        subject = PropertyFacts()
        subject.address = "123 Home St"
        subject.property_type = PropertyType.SINGLE_FAMILY
        subject.units = 1
        subject.bedrooms = 3
        subject.bathrooms = 2.0
        subject.square_footage = 2000
        subject.lot_size = 5000
        subject.year_built = 1990
        subject.construction_type = ConstructionType.FRAME
        subject.basement = True
        subject.parking_spaces = 2
        subject.assessed_value = 250000
        subject.annual_taxes = 5000
        subject.zoning = "R1"
        subject.interior_condition = InteriorCondition.AVERAGE
        subject.data_source = "MLS"
        subject.user_modified_fields = []
        
        # Format Section A
        section_a = generator.format_section_a(subject)
        
        # Verify residential property includes bedrooms/bathrooms
        assert section_a['property_type'] == 'single_family'
        assert 'Bedrooms' in section_a['data']
        assert 'Bathrooms' in section_a['data']
        assert 'Basement' in section_a['data']
        
        # Create mock valuation result for Section D
        from app.models.valuation_result import ValuationResult, ComparableValuation
        from app.models.comparable_sale import ComparableSale
        
        valuation_result = ValuationResult()
        valuation_result.conservative_arv = 240000
        valuation_result.likely_arv = 260000
        valuation_result.aggressive_arv = 280000
        valuation_result.all_valuations = [240000, 260000, 280000]
        valuation_result.key_drivers = ["Test driver"]
        
        comp = ComparableSale()
        comp.id = 1
        comp.address = "456 Residential Ave"
        comp.sale_price = 255000
        
        comp_val = ComparableValuation()
        comp_val.comparable = comp
        comp_val.comparable_id = 1
        comp_val.price_per_sqft = 127.5
        comp_val.price_per_unit = 255000.0
        comp_val.price_per_bedroom = 85000.0
        comp_val.adjusted_value = 260000.0
        comp_val.narrative = "Test narrative"
        comp_val.adjustments = []
        
        valuation_result.comparable_valuations = [comp_val]
        
        # Format Section D with residential property type
        section_d = generator.format_section_d(valuation_result, PropertyType.SINGLE_FAMILY)
        
        # Verify residential terminology is used
        assert section_d['property_type'] == 'single_family'
        valuation = section_d['valuations'][0]
        
        # Check that "Price per Bedroom" is used for residential
        assert 'Price per Bedroom' in valuation['metrics']
        assert 'Income Capitalization' not in valuation['metrics']
