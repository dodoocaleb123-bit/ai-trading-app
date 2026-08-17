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

# Cache to track the last alerted candle timestamp per symbol+timeframe and prevent duplicate spam
last_alerted_candles = {}

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

async def send_telegram_alert(message: str, reply_to_message_id: int = None) -> int | None:
    """Pushes autonomous trade signals or threaded replies directly to Telegram and returns the message ID."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing in .env file.")
        return None
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=5.0)
            data = res.json()
            if data.get("ok"):
                return data["result"]["message_id"]
    except Exception as e:
        print(f"Failed to dispatch Telegram alert: {e}")
        
    return None

# ------------------------------------------------------------------
# Section 3: Trade Outcome Tracking & Background Scanner
# ------------------------------------------------------------------
async def check_tracked_trades_outcomes():
    """Background task checking active tracked signals against live prices, evaluating Win/Loss, and running forensic self-learning on losses."""
    try:
        response = supabase.table("tracked_signals").select("*").eq("status", "OPEN").execute()
        open_trades = response.data if response and response.data else []
        
        if not open_trades:
            return

        for trade in open_trades:
            trade_id = trade["id"]
            symbol = trade["symbol"]
            direction = trade["direction"]
            entry = float(trade["entry_price"])
            sl = float(trade["stop_loss"])
            tp = float(trade["take_profit"])
            tf = trade["timeframe"]
            original_msg_id = trade.get("telegram_message_id")

            current_price = await get_live_price_rest(symbol)
            if current_price <= 0.0:
                continue

            outcome = None
            if direction == "BUY":
                if current_price >= tp:
                    outcome = "WIN"
                elif current_price <= sl:
                    outcome = "LOSS"
            elif direction == "SELL":
                if current_price <= tp:
                    outcome = "WIN"
                elif current_price >= sl:
                    outcome = "LOSS"

            if outcome:
                # 1. Update status in tracked_signals table
                supabase.table("tracked_signals").update({"status": outcome}).eq("id", trade_id).execute()
                
                new_rule_created = False
                diagnostic_summary = ""
                
                # 2. Advanced Self-Learning Loop: Forensic Analysis on Loss
                if outcome == "LOSS":
                    try:
                        # Fetch recent candles leading to failure for forensic analysis
                        failure_candles = await fetch_recent_candles(symbol, interval=tf, outputsize=3)
                        market_context_str = f"Candles leading to loss: {failure_candles}" if failure_candles else "No candle data available."

                        diagnosis_prompt = f"""You are an expert quantitative trading risk manager. An autonomous trade just failed. Analyze the failure and write a specific, forensic lesson learned.
Asset: {symbol} | Timeframe: {tf} | Direction: {direction} | Entry: {entry} | Stop Loss Hit: {sl} | Exit Price: {current_price}
{market_context_str}

