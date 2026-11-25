#!/usr/bin/env python3
"""End-to-end orchestrator for AI Risk Guardian.

Phases (each is skipped when its artifacts already exist in deployment.json,
so the script is safe to re-run after topping up funds):

  0. check      - print balances on Sepolia / Base Sepolia / Lasna
  1. fund       - Sepolia ETH -> lREACT via the Reactive faucet contract,
                  Sepolia ETH -> Base Sepolia ETH via the Base bridge
  2. base-setup - test tokens, Uniswap V2 pair, liquidity, SignalRegistry
  3. reactive   - RiskGuardianReactive on Lasna + reserves via depositTo
  4. executor   - StopExecutor on Base Sepolia + proxy reserves, approvals,
                  guardian.setExecutor
  5. prove      - agent publishes signal #1, a crash swap moves the price,
                  wait for the reactive trigger and the callback execution,
                  then write ADDRESSES.md / TX-HASHES.md

The private key is read from ~/.keys/reactive-omni.key and only ever passed
to `cast`/`forge` child processes; it is never printed or written anywhere.

Usage: python3 script/orchestrate.py [check|fund|base-setup|reactive|executor|prove|all]
"""

import json
import os
import subprocess
import sys
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP_DIR, "agent"))
from ethlite import Rpc, keccak256, rlp_encode  # noqa: E402

KEY_FILE = os.path.expanduser("~/.keys/reactive-omni.key")
DEPLOYMENT_JSON = os.path.join(APP_DIR, "deployment.json")

SEPOLIA_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
BASE_RPC = "https://sepolia.base.org"
LASNA_RPC = "https://lasna-rpc.rnk.dev/"

SYSTEM = "0x8888888888888888888888888888888888888888"
FAUCET_SEPOLIA = "0x9b9BB25f1A81078C544C829c5EB7822d747Cf434"
BASE_L1_BRIDGE = "0xfd0Bf71F60660E2f608ed56e1659C450eB113120"  # L1StandardBridge, verified on-chain (v2.8.0)
V2_FACTORY = "0x7Ae58f10f7849cA6F5fB71b7f45CB416c9204b1e"      # Uniswap V2 on Base Sepolia (verified on-chain)
V2_ROUTER = "0x1689E7B1F10000AE47eBfE339a4f69dECd19F602"       # Uniswap V2 Router02 on Base Sepolia (verified)
BASE_CALLBACK_PROXY = "0x476F44b11F5C942c58f4c8E3d0300E5710743585"

E18 = 10**18
POSITION_AMOUNT = 2 * E18       # protected position: 2 RISK
LIQUIDITY = 100 * E18           # 100 RISK / 100 STBL initial liquidity
CRASH_AMOUNT = 8 * E18          # market sell that pushes the price through the stop

FOUNDRY_BIN = os.path.expanduser("~/.foundry/bin")
ENV = dict(os.environ, PATH=FOUNDRY_BIN + ":" + os.environ.get("PATH", ""))


def log(msg):
    print(f"[orchestrate] {msg}", flush=True)


def load_key():
    with open(KEY_FILE) as f:
        return f.read().strip()


def load_deployment():
    if os.path.exists(DEPLOYMENT_JSON):
        with open(DEPLOYMENT_JSON) as f:
            return json.load(f)
    return {}


def save_deployment(dep):
    with open(DEPLOYMENT_JSON, "w") as f:
        json.dump(dep, f, indent=2)


def run(cmd, **kw):
    log("+ " + " ".join(cmd[:2]) + " ...")
    out = subprocess.run(cmd, capture_output=True, text=True, env=ENV, **kw)
    if out.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:3])}...\n{out.stdout}\n{out.stderr}")
    return out.stdout


