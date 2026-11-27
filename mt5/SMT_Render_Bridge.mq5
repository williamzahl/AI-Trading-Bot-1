//+------------------------------------------------------------------+
//| SMT_Render_Bridge.mq5                                            |
//| Henter godkjente ordre fra Render (smt-webhook) og utfoerer dem. |
//| Kjoeres paa MetaQuotes VPS slik at PC-en kan vaere av.           |
//|                                                                  |
//| Oppsett i MT5: Tools > Options > Expert Advisors                 |
//|   - huk av "Allow WebRequest for listed URL"                     |
//|   - legg til https://smt-webhook-4dgq.onrender.com               |
//+------------------------------------------------------------------+
#property copyright "SMT Bot"
#property version   "1.20"
#property strict

#include <Trade/Trade.mqh>

input string InpBaseUrl      = "https://smt-webhook-4dgq.onrender.com"; // Render-adresse
input string InpKey          = "";      // MT5_EA_KEY fra Render
input int    InpPollSeconds  = 3;       // Hvor ofte Render spoerres (sek)
input long   InpMagic        = 260611;  // Magic number for EA-ens ordre
input int    InpSlippagePts  = 50;      // Maks slippage i punkter

CTrade trade;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringLen(InpKey) == 0)
     {
      Print("SMT: InpKey er tom. Lim inn MT5_EA_KEY fra Render.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePts);
   EventSetTimer((int)MathMax(1, InpPollSeconds));
   Print("SMT: startet. Spoer ", InpBaseUrl, " hvert ", InpPollSeconds, " sek.");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
//| HTTP-hjelper                                                     |
//+------------------------------------------------------------------+
bool Http(const string method, const string url, string &body)
  {
   char data[], result[];
   string headers = "Content-Type: text/plain\r\n", resHeaders;
   ResetLastError();
   int code = WebRequest(method, url, headers, 10000, data, result, resHeaders);
   if(code == -1)
     {
      int err = GetLastError();
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn > 300)
        {
         Print("SMT: WebRequest feilet (", err, "). Er URL-en lagt til under Tools > Options > Expert Advisors?");
         lastWarn = TimeCurrent();
        }
      return(false);
     }
   body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(code != 200)
     {
      Print("SMT: Render svarte ", code, ": ", body);
      return(false);
     }
   return(true);
  }

string UrlEncode(const string s)
  {
   string out = "";
   uchar bytes[];
   int n = StringToCharArray(s, bytes, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   for(int i = 0; i < n; i++)
     {
      uchar c = bytes[i];
      if((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '-' || c == '_' || c == '.')
         out += CharToString(c);
      else
         out += StringFormat("%%%02X", c);
     }
   return(out);
  }

// Henter verdi fra "a=1;b=2"
string Field(const string text, const string key)
  {
   string parts[];
   int n = StringSplit(text, ';', parts);
   for(int i = 0; i < n; i++)
     {
      int eq = StringFind(parts[i], "=");
      if(eq > 0 && StringSubstr(parts[i], 0, eq) == key)
         return(StringSubstr(parts[i], eq + 1));
     }
   return("");
  }

void Report(const string id, const bool ok, const string ticket, const double price,
            const double sl, const double tp, const string msg, const int digits,
            const double lot = 0, const double risk = 0)
  {
   string url = InpBaseUrl + "/mt5/result?key=" + UrlEncode(InpKey) + "&id=" + id +
                "&ok=" + (ok ? "1" : "0") + "&ticket=" + ticket +
                "&price=" + DoubleToString(price, digits) +
                "&sl=" + DoubleToString(sl, digits) + "&tp=" + DoubleToString(tp, digits) +
                "&lot=" + DoubleToString(lot, 2) + "&risk=" + DoubleToString(risk, 2) +
                "&msg=" + UrlEncode(msg);
   string body;
   for(int attempt = 0; attempt < 3; attempt++)
     {
      if(Http("POST", url, body)) return;
      Sleep(1000);
     }
   Print("SMT: klarte ikke melde resultat for #", id);
  }

int OpenPositions()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         count++;
     }
   return(count);
  }

double NormalizeLot(const string symbol, double lot)
  {
   double minLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(step > 0) lot = MathFloor(lot / step + 1e-9) * step;
   if(lot < minLot) lot = minLot;
   if(lot > maxLot) lot = maxLot;
   return(lot);
  }

// Meld til Render naar en SMT-trade lukkes (TP, SL eller manuelt)
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY) return;

   long   posId  = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   double price  = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) +
                   HistoryDealGetDouble(trans.deal, DEAL_SWAP) +
                   HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   long   reasonCode = HistoryDealGetInteger(trans.deal, DEAL_REASON);
   string symbol = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

   // Finn aapningshandelen for aa faa signal-ID fra kommentaren "SMT #123"
   if(!HistorySelectByPosition(posId)) return;
   string id = "";
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic) return;
      string c = HistoryDealGetString(d, DEAL_COMMENT);
      if(StringFind(c, "SMT #") == 0) id = StringSubstr(c, 5);
      // Lukk-handelens kommisjon ligger ofte paa aapningshandelen
      profit += HistoryDealGetDouble(d, DEAL_COMMISSION);
     }
   if(StringLen(id) == 0) return;

   string reason = "OTHER";
   if(reasonCode == DEAL_REASON_TP) reason = "TP";
   else if(reasonCode == DEAL_REASON_SL) reason = "SL";
   else if(reasonCode == DEAL_REASON_SO) reason = "SO";
   else if(reasonCode == DEAL_REASON_EXPERT) reason = "EA";
   else if(reasonCode == DEAL_REASON_CLIENT || reasonCode == DEAL_REASON_MOBILE || reasonCode == DEAL_REASON_WEB) reason = "MANUAL";

   string url = InpBaseUrl + "/mt5/closed?key=" + UrlEncode(InpKey) + "&id=" + id +
                "&price=" + DoubleToString(price, digits) +
                "&profit=" + DoubleToString(profit, 2) + "&reason=" + reason;
   string body;
   for(int attempt = 0; attempt < 3; attempt++)
     {
      if(Http("POST", url, body)) { Print("SMT: meldte lukking av #", id, " (", reason, " ", profit, ")"); return; }
      Sleep(1000);
     }
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   string url = InpBaseUrl + "/mt5/next?key=" + UrlEncode(InpKey) +
                "&account=" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   string body;
   if(!Http("GET", url, body)) return;
   if(body == "NONE" || StringLen(body) == 0) return;

   string id     = Field(body, "id");
   string symbol = Field(body, "symbol");
   string side   = Field(body, "side");
   double lot    = StringToDouble(Field(body, "lot"));
   double riskUsd = StringToDouble(Field(body, "risk_usd"));
   double rr      = StringToDouble(Field(body, "rr"));
   int    lookback= (int)StringToInteger(Field(body, "lookback"));
   double buffer  = StringToDouble(Field(body, "buffer"));
   double maxLot  = StringToDouble(Field(body, "max_lot"));
   double maxSlPct= StringToDouble(Field(body, "max_sl_pct"));
   int    maxPos  = (int)StringToInteger(Field(body, "max_pos"));
   if(rr <= 0) rr = 3;
   if(lookback <= 0) lookback = 6;
   Print("SMT: fikk ordre #", id, " ", side, " ", symbol, " risiko ", riskUsd, " R:R 1:", rr);

   if(!SymbolSelect(symbol, true))
     { Report(id, false, "", 0, 0, 0, "Symbol " + symbol + " finnes ikke i MT5", 2); return; }
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     { Report(id, false, "", 0, 0, 0, "Algo Trading er slaatt av i MT5", digits); return; }
   if(maxPos > 0 && OpenPositions() >= maxPos)
     { Report(id, false, "", 0, 0, 0, "SKIP: allerede " + IntegerToString(OpenPositions()) + " aapne posisjoner", digits); return; }

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0)
     { Report(id, false, "", 0, 0, 0, "Ingen pris for " + symbol + " (marked stengt?)", digits); return; }

   bool buy = (side == "BUY");
   double price = buy ? tick.ask : tick.bid;
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);

   // SL ALLTID under laveste low (kjoep) / over hoeyeste high (salg) paa 5M,
   // inkludert lyset som er under dannelse, pluss en liten buffer.
   double sl;
   if(buy)
     {
      int idx = iLowest(symbol, PERIOD_M5, MODE_LOW, lookback, 0);
      if(idx < 0) { Report(id, false, "", price, 0, 0, "Fant ikke 5M-lows for SL", digits); return; }
      sl = MathMin(iLow(symbol, PERIOD_M5, idx), tick.bid) - buffer;
     }
   else
     {
      int idx = iHighest(symbol, PERIOD_M5, MODE_HIGH, lookback, 0);
      if(idx < 0) { Report(id, false, "", price, 0, 0, "Fant ikke 5M-highs for SL", digits); return; }
      sl = MathMax(iHigh(symbol, PERIOD_M5, idx), tick.ask) + buffer;
     }
   sl = NormalizeDouble(sl, digits);

   // Megleren krever en minste avstand; da flyttes SL lenger unna (aldri naermere).
   double minDist = (SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) + 1) * point;
   double dist = buy ? price - sl : sl - price;
   if(dist < minDist)
     {
      dist = minDist;
      sl = NormalizeDouble(buy ? price - dist : price + dist, digits);
     }
   if(maxSlPct > 0 && dist / price * 100.0 > maxSlPct)
     { Report(id, false, "", price, sl, 0, "SKIP: SL er " + DoubleToString(dist / price * 100.0, 2) +
              "% unna (maks " + DoubleToString(maxSlPct, 2) + "%)", digits); return; }
   double tp = NormalizeDouble(buy ? price + rr * dist : price - rr * dist, digits);

   // Lot ut fra fast risiko i USD: tap per lot = avstand / ticksize * tickverdi
   double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0) tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0 || tickValue <= 0)
     { Report(id, false, "", price, sl, tp, "Mangler tickverdi for " + symbol, digits); return; }
   double lossPerLot = dist / tickSize * tickValue;

   if(riskUsd > 0)
     {
      lot = riskUsd / lossPerLot;
      double minLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      if(lot < minLot)
        { Report(id, false, "", price, sl, tp, "SKIP: SL for lang, minste lot gir mer enn " +
                 DoubleToString(riskUsd, 0) + " $ risiko", digits); return; }
     }
   if(maxLot > 0 && lot > maxLot) lot = maxLot;
   lot = NormalizeLot(symbol, lot);
   double risk = lot * lossPerLot;
   string comment = "SMT #" + id;

   bool sent = buy ? trade.Buy(lot, symbol, 0, sl, tp, comment)
                   : trade.Sell(lot, symbol, 0, sl, tp, comment);
   uint rc = trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED || rc == TRADE_RETCODE_DONE_PARTIAL))
     {
      double fill = trade.ResultPrice() > 0 ? trade.ResultPrice() : price;
      double realRisk = MathAbs(fill - sl) / tickSize * tickValue * lot;
      Report(id, true, IntegerToString((long)trade.ResultOrder()), fill, sl, tp, "OK", digits, lot, realRisk);
     }
   else
      Report(id, false, "", price, sl, tp,
             "retcode " + IntegerToString(rc) + " " + trade.ResultRetcodeDescription(), digits, lot, risk);
  }
//+------------------------------------------------------------------+
