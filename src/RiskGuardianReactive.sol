// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { ISystemContract } from "./interfaces/ISystemContract.sol";
import { IReactive } from "./interfaces/IReactive.sol";
import { AbstractReactive } from "./base/AbstractReactive.sol";

/// @title RiskGuardianReactive — the reactive contract on Reactive Lasna.
/// @notice Watches two event streams on Base Sepolia (chain 84532):
///           1. `SignalUpdated` from the SignalRegistry — the AI agent's regime
///              call, carrying a dynamic stop-loss / take-profit band. Each new
///              signal (epoch) re-arms the guardian.
///           2. `Sync` from the Uniswap V2 pair — every swap moves the reserves;
///              the guardian recomputes the exchange rate and, if it crosses the
///              AI-set band (or the AI declared risk-off), requests a callback.
///         The callback targets StopExecutor on Base Sepolia, which sells the
///         protected position into the stable token. The guardian also watches
///         for the executor's `StopExecuted` confirmation and disarms.
contract RiskGuardianReactive is AbstractReactive {
    uint256 public constant ORIGIN_CHAIN_ID = 84532; // Base Sepolia
    uint64 private constant CALLBACK_GAS_LIMIT = 1000000;
    uint256 private constant SLIPPAGE_TOLERANCE_PERCENT = 75; // minOut = 75% of expected

    uint256 private constant SIGNAL_TOPIC0 =
        uint256(keccak256("SignalUpdated(uint256,bool,uint256,uint256,int256,uint256)"));
    uint256 private constant SYNC_TOPIC0 =
        uint256(keccak256("Sync(uint112,uint112)"));
    uint256 private constant EXECUTED_TOPIC0 =
        uint256(keccak256("StopExecuted(address,address,uint256,uint256)"));

    address public immutable owner;
    address public immutable signalRegistry;
    address public immutable pair;
    address public immutable client;       // position owner on Base Sepolia
    uint256 public immutable positionAmount; // risk-token amount sold on trigger
    bool public immutable riskIsToken0;    // pair token ordering

    address public executor; // set after the executor is deployed

    // Latest AI signal state.
    uint256 public lastEpoch;
    bool public riskOff;
    uint256 public stopRateX1e18;
    uint256 public takeProfitRateX1e18;
    bool public armed;
    bool public executed;

    // Last exchange rate observed from the pair (stable per risk token, x1e18).
    uint256 public lastRateX1e18;

    event ExecutorSet(address indexed executor);
    event SignalSeen(
        uint256 indexed epoch, bool riskOff, uint256 stopRateX1e18, uint256 takeProfitRateX1e18, int256 scoreX1e4
    );
    event Triggered(uint256 indexed epoch, uint256 rateX1e18, uint256 triggerRateX1e18, bool isStopLoss);
    event GuardianDone(uint256 indexed epoch, uint256 amountIn, uint256 amountOut);

    constructor(
        address signalRegistry_,
        address pair_,
        address client_,
        uint256 positionAmount_,
        bool riskIsToken0_
    ) payable {
        owner = msg.sender;
        signalRegistry = signalRegistry_;
        pair = pair_;
        client = client_;
        positionAmount = positionAmount_;
        riskIsToken0 = riskIsToken0_;

        SYSTEM.subscribe(ORIGIN_CHAIN_ID, signalRegistry, SIGNAL_TOPIC0, REACTIVE_IGNORE, REACTIVE_IGNORE, REACTIVE_IGNORE);
        SYSTEM.subscribe(ORIGIN_CHAIN_ID, pair, SYNC_TOPIC0, REACTIVE_IGNORE, REACTIVE_IGNORE, REACTIVE_IGNORE);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    /// @notice Wires the callback recipient and starts watching its confirmations.
    /// @dev Deployment order per the Reactive docs: reactive contract first, then
    ///      the callback contract (which immutably stores this contract's address),
    ///      then this setter.
    function setExecutor(address executor_) external onlyOwner {
        require(executor_ != address(0), "zero executor");
        executor = executor_;
        SYSTEM.subscribe(ORIGIN_CHAIN_ID, executor_, EXECUTED_TOPIC0, REACTIVE_IGNORE, REACTIVE_IGNORE, REACTIVE_IGNORE);
        emit ExecutorSet(executor_);
    }

    /// @notice Settles outstanding debt from this contract's balance.
    function coverDebt() external {
        _coverDebt();
    }

    /// @inheritdoc IReactive
    function react(LogRecord memory log_) external onlySystem {
        if (log_.topic0 == SIGNAL_TOPIC0 && log_.contractAddress == signalRegistry) {
            _onSignal(log_);
        } else if (log_.topic0 == SYNC_TOPIC0 && log_.contractAddress == pair) {
            _onSync(log_);
        } else if (log_.topic0 == EXECUTED_TOPIC0 && log_.contractAddress == executor) {
            _onExecuted(log_);
        }
        // Non-matching logs fall through silently: reverting would still be billed.
    }

    function _onSignal(LogRecord memory log_) internal {
        (bool ro, uint256 stop, uint256 tp, int256 score,) =
            abi.decode(log_.data, (bool, uint256, uint256, int256, uint256));
        lastEpoch = log_.topic1;
        riskOff = ro;
        stopRateX1e18 = stop;
        takeProfitRateX1e18 = tp;
        armed = true;
        executed = false;
        emit SignalSeen(log_.topic1, ro, stop, tp, score);
        if (ro) {
            // The model demands an immediate defensive exit.
            _tryExecute(lastRateX1e18, stop, true);
        }
    }

    function _onSync(LogRecord memory log_) internal {
        (uint256 reserve0, uint256 reserve1) = abi.decode(log_.data, (uint256, uint256));
        if (reserve0 == 0 || reserve1 == 0) return;
        uint256 rate = riskIsToken0
            ? (reserve1 * 1e18) / reserve0
            : (reserve0 * 1e18) / reserve1;
        lastRateX1e18 = rate;
        if (!armed || executed) return;
        if (rate <= stopRateX1e18) {
            _tryExecute(rate, stopRateX1e18, true);
        } else if (takeProfitRateX1e18 > 0 && rate >= takeProfitRateX1e18) {
            _tryExecute(rate, takeProfitRateX1e18, false);
        }
    }

    function _onExecuted(LogRecord memory log_) internal {
        (uint256 amountIn, uint256 amountOut) = abi.decode(log_.data, (uint256, uint256));
        armed = false;
        emit GuardianDone(lastEpoch, amountIn, amountOut);
    }

    /// @notice Requests the execution callback exactly once per signal epoch.
    /// @param rateRef_ Best known current rate (0 if none observed yet).
    /// @param triggerRate_ The band edge that fired, used for the event and minOut.
    /// @param isStopLoss_ True for stop-loss / risk-off exits, false for take-profit.
    function _tryExecute(uint256 rateRef_, uint256 triggerRate_, bool isStopLoss_) internal {
        if (executed || executor == address(0)) return;
        executed = true;

        uint256 refRate = rateRef_ > 0 ? rateRef_ : stopRateX1e18;
        uint256 expectedOut = (positionAmount * refRate) / 1e18;
        uint256 minOut = (expectedOut * SLIPPAGE_TOLERANCE_PERCENT) / 100;

        // The first payload argument is an address placeholder: the network
        // overwrites it with this contract's address for authentication.
        bytes memory payload = abi.encodeWithSignature(
            "executeStop(address,address,uint256,uint256)", address(0), client, positionAmount, minOut
        );

        emit Triggered(lastEpoch, refRate, triggerRate_, isStopLoss_);

        SYSTEM.requestCallbackV_1_0(
            ISystemContract.CallbackConfiguration_V_1_0({
                chainId: ORIGIN_CHAIN_ID,
                recipient: executor,
                gasLimit: CALLBACK_GAS_LIMIT,
                payload: payload
            })
        );
    }
}