def cast_send(rpc_url, pk, to, signature, *args, value=None):
    cmd = ["cast", "send", to, signature, *args, "--rpc-url", rpc_url, "--private-key", pk, "--json"]
    if value:
        cmd += ["--value", value]
    out = run(cmd)
    receipt = json.loads(out)
    if receipt.get("status") not in ("0x1", 1):
        raise RuntimeError(f"tx failed: {receipt.get('transactionHash')}")
    return receipt["transactionHash"]


def cast_call(rpc_url, to, signature, *args):
    out = run(["cast", "call", to, signature, *args, "--rpc-url", rpc_url])
    return out.strip()


def balance(rpc_url, address):
    return Rpc(rpc_url).call("eth_getBalance", [address, "latest"])


def balance_eth(rpc_url, address):
    return int(balance(rpc_url, address), 16) / E18


def contract_address(sender, nonce):
    digest = keccak256(rlp_encode([bytes.fromhex(sender[2:]), nonce]))
    return "0x" + digest[-20:].hex()


def forge_create(rpc_url, pk, contract, *args, value=None):
    rpc = Rpc(rpc_url)
    # Predict the address from the pending nonce so we don't parse stdout.
    from ethlite import privkey_to_address

    sender = privkey_to_address(bytes.fromhex(pk.removeprefix("0x")))
    nonce = rpc.get_transaction_count(sender)
    predicted = contract_address(sender, nonce)
    cmd = [
        "forge", "create", "--broadcast", "--rpc-url", rpc_url, "--private-key", pk,
        f"src/{contract}.sol:{contract}", "--json",
    ]
    if value:
        cmd += ["--value", value]
    if args:
        cmd += ["--constructor-args", *args]
    run(cmd, cwd=APP_DIR)
    code = rpc.call("eth_getCode", [predicted, "latest"])
    if code in ("0x", "0x0"):
        raise RuntimeError(f"deployment not found at predicted address {predicted}")
    log(f"deployed {contract} at {predicted}")
    return predicted


# ------------------------------------------------------------------ phases

def phase_check(dep, pk):
    from ethlite import privkey_to_address

    wallet = privkey_to_address(bytes.fromhex(pk.removeprefix("0x")))
    dep["wallet"] = wallet
    log(f"wallet {wallet}")
    log(f"Sepolia ETH:      {balance_eth(SEPOLIA_RPC, wallet):.6f}")
    log(f"Base Sepolia ETH: {balance_eth(BASE_RPC, wallet):.6f}")
    log(f"Lasna lREACT:     {balance_eth(LASNA_RPC, wallet):.6f}")
    save_deployment(dep)
    return dep


def phase_fund(dep, pk):
    wallet = dep["wallet"]
    sepolia = balance_eth(SEPOLIA_RPC, wallet)
    lreact = balance_eth(LASNA_RPC, wallet)
    base = balance_eth(BASE_RPC, wallet)

    if lreact < 2.0:
        if sepolia < 0.03:
            raise RuntimeError(
                f"need >= 0.03 Sepolia ETH to fund (have {sepolia:.4f}); top up {wallet} first"
            )
        amount = min(0.04, sepolia * 0.5)
        log(f"converting {amount} Sepolia ETH -> {amount * 100} lREACT via faucet")
        tx = cast_send(SEPOLIA_RPC, pk, FAUCET_SEPOLIA, "request(address)", wallet, value=f"{amount}ether")
        log(f"faucet tx {tx}")
        dep["faucetTx"] = tx
        for _ in range(60):
            if balance_eth(LASNA_RPC, wallet) >= lreact + amount * 99:
                break
            time.sleep(5)
        log(f"Lasna lREACT now {balance_eth(LASNA_RPC, wallet):.4f}")

    if balance_eth(BASE_RPC, wallet) < 0.008:
        sepolia = balance_eth(SEPOLIA_RPC, wallet)
        amount = min(0.015, max(0.0, sepolia - 0.004))
        if amount < 0.008:
            raise RuntimeError(f"not enough Sepolia ETH left to bridge (have {sepolia:.4f})")
        log(f"bridging {amount} ETH Sepolia -> Base Sepolia")
        tx = cast_send(
            SEPOLIA_RPC, pk, BASE_L1_BRIDGE, "bridgeETH(uint32,bytes)", "200000", "0x",
            value=f"{amount}ether",
        )
        log(f"bridge tx {tx}")
        dep["bridgeTx"] = tx
        for _ in range(120):
            if balance_eth(BASE_RPC, wallet) >= base + amount * 0.99:
                break
            time.sleep(10)
        log(f"Base Sepolia ETH now {balance_eth(BASE_RPC, wallet):.4f}")
    save_deployment(dep)
    return dep


