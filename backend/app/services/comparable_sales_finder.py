"""Comparable Sales Finder with radius expansion and filtering."""
import os
import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
from app.models.property_facts import PropertyFacts, PropertyType
from app.models.comparable_sale import ComparableSale


class ComparableSalesFinder:
    """Service for finding comparable sales with radius expansion algorithm."""
    
    # Search radius sequence in miles
    RADIUS_SEQUENCE = [0.25, 0.5, 0.75, 1.0]
    MIN_COMPARABLES = 10
    MAX_AGE_MONTHS = 12
    
    def __init__(self):
        """Initialize the service with API keys."""
        self.mls_api_key = os.getenv('MLS_API_KEY')
        self.tax_assessor_api_key = os.getenv('TAX_ASSESSOR_API_KEY')
    
    def find_comparables(
        self,
        subject: PropertyFacts,
        min_count: int = MIN_COMPARABLES,
        max_age_months: int = MAX_AGE_MONTHS
    ) -> List[Dict[str, Any]]:
        """
        Find comparable sales using radius expansion algorithm.
        
        Algorithm:
        1. Start with 0.25 mile radius
        2. Query sales within radius with filters:
           - Sale date within max_age_months
           - Property type matches subject
           - Valid sale (not foreclosure/family transfer)
        3. If count < min_count, expand radius: 0.25 → 0.5 → 0.75 → 1.0 miles
        4. Return first min_count+ results or all if < min_count at max radius
        
        Args:
            subject: Subject property facts
            min_count: Minimum number of comparables required (default: 10)
            max_age_months: Maximum age of sales in months (default: 12)
            
        Returns:
            List of comparable sale dictionaries
        """
        if not subject.latitude or not subject.longitude:
            raise ValueError("Subject property must have geocoded coordinates")
        
        # Calculate cutoff date for sale filtering
        cutoff_date = datetime.now() - timedelta(days=max_age_months * 30)
        
        comparables = []
        
        # Try each radius in sequence
        for radius in self.RADIUS_SEQUENCE:
            # Fetch sales within current radius
            sales = self._fetch_sales_in_radius(
                center=(subject.latitude, subject.longitude),
                radius_miles=radius,
                cutoff_date=cutoff_date
            )
            
            # Filter by property type
            filtered_sales = self.filter_by_property_type(sales, subject.property_type)
            
            # Filter by sale date
            filtered_sales = self._filter_by_sale_date(filtered_sales, cutoff_date)
            
            # Calculate distances and add to results
            for sale in filtered_sales:
                if sale.get('latitude') and sale.get('longitude'):
                    distance = self._calculate_distance(
                        (subject.latitude, subject.longitude),
                        (sale['latitude'], sale['longitude'])
                    )
                    sale['distance_miles'] = distance
                    comparables.append(sale)
            
            # Check if we have enough comparables
            if len(comparables) >= min_count:
                # Return exactly min_count comparables (or more if tied on distance)
                comparables.sort(key=lambda x: x['distance_miles'])
                return comparables[:min_count]
        
        # If we've exhausted all radii, return what we have
        comparables.sort(key=lambda x: x['distance_miles'])
        return comparables
    
    def expand_search_radius(self, current_radius: float) -> Optional[float]:
        """
        Get the next radius in the expansion sequence.
        
        Args:
            current_radius: Current search radius in miles
            
        Returns:
            Next radius in sequence, or None if at maximum
        """
        try:
            current_index = self.RADIUS_SEQUENCE.index(current_radius)
            if current_index < len(self.RADIUS_SEQUENCE) - 1:
                return self.RADIUS_SEQUENCE[current_index + 1]
        except ValueError:
            # Current radius not in sequence, return first radius larger than current
            for radius in self.RADIUS_SEQUENCE:
                if radius > current_radius:
                    return radius
        
        return None
    
    def filter_by_property_type(
        self,
        sales: List[Dict[str, Any]],
        property_type: PropertyType
    ) -> List[Dict[str, Any]]:
        """
        Filter sales by property type to ensure residential matches residential
        and commercial matches commercial.
        
        Args:
            sales: List of sale dictionaries
            property_type: Subject property type to match
            
        Returns:
            Filtered list of sales matching property type
        """
        return [
            sale for sale in sales
            if sale.get('property_type') == property_type.value
        ]
    
    def _fetch_sales_in_radius(
        self,
        center: Tuple[float, float],
        radius_miles: float,
        cutoff_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Fetch sales data from MLS API within specified radius.
        
        Args:
            center: Tuple of (latitude, longitude) for center point
            radius_miles: Search radius in miles
            cutoff_date: Minimum sale date to include
            
        Returns:
            List of sale dictionaries from API
        """
        if not self.mls_api_key:
            # Return empty list if no API key configured
            return []
        
        try:
            # Mock MLS API endpoint for comparable sales search
            url = "https://api.mls-provider.com/v1/sales/search"
            headers = {'Authorization': f'Bearer {self.mls_api_key}'}
            params = {
                'latitude': center[0],
                'longitude': center[1],
                'radius_miles': radius_miles,
                'min_sale_date': cutoff_date.strftime('%Y-%m-%d'),
                'exclude_foreclosures': True,
                'exclude_family_transfers': True
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform API response to internal format
            return [self._transform_sale_data(sale) for sale in data.get('sales', [])]
            
        except Exception as e:
            print(f"MLS sales search error: {e}")
            return []
    
    def _filter_by_sale_date(
        self,
        sales: List[Dict[str, Any]],
        cutoff_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Filter sales by date to include only recent sales.
        
        Args:
            sales: List of sale dictionaries
            cutoff_date: Minimum sale date to include
            
        Returns:
            Filtered list of sales within date range
        """
        filtered = []
        for sale in sales:
            sale_date = sale.get('sale_date')
            if sale_date:
                # Handle both datetime and string date formats
                if isinstance(sale_date, str):
                    try:
                        sale_date = datetime.strptime(sale_date, '%Y-%m-%d')
                    except ValueError:
                        continue
                
                if sale_date >= cutoff_date:
                    filtered.append(sale)
        
        return filtered
    
    def _calculate_distance(
        self,
        point1: Tuple[float, float],
        point2: Tuple[float, float]
    ) -> float:
        """
        Calculate distance between two geographic points using Haversine formula.
        
        Args:
            point1: Tuple of (latitude, longitude) for first point
            point2: Tuple of (latitude, longitude) for second point
            
        Returns:
            Distance in miles
        """
        lat1, lon1 = point1
        lat2, lon2 = point2
        
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        # Earth radius in miles
        earth_radius_miles = 3959
        
        return c * earth_radius_miles
    
    def _transform_sale_data(self, sale_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform MLS API sale response to internal format.
        
        Args:
            sale_response: Raw sale data from MLS API
            
        Returns:
            Transformed sale dictionary
        """
        return {
            'address': sale_response.get('address'),
            'sale_date': sale_response.get('saleDate'),
            'sale_price': sale_response.get('salePrice'),
            'property_type': self._map_property_type(sale_response.get('propertyType')),
            'units': sale_response.get('units', 1),
            'bedrooms': sale_response.get('bedrooms', 0),
            'bathrooms': sale_response.get('bathrooms', 0),
            'square_footage': sale_response.get('squareFeet'),
            'lot_size': sale_response.get('lotSize'),
            'year_built': sale_response.get('yearBuilt'),
            'construction_type': self._map_construction_type(sale_response.get('construction')),
            'interior_condition': self._map_interior_condition(sale_response.get('condition')),
            'latitude': sale_response.get('latitude'),
            'longitude': sale_response.get('longitude'),
            'similarity_notes': ''
        }
    
    def _map_property_type(self, external_type: Optional[str]) -> Optional[str]:
        """Map external property type to internal enum value."""
        if not external_type:
            return None
        
        type_mapping = {
            'single family': PropertyType.SINGLE_FAMILY.value,
            'single-family': PropertyType.SINGLE_FAMILY.value,
            'sfr': PropertyType.SINGLE_FAMILY.value,
            'multi family': PropertyType.MULTI_FAMILY.value,
            'multi-family': PropertyType.MULTI_FAMILY.value,
            'multifamily': PropertyType.MULTI_FAMILY.value,
            'commercial': PropertyType.COMMERCIAL.value,
            'retail': PropertyType.COMMERCIAL.value,
            'office': PropertyType.COMMERCIAL.value
        }
        
        return type_mapping.get(external_type.lower())
    
    def _map_construction_type(self, external_construction: Optional[str]) -> Optional[str]:
        """Map external construction type to internal enum value."""
        if not external_construction:
            return 'frame'  # Default
        
        from app.models.property_facts import ConstructionType
        
        construction_mapping = {
            'frame': ConstructionType.FRAME.value,
            'wood': ConstructionType.FRAME.value,
            'wood frame': ConstructionType.FRAME.value,
            'brick': ConstructionType.BRICK.value,
            'brick veneer': ConstructionType.BRICK.value,
            'masonry': ConstructionType.MASONRY.value,
            'concrete': ConstructionType.MASONRY.value,
            'stone': ConstructionType.MASONRY.value
        }
        
        return construction_mapping.get(external_construction.lower(), ConstructionType.FRAME.value)
    
    def _map_interior_condition(self, external_condition: Optional[str]) -> Optional[str]:
        """Map external interior condition to internal enum value."""
        if not external_condition:
            return 'average'  # Default
        
        from app.models.property_facts import InteriorCondition
        
        condition_mapping = {
            'needs gut': InteriorCondition.NEEDS_GUT.value,
            'needs_gut': InteriorCondition.NEEDS_GUT.value,
            'poor': InteriorCondition.POOR.value,
            'fair': InteriorCondition.POOR.value,
            'average': InteriorCondition.AVERAGE.value,
            'good': InteriorCondition.AVERAGE.value,
            'new renovation': InteriorCondition.NEW_RENO.value,
            'new_reno': InteriorCondition.NEW_RENO.value,
            'renovated': InteriorCondition.NEW_RENO.value,
            'high end': InteriorCondition.HIGH_END.value,
            'high_end': InteriorCondition.HIGH_END.value,
            'luxury': InteriorCondition.HIGH_END.value
        }
        
        return condition_mapping.get(external_condition.lower(), InteriorCondition.AVERAGE.value)
