// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

/// @title SignalRegistry — on-chain mailbox for the AI risk agent's decisions.
/// @notice Lives on Base Sepolia. The off-chain AI agent evaluates the market and
///         publishes its regime call here; the reactive contract on Lasna subscribes
///         to `SignalUpdated` and arms/re-arms the guardian with these parameters.
///
///         Rates are the price of the pair's risk token denominated in the stable
///         token, scaled by 1e18 (rate = reserveStable * 1e18 / reserveRisk).
contract SignalRegistry {
    /// @notice The only address allowed to publish signals (the AI agent's wallet).
    address public immutable agent;

    /// @notice Monotonic counter, incremented on every published signal.
    uint256 public epoch;

    struct Signal {
        bool riskOff;              // true = model wants an immediate defensive exit
        uint256 stopRateX1e18;     // sell if rate <= this
        uint256 takeProfitRateX1e18; // sell if rate >= this (0 disables)
        int256 scoreX1e4;          // model risk score, scaled by 1e4 (0..10000)
        uint256 updatedAt;         // block.timestamp of the publish
    }

    Signal public latest;

    event SignalUpdated(
        uint256 indexed epoch,
        bool riskOff,
        uint256 stopRateX1e18,
        uint256 takeProfitRateX1e18,
        int256 scoreX1e4,
        uint256 updatedAt
    );

    constructor(address agent_) {
        require(agent_ != address(0), "zero agent");
        agent = agent_;
    }

    /// @notice Publishes a new signal. Only the agent may call this.
    function updateSignal(
        bool riskOff_,
        uint256 stopRateX1e18_,
        uint256 takeProfitRateX1e18_,
        int256 scoreX1e4_
    ) external {
        require(msg.sender == agent, "not agent");
        epoch += 1;
        latest = Signal(riskOff_, stopRateX1e18_, takeProfitRateX1e18_, scoreX1e4_, block.timestamp);
        emit SignalUpdated(epoch, riskOff_, stopRateX1e18_, takeProfitRateX1e18_, scoreX1e4_, block.timestamp);
    }
}