def phase_base_setup(dep, pk):
    wallet = dep["wallet"]
    if "riskToken" not in dep:
        dep["riskToken"] = forge_create(BASE_RPC, pk, "TestToken", "Risk Token", "RISK", str(1_000_000 * E18))
    if "stableToken" not in dep:
        dep["stableToken"] = forge_create(BASE_RPC, pk, "TestToken", "Stable Token", "STBL", str(1_000_000 * E18))
    risk, stable = dep["riskToken"], dep["stableToken"]

    if "pair" not in dep:
        existing = cast_call(BASE_RPC, V2_FACTORY, "getPair(address,address)(address)", risk, stable)
        if existing.lower() == "0x0000000000000000000000000000000000000000":
            tx = cast_send(BASE_RPC, pk, V2_FACTORY, "createPair(address,address)", risk, stable)
            log(f"createPair tx {tx}")
            dep["createPairTx"] = tx
            existing = cast_call(BASE_RPC, V2_FACTORY, "getPair(address,address)(address)", risk, stable)
        dep["pair"] = existing
        token0 = cast_call(BASE_RPC, existing, "token0()(address)")
        dep["riskIsToken0"] = token0.lower() == risk.lower()
        log(f"pair {existing}; riskIsToken0={dep['riskIsToken0']}")

    if not dep.get("liquidityAdded"):
        deadline = str(int(time.time()) + 1200)
        for token in (risk, stable):
            cast_send(BASE_RPC, pk, token, "approve(address,uint256)", V2_ROUTER, str(1000 * E18))
        tx = cast_send(
            BASE_RPC, pk, V2_ROUTER,
            "addLiquidity(address,address,uint256,uint256,uint256,uint256,address,uint256)",
            risk, stable, str(LIQUIDITY), str(LIQUIDITY), "0", "0", wallet, deadline,
        )
        dep["addLiquidityTx"] = tx
        dep["liquidityAdded"] = True
        log(f"liquidity added tx {tx}")

    if "signalRegistry" not in dep:
        dep["signalRegistry"] = forge_create(BASE_RPC, pk, "SignalRegistry", wallet)
    save_deployment(dep)
    return dep


def phase_reactive(dep, pk):
    if "reactive" not in dep:
        dep["reactive"] = forge_create(
            LASNA_RPC, pk, "RiskGuardianReactive",
            dep["signalRegistry"], dep["pair"], dep["wallet"], str(POSITION_AMOUNT),
            "true" if dep["riskIsToken0"] else "false",
            value="0.3ether",
        )
        # Pre-pay execution reserves so the guardian never starts in debt.
        tx = cast_send(LASNA_RPC, pk, SYSTEM, "depositTo(address)", dep["reactive"], value="1.2ether")
        dep["reactiveDepositTx"] = tx
        log(f"guardian reserves funded tx {tx}")
    save_deployment(dep)
    return dep


