/**
 * Mock API responses for frontend testing
 */

export interface MockPropertyFacts {
  address: string;
  property_type: string;
  units: number;
  bedrooms: number;
  bathrooms: number;
  square_footage: number;
  lot_size: number;
  year_built: number;
  construction_type: string;
  basement: boolean;
  parking_spaces: number;
  last_sale_price: number;
  last_sale_date: string;
  assessed_value: number;
  annual_taxes: number;
  zoning: string;
  interior_condition: string;
  latitude: number;
  longitude: number;
}

export interface MockComparableSale {
  id: string;
  address: string;
  sale_date: string;
  sale_price: number;
  property_type: string;
  units: number;
  bedrooms: number;
  bathrooms: number;
  square_footage: number;
  lot_size: number;
  year_built: number;
  construction_type: string;
  interior_condition: string;
  distance_miles: number;
}

export interface MockAnalysisSession {
  session_id: string;
  user_id: string;
  current_step: number;
  subject_property: MockPropertyFacts | null;
  comparables: MockComparableSale[];
  ranked_comparables: any[];
  valuation_result: any | null;
  scenarios: any[];
}

export const mockPropertyFacts: MockPropertyFacts = {
  address: "123 Main St, Chicago, IL 60601",
  property_type: "multi_family",
  units: 4,
  bedrooms: 8,
  bathrooms: 4.0,
  square_footage: 3200,
  lot_size: 5000,
  year_built: 1920,
  construction_type: "brick",
  basement: true,
  parking_spaces: 2,
  last_sale_price: 450000.0,
  last_sale_date: "2022-06-15",
  assessed_value: 420000.0,
  annual_taxes: 8400.0,
  zoning: "R-4",
  interior_condition: "average",
  latitude: 41.8781,
  longitude: -87.6298,
};

export const mockComparables: MockComparableSale[] = Array.from({ length: 12 }, (_, i) => ({
  id: `comp-${i + 1}`,
  address: `${100 + i * 10} Oak St, Chicago, IL 6060${i % 10}`,
  sale_date: new Date(Date.now() - (30 + i * 30) * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
  sale_price: 440000 + i * 5000,
  property_type: "multi_family",
  units: 4,
  bedrooms: 8,
  bathrooms: 4.0,
  square_footage: 3100 + i * 50,
  lot_size: 4800 + i * 100,
  year_built: 1915 + i,
  construction_type: "brick",
  interior_condition: "average",
  distance_miles: 0.2 + i * 0.05,
}));

export const mockAnalysisSession: MockAnalysisSession = {
  session_id: "test-session-001",
  user_id: "test-user-001",
  current_step: 1,
  subject_property: mockPropertyFacts,
  comparables: mockComparables,
  ranked_comparables: [],
  valuation_result: null,
  scenarios: [],
};

export const mockValuationResult = {
  comparable_valuations: mockComparables.slice(0, 5).map((comp, i) => ({
    comparable: comp,
    price_per_sqft: comp.sale_price / comp.square_footage,
    price_per_unit: comp.sale_price / comp.units,
    price_per_bedroom: comp.sale_price / comp.bedrooms,
    adjusted_value: comp.sale_price + (i * 5000),
    adjustments: [],
    narrative: `Comparable ${i + 1} adjusted for differences in property characteristics.`,
  })),
  arv_range: {
    conservative: 430000,
    likely: 460000,
    aggressive: 490000,
  },
  key_drivers: [
    "Strong comparable sales in the area",
    "Recent renovations increase value",
    "Location in desirable neighborhood",
  ],
};

export const mockWholesaleScenario = {
  scenario_type: "wholesale",
  purchase_price: 320000,
  mao: 322000,
  contract_price: 305900,
  assignment_fee_low: 15295,
  assignment_fee_high: 30590,
  estimated_repairs: 50000,
};

export const mockFixFlipScenario = {
  scenario_type: "fix_flip",
  purchase_price: 320000,
  acquisition_cost: 320000,
  renovation_cost: 50000,
  holding_costs: 7400,
  financing_costs: 15263,
  closing_costs: 36800,
  total_cost: 429463,
  exit_value: 460000,
  net_profit: 30537,
  roi: 8.24,
  months_to_flip: 6,
};

export const mockBuyHoldScenario = {
  scenario_type: "buy_hold",
  purchase_price: 320000,
  market_rent: 3200,
  capital_structures: [
    {
      name: "5% Down Owner-Occupied",
      down_payment_percent: 0.05,
      interest_rate: 0.065,
      loan_term_months: 360,
    },
    {
      name: "25% Down Investor",
      down_payment_percent: 0.25,
      interest_rate: 0.075,
      loan_term_months: 360,
    },
  ],
  price_points: [
    {
      purchase_price: 300000,
      down_payment: 15000,
      loan_amount: 285000,
      monthly_payment: 1801,
      monthly_rent: 3200,
      monthly_expenses: 700,
      monthly_cash_flow: 699,
      cash_on_cash_return: 0.559,
      cap_rate: 0.10,
    },
  ],
};

/**
 * Mock API client for testing
 */
export class MockApiClient {
  private delay: number;

  constructor(delay: number = 100) {
    this.delay = delay;
  }

  private async simulateDelay<T>(data: T): Promise<T> {
    return new Promise((resolve) => {
      setTimeout(() => resolve(data), this.delay);
    });
  }

  async startAnalysis(address: string): Promise<MockAnalysisSession> {
    return this.simulateDelay({
      ...mockAnalysisSession,
      subject_property: { ...mockPropertyFacts, address },
    });
  }

  async getSession(sessionId: string): Promise<MockAnalysisSession> {
    return this.simulateDelay(mockAnalysisSession);
  }

  async advanceStep(sessionId: string, step: number): Promise<any> {
    return this.simulateDelay({ success: true, current_step: step });
  }

  async updateStepData(sessionId: string, step: number, data: any): Promise<any> {
    return this.simulateDelay({ success: true, data });
  }

  async goBackToStep(sessionId: string, step: number): Promise<any> {
    return this.simulateDelay({ success: true, current_step: step });
  }

  async getReport(sessionId: string): Promise<any> {
    return this.simulateDelay({
      sections: {
        a: mockPropertyFacts,
        b: mockComparables,
        c: [],
        d: mockValuationResult,
        e: mockValuationResult.arv_range,
        f: mockValuationResult.key_drivers,
      },
    });
  }

  async exportToExcel(sessionId: string): Promise<Blob> {
    return this.simulateDelay(new Blob(['mock excel data'], { type: 'application/vnd.ms-excel' }));
  }

  async exportToGoogleSheets(sessionId: string): Promise<{ url: string }> {
    return this.simulateDelay({ url: 'https://docs.google.com/spreadsheets/d/mock-sheet-id' });
  }
}

export const mockApiClient = new MockApiClient();
