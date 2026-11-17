# Dip-buy cbBTC race bot

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/smrfkeenam-hue/makefun-btc-race-24h/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/smrfkeenam-hue/makefun-btc-race-24h/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

Entry for [make.fun `btc-race-24h-20261117-0603`](https://make.fun/bounty/btc-race-24h-20261117-0603) — race a BTC trading bot
live for 24 hours. Simulation only: paper money against real on-chain
cbBTC/USDC prices from the Orca Whirlpool, no real money traded.

## Strategy

Trade rarely, only on high-conviction dips. A full-size round trip pays
~26–35 bps in fee (4 bps), slippage (2 bps) and price impact, so every
trade has to clear that bar — the bot makes 5 fills on the dev window.

- **Buy** the whole cash balance when the close dips 0.5% below its
  trailing 120-bar SMA, the last two closes are non-falling (the dip has
  stabilised), and the 120-bar return is above −1% (no strong downtrend:
  never buy a dip in a crash).
- **Sell** everything at +1.5% over the cost basis (take profit) or at
  −1.5% under it (stop loss).
- **Circuit breaker**: after the first stop-loss fill, stop trading for
  the rest of the window. One losing round trip caps a bad day at ~$17.
- **No new entries** during the first 242 bars (indicator warm-up) or
  after bar 1410 (no time left for a round trip to pay).
- **Fallback**: if no trade has filled by bar 1200, buy half the cash
  once (same regime filter, same TP/SL). A day that never dips 0.5%
  below its SMA is a day that rose — without this, a roaring bull day
  could end with zero trades and rank below every entry that met the
  bar.

Long only, no leverage, no shorts. Deterministic: a pure function of the
bars and fills — no clock, no network, no randomness, no files. All
comparisons are integer math on the protocol's price-scale units.

## Results (kit `grade-local`, exact replay)

| Window | Net PnL | Trades | Max drawdown |
|---|---|---|---|
| Dev window (2026-11-16 06:03 → 2026-11-17 06:03 UTC) | **+$22.24** | 5 | 1.32% |

Out-of-sample check on six Yahoo BTC-USD 1-minute 24h windows
(Nov 11–16, same cost model, same bot run through the protocol):
mean +$3.79/day, worst day −$17.24 (one stop-loss, then the circuit
breaker stops trading), max drawdown 2.53% on any window. For comparison,
buy-and-hold lost −$38 to −$65 on the three crash days in that set, and
the kit's EMA-cross baseline loses −$106.22 on the dev window.

## Layout

- `main.py` — the bot (Python 3.13, standard library only). Speaks
  `agent-fun/bars-replay/v1` on stdin/stdout.
- `vendor/makefun_bars.py` — byte-identical copy of the kit's Python SDK
  shim (`sdk/makefun_bars.py`).
- `LICENSE` — MIT.
