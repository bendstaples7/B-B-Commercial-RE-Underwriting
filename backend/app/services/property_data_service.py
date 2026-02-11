"""Property Data Service with multi-source integration and fallback logic."""
import os
import redis
import json
import requests
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition


class PropertyDataService:
    """Service for retrieving property data from multiple sources with fallback logic."""
    
    def __init__(self):
        """Initialize the service with API keys and Redis connection."""
        self.mls_api_key = os.getenv('MLS_API_KEY')
        self.tax_assessor_api_key = os.getenv('TAX_ASSESSOR_API_KEY')
        self.google_maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        self.chicago_data_api_key = os.getenv('CHICAGO_DATA_API_KEY')
        
        # Initialize Redis for caching
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Cache TTL settings
        self.property_cache_ttl = 86400  # 24 hours
        self.geocoding_cache_ttl = None  # Permanent (no expiry)
    
    def fetch_property_facts(self, address: str) -> Dict[str, Any]:
        """
        Fetch comprehensive property facts with fallback logic.
        
        Args:
            address: Property address to look up
            
        Returns:
            Dictionary containing property facts with data source tracking
        """
        # Check cache first
        cache_key = f"property_facts:{address}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
        
        # Initialize result dictionary
        property_data = {
            'address': address,
            'data_source': 'composite',
            'user_modified_fields': []
        }
        
        # Geocode the address first (needed for distance calculations)
        coordinates = self.geocode_address(address)
        if coordinates:
            property_data['latitude'] = coordinates['lat']
            property_data['longitude'] = coordinates['lng']
        
        # Try MLS API first (primary source)
        mls_data = self._fetch_from_mls(address)
        if mls_data:
            property_data.update(mls_data)
        
        # Apply fallback logic for missing fields
        property_data = self._apply_fallback_logic(address, property_data)
        
        # Cache the result
        self._set_in_cache(cache_key, property_data, self.property_cache_ttl)
        
        return property_data
    
    def fetch_with_fallback(self, address: str, field: str) -> Optional[Any]:
        """
        Fetch a specific field with fallback sequence.
        
        Args:
            address: Property address
            field: Field name to retrieve
            
        Returns:
            Field value or None if not found
        """
        # Try each source in priority order
        sources = [
            self._fetch_from_mls,
            self._fetch_from_chicago_data,
            self._fetch_from_tax_assessor,
            self._fetch_from_municipal
        ]
        
        for source_func in sources:
            try:
                data = source_func(address)
                if data and field in data and data[field] is not None:
                    return data[field]
            except Exception as e:
                # Log error and continue to next source
                print(f"Error fetching {field} from {source_func.__name__}: {e}")
                continue
        
        return None
    
    def geocode_address(self, address: str) -> Optional[Dict[str, float]]:
        """
        Geocode an address using Google Maps API with permanent caching.
        
        Args:
            address: Address to geocode
            
        Returns:
            Dictionary with 'lat' and 'lng' keys, or None if geocoding fails
        """
        # Check cache first (permanent cache for geocoding)
        cache_key = f"geocode:{address}"
        cached_coords = self._get_from_cache(cache_key)
        if cached_coords:
            return cached_coords
        
        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'address': address,
                'key': self.google_maps_api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'OK' and data['results']:
                location = data['results'][0]['geometry']['location']
                coordinates = {
                    'lat': location['lat'],
                    'lng': location['lng']
                }
                
                # Cache permanently (no TTL)
                self._set_in_cache(cache_key, coordinates, self.geocoding_cache_ttl)
                
                return coordinates
        except Exception as e:
            print(f"Geocoding error for {address}: {e}")
        
        return None
    
    def validate_property_data(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate property data and identify missing required fields.
        
        Args:
            property_data: Property data dictionary
            
        Returns:
            Dictionary with 'valid' boolean and 'missing_fields' list
        """
        required_fields = [
            'property_type', 'units', 'bedrooms', 'bathrooms', 'square_footage',
            'lot_size', 'year_built', 'construction_type', 'assessed_value',
            'annual_taxes', 'zoning'
        ]
        
        missing_fields = [
            field for field in required_fields 
            if field not in property_data or property_data[field] is None
        ]
        
        return {
            'valid': len(missing_fields) == 0,
            'missing_fields': missing_fields
        }
    
    # Private methods for data source adapters
    
    def _fetch_from_mls(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Fetch property data from MLS API.
        
        Args:
            address: Property address
            
        Returns:
            Dictionary of property data or None
        """
        if not self.mls_api_key:
            return None
        
        try:
            # Mock MLS API endpoint (replace with actual MLS API)
            url = "https://api.mls-provider.com/v1/property"
            headers = {'Authorization': f'Bearer {self.mls_api_key}'}
            params = {'address': address}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform MLS response to our format
            return self._transform_mls_data(data)
        except Exception as e:
            print(f"MLS API error: {e}")
            return None
    
    def _fetch_from_tax_assessor(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Fetch property data from county tax assessor API.
        
        Args:
            address: Property address
            
        Returns:
            Dictionary of property data or None
        """
        if not self.tax_assessor_api_key:
            return None
        
        try:
            # Mock tax assessor API endpoint
            url = "https://api.county-assessor.gov/property"
            headers = {'X-API-Key': self.tax_assessor_api_key}
            params = {'address': address}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform assessor response to our format
            return self._transform_assessor_data(data)
        except Exception as e:
            print(f"Tax assessor API error: {e}")
            return None
    
    def _fetch_from_chicago_data(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Fetch property data from Chicago city data portal (square footage fallback).
        
        Args:
            address: Property address
            
        Returns:
            Dictionary of property data or None
        """
        if not self.chicago_data_api_key:
            return None
        
        try:
            # Chicago Data Portal API for building footprints
            url = "https://data.cityofchicago.org/resource/building-footprints.json"
            params = {
                'address': address,
                '$$app_token': self.chicago_data_api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform Chicago data response
            return self._transform_chicago_data(data)
        except Exception as e:
            print(f"Chicago data API error: {e}")
            return None
    
    def _fetch_from_municipal(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Fetch property data from municipal databases (building permits, zoning).
        
        Args:
            address: Property address
            
        Returns:
            Dictionary of property data or None
        """
        try:
            # Mock municipal API endpoint
            url = "https://api.municipal-data.gov/property"
            params = {'address': address}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Transform municipal response
            return self._transform_municipal_data(data)
        except Exception as e:
            print(f"Municipal API error: {e}")
            return None
    
    def _apply_fallback_logic(self, address: str, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply fallback sequence for missing fields.
        
        Fallback order: primary → Chicago → tax assessor → municipal → manual
        
        Args:
            address: Property address
            property_data: Current property data
            
        Returns:
            Updated property data with fallback values
        """
        # Define critical fields that need fallback
        fallback_fields = {
            'square_footage': ['_fetch_from_chicago_data', '_fetch_from_tax_assessor', '_fetch_from_municipal'],
            'lot_size': ['_fetch_from_tax_assessor', '_fetch_from_municipal'],
            'year_built': ['_fetch_from_tax_assessor', '_fetch_from_municipal'],
            'zoning': ['_fetch_from_municipal', '_fetch_from_tax_assessor'],
            'assessed_value': ['_fetch_from_tax_assessor'],
            'annual_taxes': ['_fetch_from_tax_assessor']
        }
        
        for field, source_methods in fallback_fields.items():
            if field not in property_data or property_data[field] is None:
                # Try each fallback source
                for method_name in source_methods:
                    method = getattr(self, method_name)
                    try:
                        data = method(address)
                        if data and field in data and data[field] is not None:
                            property_data[field] = data[field]
                            property_data['data_source'] = f"composite:{method_name}"
                            break
                    except Exception as e:
                        print(f"Fallback error for {field} from {method_name}: {e}")
                        continue
        
        return property_data
    
    # Data transformation methods
    
    def _transform_mls_data(self, mls_response: Dict[str, Any]) -> Dict[str, Any]:
        """Transform MLS API response to internal format."""
        # Mock transformation - adjust based on actual MLS API structure
        return {
            'property_type': self._map_property_type(mls_response.get('propertyType')),
            'units': mls_response.get('units', 1),
            'bedrooms': mls_response.get('bedrooms', 0),
            'bathrooms': mls_response.get('bathrooms', 0),
            'square_footage': mls_response.get('squareFeet'),
            'lot_size': mls_response.get('lotSize'),
            'year_built': mls_response.get('yearBuilt'),
            'construction_type': self._map_construction_type(mls_response.get('construction')),
            'basement': mls_response.get('hasBasement', False),
            'parking_spaces': mls_response.get('parkingSpaces', 0),
            'last_sale_price': mls_response.get('lastSalePrice'),
            'last_sale_date': mls_response.get('lastSaleDate'),
            'assessed_value': mls_response.get('assessedValue'),
            'annual_taxes': mls_response.get('annualTaxes'),
            'zoning': mls_response.get('zoning', 'Unknown')
        }
    
    def _transform_assessor_data(self, assessor_response: Dict[str, Any]) -> Dict[str, Any]:
        """Transform tax assessor API response to internal format."""
        return {
            'assessed_value': assessor_response.get('assessed_value'),
            'annual_taxes': assessor_response.get('annual_taxes'),
            'square_footage': assessor_response.get('building_sqft'),
            'lot_size': assessor_response.get('lot_sqft'),
            'year_built': assessor_response.get('year_built'),
            'property_type': self._map_property_type(assessor_response.get('property_class')),
            'construction_type': self._map_construction_type(assessor_response.get('construction_type'))
        }
    
    def _transform_chicago_data(self, chicago_response: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Transform Chicago data portal response to internal format."""
        if not chicago_response:
            return {}
        
        # Take first matching result
        data = chicago_response[0]
        return {
            'square_footage': data.get('sq_ft'),
            'year_built': data.get('year_built')
        }
    
    def _transform_municipal_data(self, municipal_response: Dict[str, Any]) -> Dict[str, Any]:
        """Transform municipal API response to internal format."""
        return {
            'zoning': municipal_response.get('zoning_classification'),
            'year_built': municipal_response.get('year_constructed'),
            'lot_size': municipal_response.get('parcel_size_sqft')
        }
    
    # Mapping helper methods
    
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
            return None
        
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
        
        return construction_mapping.get(external_construction.lower())
    
    # Cache helper methods
    
    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve data from Redis cache."""
        try:
            cached = self.redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"Cache retrieval error: {e}")
        return None
    
    def _set_in_cache(self, key: str, data: Dict[str, Any], ttl: Optional[int] = None):
        """Store data in Redis cache with optional TTL."""
        try:
            serialized = json.dumps(data, default=str)
            if ttl:
                self.redis_client.setex(key, ttl, serialized)
            else:
                self.redis_client.set(key, serialized)
        except Exception as e:
            print(f"Cache storage error: {e}")
    
    def invalidate_cache(self, address: str):
        """Invalidate cached property data for an address."""
        cache_key = f"property_facts:{address}"
        try:
            self.redis_client.delete(cache_key)
        except Exception as e:
            print(f"Cache invalidation error: {e}")