def phase_executor(dep, pk):
    if "executor" not in dep:
        dep["executor"] = forge_create(
            BASE_RPC, pk, "StopExecutor",
            BASE_CALLBACK_PROXY, dep["reactive"], V2_ROUTER, dep["pair"],
            dep["riskToken"], dep["stableToken"],
            value="0.002ether",
        )
        tx = cast_send(BASE_RPC, pk, BASE_CALLBACK_PROXY, "depositTo(address)", dep["executor"], value="0.01ether")
        dep["executorDepositTx"] = tx
        log(f"executor reserves funded tx {tx}")
    if not dep.get("executorApproved"):
        tx = cast_send(BASE_RPC, pk, dep["riskToken"], "approve(address,uint256)", dep["executor"], str(10 * E18))
        dep["approveExecutorTx"] = tx
        dep["executorApproved"] = True
    if not dep.get("executorWired"):
        tx = cast_send(LASNA_RPC, pk, dep["reactive"], "setExecutor(address)", dep["executor"])
        dep["setExecutorTx"] = tx
        dep["executorWired"] = True
    save_deployment(dep)
    return dep


def _find_log(rpc_url, address, topic0, from_block, timeout_s=300):
    rpc = Rpc(rpc_url)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        latest = int(rpc.call("eth_blockNumber", []), 16)
        logs = rpc.call(
            "eth_getLogs",
            [{"fromBlock": hex(from_block), "toBlock": hex(latest), "address": address, "topics": [topic0]}],
        )
        if logs:
            return logs[0]
        time.sleep(6)
    raise TimeoutError(f"log {topic0} from {address} not found within {timeout_s}s")


def phase_prove(dep, pk):
    base = Rpc(BASE_RPC)
    lasna = Rpc(LASNA_RPC)
    base_block = int(base.call("eth_blockNumber", []), 16)
    lasna_block = int(lasna.call("eth_blockNumber", []), 16)

    # 1) The AI agent publishes its first signal (arms the guardian).
    if "signalTx1" not in dep:
        out = subprocess.run(
            [sys.executable, os.path.join(APP_DIR, "agent", "agent.py"), "once"],
            capture_output=True, text=True, env=dict(os.environ),
        )
        print(out.stdout)
        if out.returncode != 0:
            raise RuntimeError(f"agent failed:\n{out.stderr}")
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                dep["signalTx1"] = json.loads(line)["tx"]
        log(f"signal #1 tx {dep['signalTx1']}")

    # 2) Crash the price through the stop with a market sell.
    if "crashTx" not in dep:
        deadline = str(int(time.time()) + 1200)
        cast_send(BASE_RPC, pk, dep["riskToken"], "approve(address,uint256)", V2_ROUTER, str(100 * E18))
        tx = cast_send(
            BASE_RPC, pk, V2_ROUTER,
            "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
            str(CRASH_AMOUNT), "0", f"[{dep['riskToken']},{dep['stableToken']}]", dep["wallet"], deadline,
        )
        dep["crashTx"] = tx
        log(f"crash swap tx {tx}")

    # 3) Wait for the callback execution on Base Sepolia.
    executed_topic = "0x" + keccak256(b"StopExecuted(address,address,uint256,uint256)").hex()
    log("waiting for StopExecuted (the callback transaction)...")
    exec_log = _find_log(BASE_RPC, dep["executor"], executed_topic, base_block, timeout_s=420)
    dep["callbackTx"] = exec_log["transactionHash"]
    log(f"callback tx {dep['callbackTx']}")

    # 4) Find the reactive transaction on Lasna that requested it.
    triggered_topic = "0x" + keccak256(b"Triggered(uint256,uint256,uint256,bool)").hex()
    log("waiting for Triggered on Lasna...")
    trig_log = _find_log(LASNA_RPC, dep["reactive"], triggered_topic, lasna_block, timeout_s=120)
    dep["reactiveTx"] = trig_log["transactionHash"]
    log(f"reactive tx {dep['reactiveTx']}")

    save_deployment(dep)
    write_docs(dep)
    return dep


