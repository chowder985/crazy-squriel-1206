export interface MrrDataPoint {
  month: string; // ISO 8601 date string (YYYY-MM-DD)
  mrr_amount: number; // USD amount
}

export type LoadingState = 'loading' | 'error' | 'empty' | 'success';