Return ONLY a valid JSON object matching this exact structure:
{{
  "root_cause": "<1-sentence explanation of why the trade failed based on price action>",
  "new_rule": "<1-sentence concise, actionable trading guardrail rule to prevent this specific mistake>"
}}"""

                        diagnosis_completion = groq_client.chat.completions.create(
                            messages=[{"role": "user", "content": diagnosis_prompt}],
                            model="llama-3.1-8b-instant",
                            response_format={"type": "json_object"},
                            temperature=0.2
                        )
                        
                        diag_data = json.loads(diagnosis_completion.choices[0].message.content)
                        root_cause = diag_data.get("root_cause", "False breakout or unexpected volatility spike.")
                        new_rule_content = diag_data.get("new_rule", f"Exercise caution on {symbol} {tf} setups during high volatility.")
                        diagnostic_summary = root_cause

                        # Save forensic root cause to past_mistakes
                        mistake_payload = {
                            "asset_pair": symbol,
                            "lesson_learned": f"Forensic Loss Analysis [{tf}]: {root_cause}",
                            "embedding": [0.0] * 384
                        }
                        supabase.table("past_mistakes").insert(mistake_payload).execute()

                        # Save adaptive rule to strategy_rules
                        rule_payload = {
                            "content": f"[Auto-Learned Guardrail from {symbol} Loss]: {new_rule_content}",
                            "embedding": [0.0] * 384
                        }
                        supabase.table("strategy_rules").insert(rule_payload).execute()
                        new_rule_created = True
                        print(f"🧠 Advanced AI Learning: Successfully diagnosed {symbol} loss and updated strategy rules.")
                    except Exception as learn_err:
                        print(f"Failed to record advanced trade loss analysis: {learn_err}")

                # 3. Send threaded Telegram result notification replying directly to the signal
                emoji = "✅ *WIN*" if outcome == "WIN" else "❌ *LOSS (AI Self-Diagnosed)*"
                result_alert = (
                    f"🎯 *TRADE RESULT REPORT*\n\n"
                    f"• *Status:* {emoji}\n"
                    f"• *Exit Price:* {current_price}\n"
                    f"• *Target Hit:* {'Take Profit' if outcome == 'WIN' else 'Stop Loss'}"
                )
                if diagnostic_summary:
                    result_alert += f"\n\n🔍 *AI Root Cause:* {diagnostic_summary}"
                if new_rule_created:
                    result_alert += f"\n\n💡 *AI Adaptation:* Protective risk rule registered."

                await send_telegram_alert(result_alert, reply_to_message_id=original_msg_id)

    except Exception as e:
        print(f"Error checking tracked trade outcomes: {e}")

async def autonomous_market_scan():
    """Background task evaluating market setups across a watchlist and multiple timeframes with asset-aware risk sizing and trend confirmation."""
    global last_alerted_candles
    forex_open = is_forex_market_open()
    
    watchlist = ["XAU/USD", "EUR/USD", "GBP/USD", "BTC/USD"]
    timeframes = ["15min", "1h", "4h"]
    
    for symbol in watchlist:
        if not forex_open and symbol != "BTC/USD":
            continue

        for tf in timeframes:
            try:
                candles = await fetch_recent_candles(symbol, interval=tf, outputsize=5)
                if not candles or len(candles) < 3:
                    continue
                
                latest_candle_time = candles[0]["datetime"]
                cache_key = f"{symbol}_{tf}"
                
                if last_alerted_candles.get(cache_key) == latest_candle_time:
                    continue
                    
                c0 = float(candles[0]["close"])
                c1 = float(candles[1]["close"])
                c2 = float(candles[2]["close"])
                
                is_bullish = c0 > c1 and c1 > c2
                is_bearish = c0 < c1 and c1 < c2
                
                if not is_bullish and not is_bearish:
                    continue  
                    
                direction = "BUY" if is_bullish else "SELL"
                last_alerted_candles[cache_key] = latest_candle_time
                
                if "BTC" in symbol:
                    sl_offset = c0 * 0.0012
                elif "XAU" in symbol:
                    sl_offset = c0 * 0.0006
                else:
                    sl_offset = c0 * 0.0003

                est_sl = round(c0 - sl_offset, 4) if direction == "BUY" else round(c0 + sl_offset, 4)
                risk_distance = abs(c0 - est_sl)
                est_tp = round(c0 + (risk_distance * 2), 4) if direction == "BUY" else round(c0 - (risk_distance * 2), 4)
                
                scan_message = (
                    f"AUTOMATED 24/7 SCAN [{tf.upper()}]: Confirmed trend {direction} setup on {symbol}. "
                    f"Entry Price: {c0}, Stop Loss: {est_sl}, Take Profit: {est_tp}."
                )
                
                audit_req = ChatAuditRequest(message=scan_message)
                audit_result = await audit_chat_message(audit_req)
                
                if audit_result.get("verdict") in ["APPROVED", "WARNING"]:
                    alert_text = (
                        f"🚨 *TRADING SIGNAL ALERT* 🚨\n\n"
                        f"• *Asset:* {symbol}\n"
                        f"• *Timeframe:* `{tf.upper()}`\n"
                        f"• *Direction:* {direction}\n"
                        f"• *Entry:* {c0}\n"
                        f"• *Stop Loss:* {est_sl}\n"
                        f"• *Take Profit:* {est_tp}\n"
                        f"• *Risk/Reward:* 1:2"
                    )
                    
                    msg_id = await send_telegram_alert(alert_text)

                    try:
                        tracked_payload = {
                            "symbol": symbol,
                            "direction": direction,
                            "entry_price": c0,
                            "stop_loss": est_sl,
                            "take_profit": est_tp,
                            "timeframe": tf.upper(),
                            "status": "OPEN",
                            "telegram_message_id": msg_id
                        }
                        supabase.table("tracked_signals").insert(tracked_payload).execute()
                    except Exception as db_err:
                        print(f"Failed to save tracked signal: {db_err}")
                        
            except Exception as e:
                print(f"Error during background scan for {symbol} on {tf}: {e}")

# ------------------------------------------------------------------
# Section 4: FastAPI Initialization & Lifespan Event
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(autonomous_market_scan, 'interval', minutes=1)
    scheduler.add_job(check_tracked_trades_outcomes, 'interval', minutes=5)
    scheduler.start()
    print("🚀 Autonomous Multi-Timeframe Market Scanner & Outcome Tracker Started")
    yield
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

# Capacitor Android loads the packaged web bundle from http://localhost.
# Keep this separate from the Vite development server origin (http://localhost:5173).
origins = [
    "http://localhost",
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
    verdict: str
    confidence_score: int
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

class StrategyRuleRequest(BaseModel):
    rule_content: str

# ------------------------------------------------------------------
# Section 6: Endpoints
# ------------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "online", "message": "24/7 AI Trading Sentinel Engine is Running"}

@app.post("/chat-audit", response_model=AuditResponse)
async def audit_chat_message(req: ChatAuditRequest):
    try:
        forex_open = is_forex_market_open()
        market_status_note = (
            "Forex Market is OPEN." if forex_open 
            else "Forex Market is CLOSED (Weekend session). Note: Crypto assets like BTC/USD trade 24/7 and are fully active."
        )

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

        query_vector = [0.0] * 384

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

@app.post("/add-rule")
def add_strategy_rule(req: StrategyRuleRequest):
    try:
        embedding = [0.0] * 384
        data = {
            "content": f"[User Custom Rule]: {req.rule_content}",
            "embedding": embedding
        }
        supabase.table("strategy_rules").insert(data).execute()
        return {"status": "success", "message": "Custom strategy rule added to AI memory!"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error saving rule: {str(e)}")

# Added alias endpoint to support alternative frontend paths if requested
@app.post("/rules")
def add_strategy_rule_alias(req: StrategyRuleRequest):
    return add_strategy_rule(req)

@app.get("/history")
def get_history(limit: int = 10):
    try:
        resp = supabase.table("trade_signals").select("*").order("created_at", desc=True).limit(limit).execute()
        return {"status": "success", "history": resp.data if resp.data else []}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database query failed. Please ensure table 'trade_signals' exists in Supabase. Internal error: {str(e)}")
