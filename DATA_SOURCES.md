# Data Sources & APIs

This document outlines the proposed data sources for each signal pillar. Each pillar is served by one or more APIs, consumed by an independent data collection microservice.

---

## Pillar 1: Technical Analysis
*Price action, volume, momentum indicators (RSI, MACD, moving averages)*

| Provider | Description | Free Tier | Notes |
|----------|-------------|-----------|-------|
| **Alpha Vantage** | Real-time & historical OHLCV data, 60+ built-in technical indicators (RSI, MACD, Bollinger Bands, etc.) | Yes | NASDAQ-licensed, widely used, good documentation |
| **Twelve Data** | Deep historical candlestick data, 100+ technical indicators, WebSocket streaming | Yes (limited) | Best for backtesting due to historical depth |
| **Polygon.io** | Tick-by-tick data, WebSocket streaming, strong for real-time signals | Yes (limited) | Best for real-time; paid plans for full access |

**Recommended Start**: Alpha Vantage (free tier, broad indicator support, easy to implement)

---

## Pillar 2: Fundamental Analysis
*Earnings reports, revenue growth, profit margins, cash flow, valuation metrics, earnings calendar*

| Provider | Description | Free Tier | Notes |
|----------|-------------|-----------|-------|
| **Financial Modeling Prep (FMP)** | Broad all-in-one API: income statements, balance sheets, earnings calendars, analyst estimates, DCF valuations | Yes | Best all-around for fundamentals |
| **Alpha Vantage** | Earnings data, income statements, balance sheets, EPS surprises | Yes | Good complement to technical data from same API |
| **SEC EDGAR (Official)** | Raw 10-K, 10-Q, 8-K filings, XBRL financial data | Free | Official source, requires parsing |
| **SEC-API.io** | Structured, easy-to-query wrapper around EDGAR data | Paid | Much easier to implement than raw EDGAR |

**Recommended Start**: Financial Modeling Prep (earnings calendar + surprise data + fundamentals in one API)

**Key Metrics to Extract**:
- EPS actual vs. estimate (earnings surprise)
- Revenue actual vs. estimate
- Forward guidance (raised / maintained / lowered)
- Year-over-year revenue and margin trends
- P/E, P/B, Price-to-Free-Cash-Flow ratios

---

## Pillar 3: Institutional & Smart Money Tracking
*13F filings, insider transactions, hedge fund positioning, prominent investor moves*

| Provider | Description | Free Tier | Notes |
|----------|-------------|-----------|-------|
| **SEC EDGAR (Official)** | Raw 13F quarterly filings from all institutional investors | Free | Direct source, requires parsing |
| **SEC-API.io** | Structured 13F, insider trading, beneficial ownership data | Paid | Real-time alerts + historical trends |
| **Kaleidoscope** | Institutional portfolio diffs, insider transactions, executive biographies | Paid | Tracks quarterly position changes cleanly |
| **Finnhub** | Insider transactions, institutional ownership, real-time SEC filings | Yes (limited) | Good free starting point |

**Recommended Start**: Finnhub (free insider + institutional data) → upgrade to SEC-API.io for full 13F coverage

**Key Signals to Track**:
- New positions opened by prominent funds (Berkshire, Bridgewater, etc.)
- Significant increases in existing positions
- Insider buying (executives buying their own stock is a strong signal)
- Unusual accumulation patterns across multiple institutions

---

## Pillar 4: Market Sentiment & Analyst Consensus
*News sentiment, analyst buy/sell/hold ratings, price targets, social sentiment*

| Provider | Description | Free Tier | Notes |
|----------|-------------|-----------|-------|
| **Finnhub** | News sentiment, analyst recommendations, earnings surprises, social sentiment | Yes | Very strong free tier for sentiment |
| **Financial Modeling Prep (FMP)** | Analyst consensus, price targets, historical social sentiment | Yes (limited) | Good complement to fundamentals data |
| **EODHD** | Financial news feed, sentiment scoring per ticker, weighted keyword analysis | Paid (€19.99/mo) | Purpose-built for financial sentiment |
| **StockGeist** | Sentiment API trained specifically on financial news and market language | Paid | High quality financial NLP |
| **Alpha Vantage** | Market news API with sentiment scoring | Yes | Easy starting point, already integrated |

**Recommended Start**: Finnhub (free sentiment + analyst ratings) supplemented by Alpha Vantage news sentiment

**Key Signals to Track**:
- Analyst consensus: Strong Buy / Buy / Hold / Sell / Strong Sell
- Analyst price target vs. current price (upside/downside %)
- Recent rating upgrades or downgrades
- News sentiment score (positive/negative/neutral) over trailing 7-30 days
- Sentiment momentum (is news getting better or worse?)

---

## Pillar 5: Backtesting & Historical Data
*Historical price data, past fundamentals, historical filings for strategy validation*

| Provider | Description | Free Tier | Notes |
|----------|-------------|-----------|-------|
| **Twelve Data** | Decades of OHLCV historical data, 100+ indicators | Yes (limited) | Best historical depth for price data |
| **Alpha Vantage** | Extended historical price and fundamental data | Yes | Consistent with live data source |
| **Financial Modeling Prep** | Historical earnings, historical fundamentals, historical analyst estimates | Yes | Allows backtesting fundamental strategies |
| **Backtrader** | Open-source Python backtesting framework | Free | Connects to data sources above |
| **Zipline (Quantopian fork)** | Python backtesting engine, battle-tested by quant community | Free | More complex but very powerful |

**Recommended Approach**: Use Backtrader with Twelve Data + FMP historical feeds to simulate strategy performance across 5-10 years of market data

---

## Summary: Recommended Initial Stack

| Pillar | Primary API | Backup/Supplement |
|--------|------------|-------------------|
| Technical Analysis | Alpha Vantage | Twelve Data |
| Fundamental Analysis | Financial Modeling Prep | SEC EDGAR |
| Institutional Tracking | Finnhub | SEC-API.io |
| Sentiment & Analyst | Finnhub | Alpha Vantage News |
| Backtesting | Backtrader + Twelve Data | Zipline |

---

## Integration Notes
- All APIs return JSON — standardize internal data schema early
- Build one microservice per pillar, not per API
- Normalize all signals to a common score scale (e.g., -1 to +1 or 0-100) before feeding to the scoring engine
- Cache API responses to avoid rate limits and reduce costs
- Log all raw data for audit trail and future backtesting

---

## Future Data Sources (Later Phases)
- **Crypto**: On-chain metrics (Glassnode), exchange order flow, whale wallet tracking
- **Macro**: Fed decisions, CPI, GDP data (FRED API — free)
- **Alternative Data**: Satellite imagery, web traffic, job posting trends
- **Real Estate Tokens**: Specialized tokenized real estate data providers
