"""Tests for ScenarioAnalysisEngine."""
import pytest
from app.services.scenario_analysis_engine import ScenarioAnalysisEngine
from app.models import ScenarioType


class TestScenarioAnalysisEngine:
    """Test suite for ScenarioAnalysisEngine."""
    
    @pytest.fixture
    def engine(self):
        """Create engine instance."""
        return ScenarioAnalysisEngine()
    
    def test_analyze_wholesale_basic(self, engine):
        """Test basic wholesale scenario calculation."""
        # Given
        conservative_arv = 200000
        estimated_repairs = 30000
        session_id = 1
        
        # When
        scenario = engine.analyze_wholesale(
            conservative_arv=conservative_arv,
            estimated_repairs=estimated_repairs,
            session_id=session_id
        )
        
        # Then
        expected_mao = (200000 * 0.70) - 30000  # 140000 - 30000 = 110000
        expected_contract_price = 110000 * 0.95  # 104500
        expected_fee_low = 104500 * 0.05  # 5225
        expected_fee_high = 104500 * 0.10  # 10450
        
        assert scenario.mao == expected_mao
        assert scenario.contract_price == expected_contract_price
        assert scenario.assignment_fee_low == expected_fee_low
        assert scenario.assignment_fee_high == expected_fee_high
        assert scenario.estimated_repairs == estimated_repairs
        assert scenario.scenario_type == ScenarioType.WHOLESALE
    
    def test_analyze_fix_and_flip_basic(self, engine):
        """Test basic fix and flip scenario calculation."""
        # Given
        acquisition_cost = 100000
        renovation_cost = 50000
        likely_arv = 250000
        months_to_flip = 6
        session_id = 1
        
        # When
        scenario = engine.analyze_fix_and_flip(
            acquisition_cost=acquisition_cost,
            renovation_cost=renovation_cost,
            likely_arv=likely_arv,
            months_to_flip=months_to_flip,
            session_id=session_id
        )
        
        # Then
        expected_holding = (100000 + 50000) * 0.02 * 6  # 18000
        expected_financing = (100000 + 50000) * 0.75 * 0.11 * (6 / 12)  # 6187.5
        expected_closing = 250000 * 0.08  # 20000
        expected_total = 100000 + 50000 + 18000 + 6187.5 + 20000  # 194187.5
        expected_profit = 250000 - 194187.5  # 55812.5
        expected_roi = (55812.5 / ((100000 + 50000) * 0.25)) * 100  # 149.1%
        
        assert scenario.acquisition_cost == acquisition_cost
        assert scenario.renovation_cost == renovation_cost
        assert scenario.holding_costs == expected_holding
        assert abs(scenario.financing_costs - expected_financing) < 0.01
        assert scenario.closing_costs == expected_closing
        assert abs(scenario.total_cost - expected_total) < 0.01
        assert scenario.exit_value == likely_arv
        assert abs(scenario.net_profit - expected_profit) < 0.01
        assert abs(scenario.roi - expected_roi) < 0.1
        assert scenario.scenario_type == ScenarioType.FIX_FLIP
    
    def test_analyze_buy_and_hold_basic(self, engine):
        """Test basic buy and hold scenario calculation."""
        # Given
        market_rent = 2000
        annual_expenses = 6000
        price_points = [150000, 175000, 200000]
        session_id = 1
        
        # When
        scenario = engine.analyze_buy_and_hold(
            market_rent=market_rent,
            annual_expenses=annual_expenses,
            price_points=price_points,
            session_id=session_id
        )
        
        # Then
        assert scenario.market_rent == market_rent
        assert len(scenario.price_points) == 3
        assert scenario.scenario_type == ScenarioType.BUY_HOLD
        
        # Check first price point has both capital structures
        first_price_point = scenario.price_points[0]
        assert first_price_point['purchase_price'] == 150000
        assert len(first_price_point['capital_structure_results']) == 2
        
        # Check owner-occupied structure
        owner_occupied = first_price_point['capital_structure_results'][0]
        assert owner_occupied['name'] == '5% Down Owner-Occupied'
        assert owner_occupied['down_payment_percent'] == 5.0
        assert owner_occupied['interest_rate'] == 6.5
        assert owner_occupied['down_payment'] == 7500
        assert owner_occupied['loan_amount'] == 142500
        assert owner_occupied['monthly_rent'] == 2000
        assert owner_occupied['monthly_expenses'] == 500
        
        # Check investor structure
        investor = first_price_point['capital_structure_results'][1]
        assert investor['name'] == '25% Down Investor'
        assert investor['down_payment_percent'] == 25.0
        assert investor['interest_rate'] == 7.5
        assert investor['down_payment'] == 37500
        assert investor['loan_amount'] == 112500
    
    def test_compare_scenarios_basic(self, engine):
        """Test scenario comparison."""
        # Given
        scenarios = [
            {
                'type': 'wholesale',
                'data': {
                    'mao': 110000,
                    'contract_price': 104500,
                    'assignment_fee_low': 5225,
                    'assignment_fee_high': 10450
                }
            },
            {
                'type': 'fix_flip',
                'data': {
                    'acquisition_cost': 100000,
                    'renovation_cost': 50000,
                    'total_cost': 194187.5,
                    'exit_value': 250000,
                    'net_profit': 55812.5,
                    'roi': 149.1
                }
            }
        ]
        price_points = [100000, 150000, 200000]
        
        # When
        comparison = engine.compare_scenarios(scenarios, price_points)
        
        # Then
        assert len(comparison['price_points']) == 3
        assert comparison['summary']['total_scenarios'] == 2
        assert comparison['summary']['price_points_analyzed'] == 3
        
        # Check first price point
        first_comparison = comparison['price_points'][0]
        assert first_comparison['price_point'] == 100000
        assert len(first_comparison['scenarios']) == 2
        assert first_comparison['highest_roi'] is not None
    
    def test_monthly_payment_calculation(self, engine):
        """Test PMT formula calculation."""
        # Given
        principal = 100000
        annual_rate = 0.06
        months = 360
        
        # When
        payment = engine._calculate_monthly_payment(principal, annual_rate, months)
        
        # Then - Expected payment for $100k at 6% for 30 years is ~$599.55
        assert 595 < payment < 605
    
    def test_monthly_payment_zero_interest(self, engine):
        """Test PMT formula with zero interest."""
        # Given
        principal = 120000
        annual_rate = 0.0
        months = 360
        
        # When
        payment = engine._calculate_monthly_payment(principal, annual_rate, months)
        
        # Then
        assert payment == 120000 / 360  # Simple division when rate is 0
