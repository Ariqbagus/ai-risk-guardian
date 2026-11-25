// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { IReactive } from "../src/interfaces/IReactive.sol";
import { RiskGuardianReactive } from "../src/RiskGuardianReactive.sol";
import { SignalRegistry } from "../src/SignalRegistry.sol";

/// @notice Minimal cheatcode surface (avoids a forge-std dependency for these tests).
interface CheatCodes {
    function prank(address) external;
    function etch(address, bytes calldata) external;
}

/// @notice Stand-in for the Reactive system contract, etched at 0x8888...8888 so
///         high-level calls from the guardian find code there, as on Lasna.
contract MockSystem {
    uint256 public subscribeCount;
    uint256 public callbackCount;
    uint256 public lastCallbackChainId;
    address public lastCallbackRecipient;

    function subscribe(uint256, address, uint256, uint256, uint256, uint256) external {
        subscribeCount += 1;
    }

    function unsubscribe(uint256, address, uint256, uint256, uint256, uint256) external {}

    struct CbConfig {
        uint256 chainId;
        address recipient;
        uint64 gasLimit;
        bytes payload;
    }

    function requestCallbackV_1_0(CbConfig memory config_) external {
        callbackCount += 1;
        lastCallbackChainId = config_.chainId;
        lastCallbackRecipient = config_.recipient;
    }

    function debt(address) external pure returns (uint256) {
        return 0;
    }

    function reserves(address) external pure returns (uint256) {
        return 0;
    }

    function depositTo(address) external payable {}
}

/// @notice Local logic tests for the guardian's react() routing. On a local EVM the
///         system contract address (0x8888...8888) holds no code, so subscribe /
///         requestCallback calls succeed silently and only the state machine runs.
contract GuardianTest {
    CheatCodes constant VM = CheatCodes(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);
    address constant SYSTEM = 0x8888888888888888888888888888888888888888;

    uint256 constant SIGNAL_TOPIC0 =
        uint256(keccak256("SignalUpdated(uint256,bool,uint256,uint256,int256,uint256)"));
    uint256 constant SYNC_TOPIC0 = uint256(keccak256("Sync(uint112,uint112)"));

    address constant REGISTRY = address(0x1001);
    address constant PAIR = address(0x1002);
    address constant CLIENT = address(0x1003);
    address constant EXECUTOR = address(0x1004);

    function _deploy() internal returns (RiskGuardianReactive g) {
        MockSystem mock = new MockSystem();
        VM.etch(SYSTEM, address(mock).code);
        // The test contract deploys the guardian, so it is the owner.
        g = new RiskGuardianReactive(REGISTRY, PAIR, CLIENT, 2 ether, true);
        g.setExecutor(EXECUTOR);
    }

    function _signalLog(bool riskOff, uint256 stop, uint256 tp) internal pure returns (IReactive.LogRecord memory log) {
        log = IReactive.LogRecord({
            chainId: 84532,
            contractAddress: REGISTRY,
            topic0: SIGNAL_TOPIC0,
            topic1: 1,
            topic2: 0,
            topic3: 0,
            data: abi.encode(riskOff, stop, tp, int256(5000), uint256(1700000000)),
            blockNumber: 1,
            opCode: 2,
            blockHash: 0,
            txHash: 0,
            logIndex: 0
        });
    }

    function _syncLog(uint112 r0, uint112 r1) internal pure returns (IReactive.LogRecord memory log) {
        log = IReactive.LogRecord({
            chainId: 84532,
            contractAddress: PAIR,
            topic0: SYNC_TOPIC0,
            topic1: 0,
            topic2: 0,
            topic3: 0,
            data: abi.encode(r0, r1),
            blockNumber: 2,
            opCode: 1,
            blockHash: 0,
            txHash: 0,
            logIndex: 0
        });
    }

    function testStopLossTriggersOnSyncCross() public {
        RiskGuardianReactive g = _deploy();

        VM.prank(SYSTEM);
        g.react(_signalLog(false, 0.9 ether, 1.2 ether));
        require(g.armed() && !g.executed(), "armed after signal");

        // Rate 1.0: no trigger.
        VM.prank(SYSTEM);
        g.react(_syncLog(100 ether, 100 ether));
        require(!g.executed(), "no trigger at rate 1.0");
        require(g.lastRateX1e18() == 1 ether, "rate tracked");

        // Rate 92/108 = 0.8518...: below the 0.9 stop -> trigger.
        VM.prank(SYSTEM);
        g.react(_syncLog(108 ether, 92 ether));
        require(g.executed(), "triggered below stop");
        require(MockSystem(SYSTEM).callbackCount() == 1, "exactly one callback requested");
        require(MockSystem(SYSTEM).lastCallbackRecipient() == EXECUTOR, "callback targets executor");
    }

    function testRiskOffTriggersImmediately() public {
        RiskGuardianReactive g = _deploy();
        VM.prank(SYSTEM);
        g.react(_signalLog(true, 0.9 ether, 1.2 ether));
        require(g.executed(), "risk-off executes at once");
    }

    function testTakeProfitTriggers() public {
        RiskGuardianReactive g = _deploy();
        VM.prank(SYSTEM);
        g.react(_signalLog(false, 0.9 ether, 1.2 ether));
        // Rate 130/100 = 1.3 >= 1.2 take-profit.
        VM.prank(SYSTEM);
        g.react(_syncLog(100 ether, 130 ether));
        require(g.executed(), "take-profit triggered");
    }

    function testReactRejectsNonSystemCaller() public {
        RiskGuardianReactive g = _deploy();
        (bool ok,) = address(g).call(abi.encodeWithSignature("react((uint256,address,uint256,uint256,uint256,uint256,bytes,uint256,uint256,uint256,uint256,uint256))", _signalLog(false, 1, 1)));
        require(!ok, "react must reject non-system callers");
    }

    function testRegistryOnlyAgentPublishes() public {
        SignalRegistry reg = new SignalRegistry(address(this));
        reg.updateSignal(false, 1, 2, 3);
        require(reg.epoch() == 1, "epoch increments");
        (bool ok,) = address(reg).call(
            abi.encodeWithSignature("updateSignal(bool,uint256,uint256,int256)", true, 1, 2, 3)
        );
        // Caller here IS the agent (this contract), so use a fresh registry with a different agent.
        require(ok, "agent call should succeed");
        SignalRegistry reg2 = new SignalRegistry(address(0xBEEF));
        (bool ok2,) = address(reg2).call(
            abi.encodeWithSignature("updateSignal(bool,uint256,uint256,int256)", true, 1, 2, 3)
        );
        require(!ok2, "non-agent must be rejected");
    }
}
