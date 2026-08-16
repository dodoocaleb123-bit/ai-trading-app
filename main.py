import os
import json
import re
import traceback
import httpx
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

# ------------------------------------------------------------------
# Section 1: API Keys & Environment Variables
# ------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variable.")

if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY environment variable.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)
scheduler = AsyncIOScheduler()

# ------------------------------------------------------------------
# Section 2: Helper & Market Data Functions
# ------------------------------------------------------------------
def is_forex_market_open() -> bool:
    """Checks if global Forex markets are open (Closes Friday 22:00 UTC, Opens Sunday 22:00 UTC)."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0 = Monday, 6 = Sunday
    hour = now.hour

    if weekday == 4 and hour >= 22:  # Friday after 10 PM UTC
        return False
    if weekday == 5:  # Saturday
        return False
    if weekday == 6 and hour < 22:  # Sunday before 10 PM UTC
        return False

    return True

def extract_symbol_from_message(message: str) -> str | None:
    """Extracts common trading symbols from raw user signal messages."""
    known_symbols = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "BTCUSD", "ETHUSD"]
    clean_msg = message.upper().replace("/", "")
    
    for symbol in known_symbols:
        if symbol in clean_msg:
            if len(symbol) == 6:
                return f"{symbol[:3]}/{symbol[3:]}"
            return symbol
            
    match = re.search(r'\b[A-Z]{6}\b', clean_msg)
    if match:
        sym = match.group(0)
        return f"{sym[:3]}/{sym[3:]}"
        
    return None

async def get_live_price_rest(symbol: str) -> float:
    """Fetches real-time spot price feed from Twelve Data REST API."""
    if not TWELVE_DATA_API_KEY:
        return 0.0
        
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVE_DATA_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=5.0)
            data = res.json()
            if "price" in data:
                return float(data["price"])
    except Exception as e:
        print(f"Error fetching live market price for {symbol}: {e}")
        
    return 0.0

async def fetch_recent_candles(symbol: str, interval: str = "15min", outputsize: int = 5) -> list[dict]:
    """Fetches recent OHLCV candlestick time-series data from Twelve Data."""
    if not TWELVE_DATA_API_KEY:
        return []
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=5.0)
            data = res.json()
            return data.get("values", [])
    except Exception as e:
        print(f"Error fetching candles for {symbol} ({interval}): {e}")
        return []

async def send_telegram_alert(message: str):
    """Pushes autonomous trade signals directly to your mobile device via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing in .env file.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=5.0)
    except Exception as e:
        print(f"Failed to dispatch Telegram alert: {e}")

# ------------------------------------------------------------------
# Section 3: 24/7 Autonomous Multi-Timeframe Background Market Scanner
# ------------------------------------------------------------------
async def autonomous_market_scan():
    """Background task evaluating market setups across a watchlist and multiple timeframes."""
    # Guard check: Skip scanning Forex symbols when market is closed
    forex_open = is_forex_market_open()
    
    watchlist = ["XAU/USD", "EUR/USD", "GBP/USD", "BTC/USD"]
    timeframes = ["5min", "15min", "1h", "4h"]
    
    for symbol in watchlist:
        # Skip traditional Forex pairs if the market is closed (BTC/USD runs 24/7)
        if not forex_open and symbol != "BTC/USD":
            continue

        for tf in timeframes:
            try:
                candles = await fetch_recent_candles(symbol, interval=tf, outputsize=5)
                if not candles or len(candles) < 2:
                    continue
                    
                latest_close = float(candles[0]["close"])
                prev_close = float(candles[1]["close"])
                high = float(candles[0]["high"])
                low = float(candles[0]["low"])
                
                # Technical Trigger: Evaluate volatility / price expansion (>0.1% move)
                price_change_pct = abs((latest_close - prev_close) / prev_close) * 100
                
                if price_change_pct >= 0.10:
                    direction = "BUY" if latest_close > prev_close else "SELL"
                    est_sl = round(low - (latest_close * 0.002), 4) if direction == "BUY" else round(high + (latest_close * 0.002), 4)
                    est_tp = round(latest_close + (abs(latest_close - est_sl) * 2), 4) if direction == "BUY" else round(latest_close - (abs(latest_close - est_sl) * 2), 4)
                    
                    scan_message = (
                        f"AUTOMATED 24/7 SCAN [{tf.upper()}]: Potential {direction} setup on {symbol}. "
                        f"Entry Price: {latest_close}, Stop Loss: {est_sl}, Take Profit: {est_tp}."
                    )
                    
                    # Hand off detected technical setup to AI Audit Engine
                    audit_req = ChatAuditRequest(message=scan_message)
                    audit_result = await audit_chat_message(audit_req)
                    
                    # Push instant alert if AI approves setup against RAG strategy rules
                    if audit_result.get("verdict") in ["APPROVED", "WARNING"]:
                        # Custom cleanly formatted message payload
                        alert_text = (
                            f"🚨 *TRADING SIGNAL ALERT* 🚨\n\n"
                            f"• *Asset:* {symbol}\n"
                            f"• *Direction:* {direction}\n"
                            f"• *Entry:* {latest_close}\n"
                            f"• *Stop Loss:* {est_sl}\n"
                            f"• *Take Profit:* {est_tp}\n"
                            f"• *Risk/Reward:* 1:2"
                        )
                        await send_telegram_alert(alert_text)
                        
            except Exception as e:
                print(f"Error during background scan for {symbol} on {tf}: {e}")

