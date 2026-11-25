# Deployed Addresses — AI Risk Guardian

All contracts are on public testnets. No mainnet contract was touched.

## Base Sepolia (chain 84532) — origin + destination

| Contract | Address |
|---|---|
| Wallet (agent / client / deployer) | `0xa340ba1ee95dbd2095f5d7d167ea5e3aad7b0a87` |
| Risk token (RISK, test ERC-20) | `0x2e677237eb44a9bfccbac0bbdf8943cee1a25fdf` |
| Stable token (STBL, test ERC-20) | `0x97c8965c0b91df8ad6f8293ecb49be4a84df528c` |
| Uniswap V2 pair RISK/STBL | `0x4bbEeE2b920138c3a10eA3Acd6CDc847Ef5Ae38B` |
| SignalRegistry | `0xf8677ec8edfa54e155ed4337a85601e092f1f3f0` |
| StopExecutor (callback contract) | `0x13facab2ddcec1168df23f150b4b1a3699351f1f` |
| Uniswap V2 factory | `0x7Ae58f10f7849cA6F5fB71b7f45CB416c9204b1e` |
| Uniswap V2 router | `0x1689E7B1F10000AE47eBfE339a4f69dECd19F602` |
| Reactive callback proxy | `0x476F44b11F5C942c58f4c8E3d0300E5710743585` |

## Reactive Lasna (chain 5318007)

| Contract | Address |
|---|---|
| RiskGuardianReactive | `0xecb4148a02e172e58c0a44fabc9b98cb19470209` |
| System contract | `0x8888888888888888888888888888888888888888` |

Pair token order: risk token is token0 = `True`.
Protected position: 2 RISK, sold into STBL on trigger.
