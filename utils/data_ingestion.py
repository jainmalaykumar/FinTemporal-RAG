import yfinance as yf
from gnews import GNews
from bs4 import BeautifulSoup
from datetime import datetime
import logging
import pandas as pd
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FinancialDataFetcher:
    def __init__(self):
        # Initialize GNews client for fetching top 5 recent articles
        self.google_news = GNews(max_results=5)
        self.fmp_api_key = os.getenv("FMP_API_KEY")
        print(f"[DEBUG]: FMP API Key Loaded: {'YES' if self.fmp_api_key else 'NO (Key is None)'}")

    def fetch_quantitative_metrics(self, ticker: str) -> list:
        """
        Retrieves fundamental metrics for a given ticker using FMP (primary) or yfinance (fallback).
        Formats the raw data into clean, readable sentences.
        """
        # Full date+time (not just date) so the temporal reranker can decay
        # JIT snapshots by day rather than only by year — a metric fetched
        # this morning should outrank the same metric cached three weeks ago.
        current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            if self.fmp_api_key:
                profile_url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={self.fmp_api_key}"
                metrics_url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{ticker}?apikey={self.fmp_api_key}"
                
                profile_resp = requests.get(profile_url)
                profile_resp.raise_for_status()
                profile_data = profile_resp.json()
                
                metrics_resp = requests.get(metrics_url)
                metrics_resp.raise_for_status()
                metrics_data = metrics_resp.json()
                
                if not profile_data or not metrics_data:
                    raise ValueError("FMP returned empty data")

                p_data = profile_data[0]
                m_data = metrics_data[0]
                
                def format_metric(val, is_pct=False):
                    if not isinstance(val, (int, float)):
                        return str(val)
                    if is_pct:
                        return f"{val * 100:.2f}%"
                    if isinstance(val, float) and val.is_integer():
                        return f"{int(val):,}"
                    elif isinstance(val, int):
                        return f"{val:,}"
                    return f"{val:,.2f}"
                
                price = format_metric(p_data.get('price', 'N/A'))
                market_cap = format_metric(p_data.get('mktCap', 'N/A'))
                
                pe_ratio = format_metric(m_data.get('peRatioTTM', 'N/A'))
                peg_ratio = format_metric(m_data.get('pegRatioTTM', 'N/A'))
                debt_to_equity = format_metric(m_data.get('debtToEquityRatioTTM', 'N/A'))
                
                roe = format_metric(m_data.get('roeTTM', 'N/A'), is_pct=True)
                operating_margin = format_metric(m_data.get('operatingProfitMarginTTM', 'N/A'), is_pct=True)
                
                free_cash_flow = format_metric(m_data.get('freeCashFlowTTM', m_data.get('freeCashFlowPerShareTTM', 'N/A')))
                total_revenue = format_metric(m_data.get('revenueTTM', m_data.get('revenuePerShareTTM', 'N/A')))
                net_income = format_metric(m_data.get('netIncomeTTM', m_data.get('netIncomePerShareTTM', 'N/A')))
                
                text_chunk = (
                    f"The current stock price of {ticker} is {price}. "
                    f"Its Price/Earnings-to-Growth (PEG) ratio stands at {peg_ratio}. "
                    f"The trailing P/E ratio is {pe_ratio}. "
                    f"The Market Capitalization of the company is {market_cap}. "
                    f"The Debt-to-Equity ratio is {debt_to_equity}. "
                    f"The Return on Equity (ROE) is {roe}. "
                    f"The Operating Margin is {operating_margin}. "
                    f"The Free Cash Flow is {free_cash_flow}. "
                    f"For the most recent year, the Total Revenue is {total_revenue} and the Net Income is {net_income}."
                )
                
                return [{
                    'text_chunk': text_chunk,
                    'metadata': {
                        'Date_Published': current_date,
                        'Ticker_Symbol': ticker,
                        'Document_Type': 'metrics',
                        'source': 'Financial Modeling Prep (FMP)'
                    }
                }]
            else:
                print("[WARNING]: Skipping FMP because FMP_API_KEY is missing in environment. Falling back to yfinance.")
        except Exception as e:
            logging.warning(f"FMP fetch failed or API key missing, falling back to yfinance: {e}")
            
        # Fallback (yfinance)
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Extract required metrics safely, providing a fallback 'N/A' if missing
            price = info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))
            peg_ratio = info.get('pegRatio', 'N/A')
            pe_ratio = info.get('trailingPE', 'N/A')
            market_cap = info.get('marketCap', 'N/A')
            debt_to_equity = info.get('debtToEquity', 'N/A')
            roe = info.get('returnOnEquity', 'N/A')
            operating_margin = info.get('operatingMargins', 'N/A')
            free_cash_flow = info.get('freeCashflow', 'N/A')
            
            # Access financials for Revenue and Net Income safely
            try:
                financials = stock.financials
                if financials is not None and not financials.empty:
                    recent_col = financials.columns[0]
                    
                    if 'Total Revenue' in financials.index:
                        total_revenue = financials.loc['Total Revenue', recent_col]
                        total_revenue = total_revenue if not pd.isna(total_revenue) else 'N/A'
                    else:
                        total_revenue = 'N/A'
                        
                    if 'Net Income' in financials.index:
                        net_income = financials.loc['Net Income', recent_col]
                        net_income = net_income if not pd.isna(net_income) else 'N/A'
                    else:
                        net_income = 'N/A'
                else:
                    total_revenue = 'N/A'
                    net_income = 'N/A'
            except Exception as e:
                logging.warning(f"Could not fetch financials for {ticker}: {e}")
                total_revenue = 'N/A'
                net_income = 'N/A'
            
            text_chunk = (
                f"The current stock price of {ticker} is {price}. "
                f"Its Price/Earnings-to-Growth (PEG) ratio stands at {peg_ratio}. "
                f"The trailing P/E ratio is {pe_ratio}. "
                f"The Market Capitalization of the company is {market_cap}. "
                f"The Debt-to-Equity ratio is {debt_to_equity}. "
                f"The Return on Equity (ROE) is {roe}. "
                f"The Operating Margin is {operating_margin}. "
                f"The Free Cash Flow is {free_cash_flow}. "
                f"For the most recent year, the Total Revenue is {total_revenue} and the Net Income is {net_income}."
            )
            
            return [{
                'text_chunk': text_chunk,
                'metadata': {
                    'Date_Published': current_date,
                    'Ticker_Symbol': ticker,
                    'Document_Type': 'metrics',
                    'source': 'Yahoo Finance (yfinance)'
                }
            }]
            
        except Exception as e:
            logging.error(f"Failed to fetch quantitative metrics for {ticker}: {e}")
            return []

    def fetch_qualitative_news(self, ticker: str, user_query: str = "") -> list:
        """
        Retrieves top 5 recent news articles related to the ticker using gnews.
        Uses BeautifulSoup to clean any HTML and extract plain text.
        """
        try:
            search_term = f"{ticker} {user_query}".strip()
            news_items = self.google_news.get_news(search_term)
            
            results = []
            # Full date+time (not just date) so the temporal reranker can
            # decay by day, not just by year.
            current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Guard against None if API limit or network issue occurs
            if not news_items:
                logging.warning(f"No news items found for {ticker}.")
                return []

            for item in news_items:
                try:
                    title_html = item.get('title', '')
                    description_html = item.get('description', '')

                    # Clean HTML using BeautifulSoup to extract plain text
                    clean_title = BeautifulSoup(title_html, "html.parser").get_text(separator=" ", strip=True)
                    clean_desc = BeautifulSoup(description_html, "html.parser").get_text(separator=" ", strip=True)

                    # Parse published date if available, else fallback to current date
                    pub_date = item.get('published date')
                    formatted_date = current_date
                    if pub_date:
                        try:
                            # GNews format: 'Tue, 28 Feb 2023 15:00:00 GMT' — GNews
                            # already gives us time-of-day precision; keep it
                            # instead of truncating to date-only as before.
                            parsed_date = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %Z')
                            formatted_date = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            pass # Keep fallback current_date

                    text_chunk = f"Title: {clean_title}\nSummary: {clean_desc}"
                    
                    results.append({
                        'text_chunk': text_chunk,
                        'metadata': {
                            'Date_Published': formatted_date,
                            'Ticker_Symbol': ticker,
                            'Document_Type': 'news',
                            'source': 'Google News'
                        }
                    })
                except Exception as inner_e:
                    logging.warning(f"Failed to process a news item for {ticker}: {inner_e}")
                    continue
                    
            return results
            
        except Exception as e:
            logging.error(f"Failed to fetch qualitative news for {ticker}: {e}")
            return []

if __name__ == "__main__":
    fetcher = FinancialDataFetcher()
    test_ticker = 'TMCV.NS'
    
    print(f"--- Testing Quantitative Metrics for {test_ticker} ---")
    metrics = fetcher.fetch_quantitative_metrics(test_ticker)
    for m in metrics:
        print(f"Chunk: {m['text_chunk']}")
        print(f"Metadata: {m['metadata']}\n")
        
    print(f"--- Testing Qualitative News for {test_ticker} ---")
    news = fetcher.fetch_qualitative_news(test_ticker)
    for n in news:
        print(f"Chunk: {n['text_chunk']}")
        print(f"Metadata: {n['metadata']}\n")
