# AI Risk Guardian — Reactive Meets AI

An autonomous stop-loss / take-profit guardian for a Uniswap V2 position.
An off-chain AI agent watches the market, decides how much risk is
acceptable, and publishes that decision on-chain. A reactive contract on the
Reactive Network watches both the AI's signals and the pair's price in real
time — and the moment the price crosses the AI-set band (or the AI declares
risk-off), it fires a cross-chain callback that executes the protective swap
on the origin chain. No keeper, no human in the loop.

```
                        publishSignal (dynamic stop band)
   AI agent (Python) ─────────────────────────────► SignalRegistry
        │ polls reserves                                  │ SignalUpdated
        ▼                                                 ▼
   Uniswap V2 pair ─── Sync (price) ───► RiskGuardianReactive (Lasna)
        ▲                                                 │ stop crossed / risk-off
        │ protective swap                                 │ requestCallbackV_1_0
   StopExecutor ◄─────────── callback ──── Reactive Network ┘
   (Base Sepolia)
```

## Why this is "Reactive Meets AI"

The AI is not a demo garnish — it is a running part of the system:

- The reactive contract holds **no hard-coded threshold**. The stop-loss and
  take-profit bands, and the immediate-exit flag, all come from the AI
  agent's on-chain signals (`SignalRegistry.latest`).
- The agent (`agent/agent.py`) polls the pair's reserves, computes features
  (fast/slow momentum, realized volatility, drawdown from peak), and scores
  them with a logistic-regression model that estimates the probability of a
  near-term adverse move. The stop distance is volatility-scaled
  (3× window volatility, clamped to 5–25% below spot); `riskOff` fires when
  the model score ≥ 0.65 or drawdown ≤ −12%.
- If the agent goes silent, signals go stale after 10 minutes and the
  guardian stops acting — the system fails safe, not blind.

## The loop, step by step

1. Agent samples the RISK/STBL pair price on Base Sepolia, computes features
   and a risk score, and calls `SignalRegistry.updateSignal(...)`.
   The event `SignalUpdated` arms the guardian for that signal epoch.
2. `RiskGuardianReactive` (Lasna) is subscribed via `SYSTEM.subscribe` to:
   - `SignalUpdated` from the registry (Base Sepolia),
   - `Sync` from the pair (Base Sepolia),
   - its own `ExecutorSet` event (Lasna) for wiring the executor.
3. On each `Sync`, the guardian recomputes the pair rate and compares it to
   the active band. On a stop cross, take-profit cross, or a `riskOff`
   signal, it calls `SYSTEM.requestCallbackV_1_0` with an
   `executeStop(...)` payload — exactly once per signal epoch.
4. The Reactive Network delivers the callback on Base Sepolia through the
   callback proxy; `StopExecutor.executeStop` (restricted to the proxy,
   authorized by the reactive contract's address in the payload's first
   word) swaps the protected position into the stable token through the real
   Uniswap V2 router.

Built on the current Omni API (`SYSTEM.subscribe`, `react(LogRecord)`,
`requestCallbackV_1_0`, reserve/debt payment via `depositTo`), adapted from
the official Uniswap V2 stop-order pattern.

## Contracts

| Contract | Chain | Role |
|---|---|---|
| `SignalRegistry` | Base Sepolia (84532) | Stores the AI's latest signal; emits `SignalUpdated` |
| `RiskGuardianReactive` | Reactive Lasna (5318007) | Subscribes, watches the band, requests callbacks |
| `StopExecutor` | Base Sepolia (84532) | Callback target; executes the protective swap |
| `TestToken` ×2 | Base Sepolia | RISK and STBL test ERC-20s |

Deployed addresses: see [ADDRESSES.md](ADDRESSES.md).
Proof of the full loop (origin tx → reactive tx → callback tx): see
[TX-HASHES.md](TX-HASHES.md).

## Run it

Prerequisites: Foundry, Python 3 (standard library only), a testnet wallet
key at `~/.keys/reactive-omni.key`, Sepolia ETH in that wallet.

```bash
forge build
forge test                                   # 5/5: full loop against a mock Reactive system contract
python3 script/orchestrate.py all            # fund -> deploy -> prove the loop on-chain
python3 agent/agent.py once                  # one AI decision + on-chain signal
python3 agent/agent.py run 900               # continuous agent (15 min)
```

`script/orchestrate.py` is resumable: every phase records its artifacts in
`deployment.json` and is skipped on re-run.

Funding (all testnet, all free): Sepolia ETH from a public faucet is split
three ways by the orchestrator — converted to lREACT through the official
Reactive faucet contract on Sepolia (1 ETH = 100 lREACT), bridged to Base
Sepolia through the official Base L1 bridge, and used as gas. lREACT funds
the guardian's reserves on Lasna via `depositTo`; a small Base Sepolia
deposit pre-pays the executor's callback reserves so execution never starts
in debt.

## Honest limitations

- The pair is a fresh testnet pair with no organic market history, so the
  model trains on synthetic two-regime price paths (documented in
  `agent/agent.py`). The feature extraction and decision code are identical
  to what a production deployment would run on real history.
- The demo position is 2 RISK against 100/100 test-token liquidity; the
  "crash" that proves the loop is a deliberate 8 RISK market sell.
- One execution per signal epoch by design: after firing, the guardian waits
  for a fresh AI signal before it can act again.

## Layout

```
src/          contracts (SignalRegistry, RiskGuardianReactive, StopExecutor, TestToken)
src/base/     minimal Omni base contracts (AbstractReactive / AbstractCallback / AbstractPayer)
src/interfaces/  IReactive, IReactiveOmni, ICallback, IUniswapV2
test/         Foundry tests incl. an end-to-end loop test with a mock system contract
agent/        the AI agent (agent.py) + a dependency-free Ethereum helper (ethlite.py)
script/       orchestrate.py — funding, deployment and the on-chain proof run
```