def write_docs(dep):
    b = "https://sepolia.basescan.org"
    l = "https://lasna.reactscan.net"
    addresses = f"""# Deployed Addresses — AI Risk Guardian

All contracts are on public testnets. No mainnet contract was touched.

## Base Sepolia (chain 84532) — origin + destination

| Contract | Address |
|---|---|
| Wallet (agent / client / deployer) | `{dep['wallet']}` |
| Risk token (RISK, test ERC-20) | `{dep['riskToken']}` |
| Stable token (STBL, test ERC-20) | `{dep['stableToken']}` |
| Uniswap V2 pair RISK/STBL | `{dep['pair']}` |
| SignalRegistry | `{dep['signalRegistry']}` |
| StopExecutor (callback contract) | `{dep.get('executor', '—')}` |
| Uniswap V2 factory | `{V2_FACTORY}` |
| Uniswap V2 router | `{V2_ROUTER}` |
| Reactive callback proxy | `{BASE_CALLBACK_PROXY}` |

## Reactive Lasna (chain 5318007)

| Contract | Address |
|---|---|
| RiskGuardianReactive | `{dep.get('reactive', '—')}` |
| System contract | `{SYSTEM}` |

Pair token order: risk token is token0 = `{dep.get('riskIsToken0')}`.
Protected position: 2 RISK, sold into STBL on trigger.
"""
    hashes = f"""# Transaction Hashes — the full reactive loop

One complete, verified run of the guardian loop (Base Sepolia -> Lasna -> Base Sepolia):

| Step | What | Transaction |
|---|---|---|
| 1 | AI agent publishes signal #1 (arms guardian with dynamic stop band) | [{dep.get('signalTx1', '—')}]({b}/tx/{dep.get('signalTx1', '')}) |
| 2 | Market sell (8 RISK) crashes the pair price through the AI-set stop | [{dep.get('crashTx', '—')}]({b}/tx/{dep.get('crashTx', '')}) |
| 3 | Reactive transaction on Lasna: guardian sees the Sync, emits Triggered, requests callback | [{dep.get('reactiveTx', '—')}]({l}/tx/{dep.get('reactiveTx', '')}) |
| 4 | Callback transaction on Base Sepolia: StopExecutor sells the protected 2 RISK into STBL | [{dep.get('callbackTx', '—')}]({b}/tx/{dep.get('callbackTx', '')}) |

Supporting transactions:

| What | Transaction |
|---|---|
| Sepolia ETH -> lREACT faucet conversion | {dep.get('faucetTx', '—')} |
| Sepolia -> Base Sepolia bridge deposit | {dep.get('bridgeTx', '—')} |
| Pair creation | {dep.get('createPairTx', '—')} |
| Liquidity added (100 RISK / 100 STBL) | {dep.get('addLiquidityTx', '—')} |
| Guardian reserves (depositTo on Lasna) | {dep.get('reactiveDepositTx', '—')} |
| Executor reserves (depositTo via Base Sepolia proxy) | {dep.get('executorDepositTx', '—')} |
| Client approves StopExecutor | {dep.get('approveExecutorTx', '—')} |
| Guardian wired to executor (setExecutor) | {dep.get('setExecutorTx', '—')} |
"""
    with open(os.path.join(APP_DIR, "ADDRESSES.md"), "w") as f:
        f.write(addresses)
    with open(os.path.join(APP_DIR, "TX-HASHES.md"), "w") as f:
        f.write(hashes)
    log("ADDRESSES.md and TX-HASHES.md written")


PHASES = {
    "check": phase_check,
    "fund": phase_fund,
    "base-setup": phase_base_setup,
    "reactive": phase_reactive,
    "executor": phase_executor,
    "prove": phase_prove,
}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    pk = load_key()
    dep = load_deployment()
    run(["forge", "build"], cwd=APP_DIR)
    order = ["check", "fund", "base-setup", "reactive", "executor", "prove"] if which == "all" else [which]
    for name in order:
        log(f"=== phase: {name} ===")
        dep = PHASES[name](dep, pk)
    log("done")


if __name__ == "__main__":
    main()