# ------------------------------------------------------------------
# Section 4: FastAPI Initialization & Lifespan Event
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start background scanner loop (runs every 15 minutes)
    scheduler.add_job(autonomous_market_scan, 'interval', minutes=15)
    scheduler.start()
    print("🚀 Autonomous Multi-Timeframe Market Scanner Started")
    yield
    # Shutdown: Stop scheduler gracefully
    scheduler.shutdown()

app = FastAPI(
    title="AI Trading Strategy Audit API",
    description="RAG-powered API to audit trades and run autonomous multi-timeframe market scans.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

origins = [
    "http://localhost:5173",
    "https://ai-trading-app-lyart.vercel.app",
    "https://ai-trading-app.vercel.app",
    "https://ai-trading-app-git-main-tech-angel1.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Section 5: Data Models
# ------------------------------------------------------------------
class ChatAuditRequest(BaseModel):
    message: str

class AuditResponse(BaseModel):
    verdict: str  # APPROVED, REJECTED, or WARNING
    confidence_score: int  # 0 to 100
    risk_reward_ratio: float
    summary: str
    violations: list[str]
    improvements: list[str]

class TradeSignalRequest(BaseModel):
    asset_pair: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    setup_notes: str

class MistakeRequest(BaseModel):
    asset_pair: str
    lesson_learned: str

# ------------------------------------------------------------------
# Section 6: Endpoints
# ------------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "online", "message": "24/7 AI Trading Sentinel Engine is Running"}

@app.post("/chat-audit", response_model=AuditResponse)
async def audit_chat_message(req: ChatAuditRequest):
    try:
        # Check active session status for traditional Forex market
        forex_open = is_forex_market_open()
        market_status_note = (
            "Forex Market is OPEN." if forex_open 
            else "Forex Market is CLOSED (Weekend session). Note: Crypto assets like BTC/USD trade 24/7 and are fully active."
        )

        # 1. Fetch live market price if a ticker/symbol is detected
        live_price_info = "Live market price unavailable."
        
        for symbol in ["XAUUSD", "EURUSD", "GBPUSD", "BTCUSD"]:
            if symbol.lower() in req.message.lower():
                current_price = await get_live_price_rest(symbol)
                if current_price > 0:
                    live_price_info = f"Current Live Market Price for {symbol}: {current_price}"
                break

        detected_symbol = extract_symbol_from_message(req.message)
        if live_price_info == "Live market price unavailable." and detected_symbol:
            current_price = await get_live_price_rest(detected_symbol)
            if current_price > 0:
                live_price_info = f"Current Live Market Price for {detected_symbol}: {current_price}"

        # 2. Fallback query vector (384 dimensions for pgvector compatibility)
        query_vector = [0.0] * 384

        # 3. Vector Search against strategy rules & past mistakes
        relevant_rules = []
        try:
            rules_resp = supabase.rpc(
                'match_strategy_rules', 
                {'query_embedding': query_vector, 'match_threshold': 0.1, 'match_count': 5}
            ).execute()
            if rules_resp and rules_resp.data:
                relevant_rules = [r['content'] for r in rules_resp.data if 'content' in r]
        except Exception as e:
            print(f"Strategy rules RPC search skipped: {e}")

        past_mistakes = []
        try:
            mistakes_resp = supabase.rpc(
                'match_past_mistakes', 
                {'query_embedding': query_vector, 'match_threshold': 0.1, 'match_count': 3}
            ).execute()
            if mistakes_resp and mistakes_resp.data:
                past_mistakes = [f"[{m.get('asset_pair', 'ALL')}] {m.get('lesson_learned', '')}" for m in mistakes_resp.data]
        except Exception as e:
            print(f"Past mistakes RPC search skipped: {e}")

        rules_context = "\n---\n".join(relevant_rules) if relevant_rules else "No specific strategy rules matched."
        mistakes_context = "\n---\n".join(past_mistakes) if past_mistakes else "No similar past mistakes detected."

        # 4. Build prompt incorporating market session context and live feeds
        prompt = f"""You are an expert AI Trading Copilot and Risk Manager inside a live trading chat application.
The trader just posted this raw trade signal:

"{req.message}"

### MARKET SESSION STATUS:
{market_status_note}

### REAL-TIME MARKET DATA:
{live_price_info}

### RETRIEVED STRATEGY RULES (System Context):
{rules_context}

### RETRIEVED PAST TRADER MISTAKES (System Context):
{mistakes_context}

### INSTRUCTIONS:
1. If the detected asset is a Forex/Commodity pair (e.g. EURUSD, GBPUSD, XAUUSD) and the Forex Market is CLOSED, audit the trade setup theoretically for weekend planning and note that live execution is paused. HOWEVER, if the asset is Crypto (e.g. BTC/USD or BTCUSD), crypto markets are OPEN 24/7, so do NOT flag a market closure violation for crypto.
2. DO NOT reject or penalize a trade signal simply because the user provided a fast, brief entry without typing out full market context or strategy names in text.
3. Automatically parse the trade parameters (Asset Pair, Direction, Entry Price, Stop Loss, Take Profit) from the signal.
4. Compare the trader's proposed entry price against the CURRENT LIVE MARKET PRICE (if available) to detect slippage or invalid pending orders.
5. Mathematically evaluate or calculate the Risk-to-Reward ratio based on the price levels provided.
6. Compare the trade against the retrieved strategy rules and past mistakes:
   - Verify if the setup meets minimum Risk-Reward thresholds (e.g., 1:2+).
   - Check if the trade mirrors any logged past mistakes or violates risk constraints.
7. Provide proactive, actionable trade optimization advice in 'summary' and 'improvements' (e.g., specific SL/TP price adjustments to optimize risk-reward).

Return ONLY a valid JSON object matching this exact structure:
{{
  "verdict": "APPROVED" | "WARNING" | "REJECTED",
  "confidence_score": <number between 0 and 100>,
  "risk_reward_ratio": <calculated or estimated float, e.g. 2.0>,
  "summary": "<1-2 sentence executive audit summary with clear trade guidance>",
  "violations": ["<violation or conflict with live price, strategy rules, market hours, or past mistakes>"],
  "improvements": ["<concrete level adjustment or trade optimization suggestion>"]
}}
"""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are a proactive AI Trading Copilot and Risk Manager. You evaluate raw trade inputs against live market prices, session hours, pre-loaded strategy rules, and past mistakes, providing constructive trade optimizations."
                },
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        raw_reply = chat_completion.choices[0].message.content
        audit_data = json.loads(raw_reply)

        # Save to history with fallback error handling
        try:
            log_entry = {
                "asset_pair": detected_symbol if detected_symbol else "CHAT_SIGNAL",
                "direction": "AUDIT",
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "setup_notes": req.message,
                "audit_report": raw_reply
            }
            supabase.table("trade_signals").insert(log_entry).execute()
        except Exception as db_err:
            print(f"Warning: Failed to log audit signal to Supabase trade_signals table: {db_err}")

        return audit_data

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/add-mistake")
def add_mistake(req: MistakeRequest):
    try:
        embedding = [0.0] * 384
        data = {
            "asset_pair": req.asset_pair.upper(),
            "lesson_learned": req.lesson_learned,
            "embedding": embedding
        }
        supabase.table("past_mistakes").insert(data).execute()
        return {"status": "success", "message": "Mistake logged to memory"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error logging mistake: {str(e)}")

@app.get("/history")
def get_history(limit: int = 10):
    try:
        resp = supabase.table("trade_signals").select("*").order("created_at", desc=True).limit(limit).execute()
        return {"status": "success", "history": resp.data if resp.data else []}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database query failed. Please ensure table 'trade_signals' exists in Supabase. Internal error: {str(e)}")