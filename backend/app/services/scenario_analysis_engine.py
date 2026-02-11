"""Scenario Analysis Engine for investment strategy modeling."""
from typing import Dict, List, Optional, Tuple
from app.models import (
    WholesaleScenario,
    FixFlipScenario,
    BuyHoldScenario,
    ScenarioType,
    PropertyFacts,
    ComparableSale
)


class ScenarioAnalysisEngine:
    """
    Engine for analyzing real estate investment scenarios.
    
    Supports three investment strategies:
    - Wholesale: Quick assignment deals
    - Fix and Flip: Renovation and resale
    - Buy and Hold: Long-term rental income
    """
    
    def analyze_wholesale(
        self,
        conservative_arv: float,
        estimated_repairs: float,
        session_id: int
    ) -> WholesaleScenario:
        """
        Analyze wholesale investment scenario.
        
        Args:
            conservative_arv: Conservative ARV (25th percentile)
            estimated_repairs: Estimated repair costs
            session_id: Analysis session ID
            
        Returns:
            WholesaleScenario with MAO, contract price, and assignment fees
        """
        # MAO formula: Conservative ARV × 0.70 - Estimated Repairs
        mao = (conservative_arv * 0.70) - estimated_repairs
        
        # Contract price formula: MAO × 0.95
        contract_price = mao * 0.95
        
        # Assignment fee range: Contract Price × 0.05 to 0.10
        assignment_fee_low = contract_price * 0.05
        assignment_fee_high = contract_price * 0.10
        
        # Create summary
        summary = {
            'strategy': 'Wholesale',
            'conservative_arv': conservative_arv,
            'estimated_repairs': estimated_repairs,
            'mao': mao,
            'contract_price': contract_price,
            'assignment_fee_range': f'${assignment_fee_low:.0f} - ${assignment_fee_high:.0f}'
        }
        
        # Create scenario object
        scenario = WholesaleScenario(
            session_id=session_id,
            scenario_type=ScenarioType.WHOLESALE,
            purchase_price=contract_price,
            mao=mao,
            contract_price=contract_price,
            assignment_fee_low=assignment_fee_low,
            assignment_fee_high=assignment_fee_high,
            estimated_repairs=estimated_repairs,
            summary=summary
        )
        
        return scenario

    
    def analyze_fix_and_flip(
        self,
        acquisition_cost: float,
        renovation_cost: float,
        likely_arv: float,
        months_to_flip: int,
        session_id: int
    ) -> FixFlipScenario:
        """
        Analyze fix and flip investment scenario.
        
        Args:
            acquisition_cost: Purchase price
            renovation_cost: Renovation budget
            likely_arv: Likely ARV (median)
            months_to_flip: Expected months to complete and sell
            session_id: Analysis session ID
            
        Returns:
            FixFlipScenario with complete cost breakdown and profit analysis
        """
        # Calculate holding costs: (Acquisition + Renovation) × 0.02 × months
        holding_costs = (acquisition_cost + renovation_cost) * 0.02 * months_to_flip
        
        # Calculate financing costs: (Acquisition + Renovation) × 0.75 × 0.11 × (months / 12)
        financing_costs = (acquisition_cost + renovation_cost) * 0.75 * 0.11 * (months_to_flip / 12)
        
        # Calculate closing costs: Likely ARV × 0.08
        closing_costs = likely_arv * 0.08
        
        # Calculate total cost
        total_cost = acquisition_cost + renovation_cost + holding_costs + financing_costs + closing_costs
        
        # Exit value is the likely ARV
        exit_value = likely_arv
        
        # Calculate net profit
        net_profit = exit_value - total_cost
        
        # Calculate ROI: Net Profit / (Acquisition + Renovation) × 0.25
        roi = (net_profit / ((acquisition_cost + renovation_cost) * 0.25)) * 100
        
        # Create summary
        summary = {
            'strategy': 'Fix and Flip',
            'acquisition_cost': acquisition_cost,
            'renovation_cost': renovation_cost,
            'holding_costs': holding_costs,
            'financing_costs': financing_costs,
            'closing_costs': closing_costs,
            'total_cost': total_cost,
            'exit_value': exit_value,
            'net_profit': net_profit,
            'roi': roi,
            'months_to_flip': months_to_flip
        }
        
        # Create scenario object
        scenario = FixFlipScenario(
            session_id=session_id,
            scenario_type=ScenarioType.FIX_FLIP,
            purchase_price=acquisition_cost,
            acquisition_cost=acquisition_cost,
            renovation_cost=renovation_cost,
            holding_costs=holding_costs,
            financing_costs=financing_costs,
            closing_costs=closing_costs,
            total_cost=total_cost,
            exit_value=exit_value,
            net_profit=net_profit,
            roi=roi,
            months_to_flip=months_to_flip,
            summary=summary
        )
        
        return scenario

    
    def _calculate_monthly_payment(
        self,
        principal: float,
        annual_rate: float,
        months: int
    ) -> float:
        """
        Calculate monthly payment using PMT formula.
        
        Args:
            principal: Loan amount
            annual_rate: Annual interest rate (e.g., 0.065 for 6.5%)
            months: Loan term in months
            
        Returns:
            Monthly payment amount
        """
        if annual_rate == 0:
            return principal / months
        
        monthly_rate = annual_rate / 12
        payment = principal * (monthly_rate * (1 + monthly_rate) ** months) / \
                  ((1 + monthly_rate) ** months - 1)
        return payment
    
    def analyze_buy_and_hold(
        self,
        market_rent: float,
        annual_expenses: float,
        price_points: List[float],
        session_id: int,
        subject_property: Optional[PropertyFacts] = None
    ) -> BuyHoldScenario:
        """
        Analyze buy and hold investment scenario with dual capital structures.
        
        Args:
            market_rent: Monthly market rent
            annual_expenses: Annual property expenses (taxes, insurance, maintenance, vacancy)
            price_points: List of purchase prices to analyze (low, medium, high)
            session_id: Analysis session ID
            subject_property: Optional property facts for additional context
            
        Returns:
            BuyHoldScenario with dual capital structure analysis
        """
        # Define capital structures
        capital_structures = [
            {
                'name': '5% Down Owner-Occupied',
                'down_payment_percent': 0.05,
                'interest_rate': 0.065,
                'loan_term_months': 360
            },
            {
                'name': '25% Down Investor',
                'down_payment_percent': 0.25,
                'interest_rate': 0.075,
                'loan_term_months': 360
            }
        ]
        
        # Calculate monthly expenses
        monthly_expenses = annual_expenses / 12
        
        # Analyze each price point with both capital structures
        price_point_results = []
        
        for purchase_price in price_points:
            price_point_data = {
                'purchase_price': purchase_price,
                'capital_structure_results': []
            }
            
            for structure in capital_structures:
                # Calculate down payment and loan amount
                down_payment = purchase_price * structure['down_payment_percent']
                loan_amount = purchase_price - down_payment
                
                # Calculate monthly payment
                monthly_payment = self._calculate_monthly_payment(
                    loan_amount,
                    structure['interest_rate'],
                    structure['loan_term_months']
                )
                
                # Calculate monthly cash flow: Rent - Payment - Expenses
                monthly_cash_flow = market_rent - monthly_payment - monthly_expenses
                
                # Calculate cash-on-cash return: (Cash Flow × 12) / Down Payment
                if down_payment > 0:
                    cash_on_cash_return = ((monthly_cash_flow * 12) / down_payment) * 100
                else:
                    cash_on_cash_return = 0
                
                # Calculate cap rate: (Rent × 12 - Expenses × 12) / Purchase Price
                cap_rate = ((market_rent * 12 - monthly_expenses * 12) / purchase_price) * 100
                
                structure_result = {
                    'name': structure['name'],
                    'down_payment_percent': structure['down_payment_percent'] * 100,
                    'interest_rate': structure['interest_rate'] * 100,
                    'down_payment': down_payment,
                    'loan_amount': loan_amount,
                    'monthly_payment': monthly_payment,
                    'monthly_rent': market_rent,
                    'monthly_expenses': monthly_expenses,
                    'monthly_cash_flow': monthly_cash_flow,
                    'cash_on_cash_return': cash_on_cash_return,
                    'cap_rate': cap_rate
                }
                
                price_point_data['capital_structure_results'].append(structure_result)
            
            price_point_results.append(price_point_data)
        
        # Create summary
        summary = {
            'strategy': 'Buy and Hold',
            'market_rent': market_rent,
            'annual_expenses': annual_expenses,
            'monthly_expenses': monthly_expenses,
            'price_points_analyzed': len(price_points),
            'capital_structures': len(capital_structures)
        }
        
        # Use the middle price point as the purchase_price for the base scenario
        purchase_price = price_points[len(price_points) // 2] if price_points else 0
        
        # Create scenario object
        scenario = BuyHoldScenario(
            session_id=session_id,
            scenario_type=ScenarioType.BUY_HOLD,
            purchase_price=purchase_price,
            market_rent=market_rent,
            capital_structures=capital_structures,
            price_points=price_point_results,
            summary=summary
        )
        
        return scenario

    
    def compare_scenarios(
        self,
        scenarios: List[Dict],
        price_points: List[float]
    ) -> Dict:
        """
        Compare multiple investment scenarios across price points.
        
        Args:
            scenarios: List of scenario dictionaries with type and data
            price_points: List of price points to compare (low, medium, high)
            
        Returns:
            Dictionary with comparison table and highest ROI highlights
        """
        comparison_results = []
        
        for price_point in price_points:
            price_point_comparison = {
                'price_point': price_point,
                'scenarios': [],
                'highest_roi': None,
                'highest_roi_value': float('-inf')
            }
            
            for scenario in scenarios:
                scenario_type = scenario.get('type')
                scenario_data = scenario.get('data')
                
                if scenario_type == 'wholesale':
                    # Wholesale ROI: Assignment fee / Contract price
                    assignment_fee_avg = (
                        scenario_data.get('assignment_fee_low', 0) + 
                        scenario_data.get('assignment_fee_high', 0)
                    ) / 2
                    contract_price = scenario_data.get('contract_price', 1)
                    roi = (assignment_fee_avg / contract_price) * 100 if contract_price > 0 else 0
                    
                    scenario_result = {
                        'type': 'Wholesale',
                        'roi': roi,
                        'key_metric': f'Assignment Fee: ${assignment_fee_avg:.0f}',
                        'details': {
                            'mao': scenario_data.get('mao'),
                            'contract_price': contract_price,
                            'assignment_fee_range': f"${scenario_data.get('assignment_fee_low', 0):.0f} - ${scenario_data.get('assignment_fee_high', 0):.0f}"
                        }
                    }
                
                elif scenario_type == 'fix_flip':
                    # Fix and Flip ROI from scenario data
                    roi = scenario_data.get('roi', 0)
                    net_profit = scenario_data.get('net_profit', 0)
                    
                    scenario_result = {
                        'type': 'Fix and Flip',
                        'roi': roi,
                        'key_metric': f'Net Profit: ${net_profit:.0f}',
                        'details': {
                            'acquisition_cost': scenario_data.get('acquisition_cost'),
                            'renovation_cost': scenario_data.get('renovation_cost'),
                            'total_cost': scenario_data.get('total_cost'),
                            'exit_value': scenario_data.get('exit_value'),
                            'net_profit': net_profit
                        }
                    }
                
                elif scenario_type == 'buy_hold':
                    # Buy and Hold: Use best cash-on-cash return from capital structures
                    price_point_data = None
                    for pp_data in scenario_data.get('price_points', []):
                        if abs(pp_data.get('purchase_price', 0) - price_point) < 0.01:
                            price_point_data = pp_data
                            break
                    
                    if price_point_data:
                        best_coc = float('-inf')
                        best_structure = None
                        
                        for structure in price_point_data.get('capital_structure_results', []):
                            coc = structure.get('cash_on_cash_return', float('-inf'))
                            if coc > best_coc:
                                best_coc = coc
                                best_structure = structure
                        
                        roi = best_coc
                        monthly_cash_flow = best_structure.get('monthly_cash_flow', 0) if best_structure else 0
                        
                        scenario_result = {
                            'type': 'Buy and Hold',
                            'roi': roi,
                            'key_metric': f'Cash Flow: ${monthly_cash_flow:.0f}/mo',
                            'details': {
                                'market_rent': scenario_data.get('market_rent'),
                                'best_structure': best_structure.get('name') if best_structure else None,
                                'cash_on_cash_return': roi,
                                'cap_rate': best_structure.get('cap_rate') if best_structure else None
                            }
                        }
                    else:
                        continue
                else:
                    continue
                
                price_point_comparison['scenarios'].append(scenario_result)
                
                # Track highest ROI
                if roi > price_point_comparison['highest_roi_value']:
                    price_point_comparison['highest_roi_value'] = roi
                    price_point_comparison['highest_roi'] = scenario_result['type']
            
            comparison_results.append(price_point_comparison)
        
        return {
            'price_points': comparison_results,
            'summary': {
                'total_scenarios': len(scenarios),
                'price_points_analyzed': len(price_points)
            }
        }
