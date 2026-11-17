"""Dip-buy mean-reversion bot for cbBTC (make.fun btc-race-24h-20261117-0603).

Strategy (backtested on the kit's dev window + 6 Yahoo BTC-USD 1m days):
  - Buy the whole cash balance when the close dips 0.5% below its trailing
    120-bar simple moving average, the last two closes are non-falling
    (the dip has stabilised), and the 120-bar return is above -1%
    (no strong downtrend: never buy a dip in a crash).
  - Sell everything at +1.5% over the cost basis (take profit) or at -1.5%
    under it (stop loss).
  - Circuit breaker: after the first stop-loss fill, stop trading for the
    rest of the window. One losing round trip caps a bad day at ~$17.
  - No new entries during the first 242 bars (indicator warm-up) or after
    bar 1410 (no time left for a round trip to pay).

Costs matter: a full-size round trip pays ~26-35 bps in fee, slippage and
price impact, so the bot trades rarely (5 fills on the dev window) and only
on a dip deep enough to clear that bar. Long only, no leverage, no shorts.

Protocol: agent-fun/bars-replay/v1 via the vendored kit shim
(vendor/makefun_bars.py, byte-identical to the kit's sdk/makefun_bars.py).
Deterministic: pure function of the bars and fills, no clock, no network,
no randomness, no files.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy parameters (all in basis points where a percent applies) ---
MEAN_SPAN = 120          # trailing SMA window (bars)
DIP_BPS = 50             # buy when close is this far below the SMA
TP_BPS = 150             # take profit above the cost basis
SL_BPS = 150             # stop loss below the cost basis
STAB_BARS = 2            # require this many last closes non-falling to buy
RET_BARS = 120           # lookback for the regime filter
RET_MIN_BPS = -100       # regime filter: 120-bar return must exceed this
WARMUP_BARS = 242        # bars of history before the first entry
LAST_ENTRY_BAR = 1410    # no new entries at/after this bar index
FALLBACK_BAR = 1200      # if still no trade by here, buy once (see below)
FALLBACK_SIZE_BPS = 5000  # ... with half the cash: a strong uptrend has no
# 0.5% dips below its SMA, so without this the bot could end a roaring
# bull day with zero trades and rank below every entry that met the bar.
# The fallback fires only when the dip rules stayed silent all day; it
# still respects the regime filter and the same TP/SL exits.
BUY_SLIP_BPS = 100       # max slippage vs the decision close, buys
SELL_SLIP_BPS = 200      # max slippage vs the decision close, sells

BPS = 10_000


class Bot:
    def __init__(self):
        self.closes = []        # every close seen, price-scale ints
        self.window = []        # last MEAN_SPAN closes, for the SMA
        self.window_sum = 0     # their sum (rolling SMA)
        self.bar_count = 0      # bars answered so far
        self.stopped_out = False  # circuit breaker: a stop-loss fill happened
        self.traded = False     # a buy of ours has filled (fallback gate)
        self.order_no = 0       # for unique client ids

    def _next_id(self, prefix):
        self.order_no += 1
        return "%s%d" % (prefix, self.order_no)

    def on_batch(self, state, batch):
        # Fold the fills of the previous reply in first: a filled stop-loss
        # sell trips the circuit breaker.
        for fill in batch.get("fills", []):
            if fill.get("status") != "filled":
                continue
            if fill.get("side") == "buy":
                self.traded = True
            elif (fill.get("side") == "sell"
                    and str(fill.get("client_id", "")).startswith("sl")):
                self.stopped_out = True

        bar = None
        for b in batch.get("bars", []):
            if b.get("symbol") == SYMBOL:
                bar = b
                break
        if bar is None:
            return []  # no bar for our symbol this minute: no decision
        close = int(bar["c"])
        self.closes.append(close)
        self.window.append(close)
        self.window_sum += close
        if len(self.window) > MEAN_SPAN:
            self.window_sum -= self.window.pop(0)
        self.bar_count += 1

        held = state.positions.get(SYMBOL)
        if held is not None and held.qty > 0:
            return self._exit(state, held, close)
        return self._entry(state, close)

    def _entry(self, state, close):
        if self.stopped_out:
            return []
        if self.bar_count <= WARMUP_BARS:
            return []
        if self.bar_count > LAST_ENTRY_BAR:
            return []
        if len(self.window) < MEAN_SPAN:
            return []
        # Fallback: no trade yet and the window is nearly over. A day that
        # never dipped is a day that rose; buy half the cash and let the
        # usual TP/SL exits manage it. Only once, only in a healthy regime.
        if not self.traded and self.bar_count >= FALLBACK_BAR:
            if len(self.closes) > RET_BARS:
                ref = self.closes[-1 - RET_BARS]
                if close * BPS >= ref * (BPS + RET_MIN_BPS):
                    cash = state.cash * FALLBACK_SIZE_BPS // BPS
                    if cash > 0:
                        return [{"side": "buy", "client_id": self._next_id("b"),
                                 "symbol": SYMBOL, "notional_quote_units": cash,
                                 "max_slippage_bps": BUY_SLIP_BPS}]
            return []
        # Dip: close at least DIP_BPS below the trailing SMA.
        # Pure-integer form of close < (window_sum / MEAN_SPAN) * (BPS - DIP_BPS) / BPS.
        if close * BPS * MEAN_SPAN >= self.window_sum * (BPS - DIP_BPS):
            return []
        # Regime: the 120-bar return must beat RET_MIN_BPS.
        if len(self.closes) <= RET_BARS:
            return []
        ref = self.closes[-1 - RET_BARS]
        if close * BPS < ref * (BPS + RET_MIN_BPS):
            return []
        # Stabilisation: the last STAB_BARS closes non-falling.
        for j in range(STAB_BARS):
            if self.closes[-1 - j] < self.closes[-2 - j]:
                return []
        cash = state.cash
        if cash <= 0:
            return []
        return [{"side": "buy", "client_id": self._next_id("b"),
                 "symbol": SYMBOL, "notional_quote_units": cash,
                 "max_slippage_bps": BUY_SLIP_BPS}]

    def _exit(self, state, held, close):
        # Cost basis as a price-scale int: cost / qty, in the protocol's units.
        # value = qty * price * 10**quote_scale // 10**(qty_scale + price_scale),
        # so price = cost * 10**(qty_scale + price_scale) // (qty * 10**quote_scale).
        sym = state.symbols[SYMBOL]
        entry = (held.cost * 10 ** (sym["qty_scale"] + sym["price_scale"])
                 // (held.qty * 10 ** state.hello["capital"]["quote_scale"]))
        if close * BPS <= entry * (BPS - SL_BPS):
            return [{"side": "sell", "client_id": self._next_id("sl"),
                     "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": SELL_SLIP_BPS}]
        if close * BPS >= entry * (BPS + TP_BPS):
            return [{"side": "sell", "client_id": self._next_id("tp"),
                     "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": SELL_SLIP_BPS}]
        return []


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
