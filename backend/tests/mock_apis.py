"""Mock external API responses for testing."""
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from unittest.mock import Mock
import random


class MockMLSAPI:
    """Mock MLS API for property and sales data."""
    
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
    
    def get_property_details(self, address: str) -> Dict[str, Any]:
        """Mock property details retrieval."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("MLS API unavailable")
        
        return {
            'address': address,
            'property_type': 'multi_family',
            'units': 4,
            'bedrooms': 8,
            'bathrooms': 4.0,
            'square_footage': 3200,
            'lot_size': 5000,
            'year_built': 1920,
            'construction_type': 'brick',
            'basement': True,
            'parking_spaces': 2,
            'last_sale_price': 450000.0,
            'last_sale_date': '2022-06-15',
            'zoning': 'R-4'
        }
    
    def search_comparable_sales(
        self, 
        latitude: float, 
        longitude: float, 
        radius_miles: float,
        property_type: str,
        max_age_months: int = 12
    ) -> List[Dict[str, Any]]:
        """Mock comparable sales search."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("MLS API unavailable")
        
        # Generate mock comparables based on radius
        num_comps = int(radius_miles * 15)  # More comps at larger radius
        comparables = []
        
        base_date = datetime.now().date()
        
        for i in range(num_comps):
            comp = {
                'address': f"{1000 + i * 10} Test St, Chicago, IL 60601",
                'sale_date': (base_date - timedelta(days=random.randint(1, 365))).isoformat(),
                'sale_price': 440000 + random.randint(-50000, 50000),
                'property_type': property_type,
                'units': 4,
                'bedrooms': 8,
                'bathrooms': 4.0,
                'square_footage': 3200 + random.randint(-200, 200),
                'lot_size': 5000 + random.randint(-500, 500),
                'year_built': 1920 + random.randint(-10, 10),
                'construction_type': 'brick',
                'interior_condition': 'average',
                'latitude': latitude + (random.random() - 0.5) * radius_miles * 0.01,
                'longitude': longitude + (random.random() - 0.5) * radius_miles * 0.01
            }
            comparables.append(comp)
        
        return comparables


class MockTaxAssessorAPI:
    """Mock tax assessor API for property characteristics."""
    
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
    
    def get_property_info(self, address: str) -> Dict[str, Any]:
        """Mock property info retrieval."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("Tax Assessor API unavailable")
        
        return {
            'address': address,
            'assessed_value': 420000.0,
            'annual_taxes': 8400.0,
            'square_footage': 3200,
            'lot_size': 5000,
            'year_built': 1920,
            'zoning': 'R-4'
        }


class MockChicagoCityDataAPI:
    """Mock Chicago city data portal API."""
    
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
    
    def get_building_data(self, address: str) -> Dict[str, Any]:
        """Mock building data retrieval."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("Chicago City Data API unavailable")
        
        return {
            'address': address,
            'square_footage': 3200,
            'year_built': 1920,
            'building_permits': []
        }


class MockMunicipalDataAPI:
    """Mock municipal data API for permits and zoning."""
    
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
    
    def get_zoning_info(self, address: str) -> Dict[str, Any]:
        """Mock zoning info retrieval."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("Municipal Data API unavailable")
        
        return {
            'address': address,
            'zoning': 'R-4',
            'permits': []
        }


class MockGoogleMapsAPI:
    """Mock Google Maps API for geocoding."""
    
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
    
    def geocode(self, address: str) -> Dict[str, Any]:
        """Mock geocoding."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("Google Maps API unavailable")
        
        # Return Chicago coordinates with slight variation
        return {
            'latitude': 41.8781 + random.random() * 0.01,
            'longitude': -87.6298 + random.random() * 0.01,
            'formatted_address': address
        }


class MockRentalDataAPI:
    """Mock rental data API for market rent information."""
    
    def __init__(self):
        self.call_count = 0
        self.should_fail = False
    
    def get_market_rent(
        self, 
        latitude: float, 
        longitude: float, 
        bedrooms: int,
        property_type: str
    ) -> Dict[str, Any]:
        """Mock market rent retrieval."""
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("Rental Data API unavailable")
        
        # Calculate mock rent based on bedrooms
        base_rent = 1200
        rent_per_bedroom = 400
        
        return {
            'market_rent': base_rent + (bedrooms * rent_per_bedroom),
            'sample_size': 15,
            'confidence': 'high'
        }


class MockAPIFactory:
    """Factory for creating mock API instances."""
    
    @staticmethod
    def create_all_mocks() -> Dict[str, Any]:
        """Create all mock API instances."""
        return {
            'mls': MockMLSAPI(),
            'tax_assessor': MockTaxAssessorAPI(),
            'chicago_data': MockChicagoCityDataAPI(),
            'municipal': MockMunicipalDataAPI(),
            'google_maps': MockGoogleMapsAPI(),
            'rental_data': MockRentalDataAPI()
        }
    
    @staticmethod
    def configure_failure_scenario(
        mocks: Dict[str, Any], 
        failing_apis: List[str]
    ):
        """Configure specific APIs to fail for testing fallback logic."""
        for api_name in failing_apis:
            if api_name in mocks:
                mocks[api_name].should_fail = True
    
    @staticmethod
    def reset_all_mocks(mocks: Dict[str, Any]):
        """Reset all mock API states."""
        for mock in mocks.values():
            mock.call_count = 0
            mock.should_fail = False
