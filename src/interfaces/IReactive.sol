// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { IPayer } from "./IPayer.sol";

/// @title Interface for reactive contracts.
/// @notice Reactive contracts receive notifications about new event logs matching
///         their subscriptions, delivered by the system contract via `react()`.
interface IReactive is IPayer {
    /// @notice Normalized representation of an EVM event log.
    struct LogRecord {
        uint256 chainId;
        address contractAddress;
        uint256 topic0;
        uint256 topic1;
        uint256 topic2;
        uint256 topic3;
        bytes data;
        uint256 blockNumber;
        uint256 opCode;
        uint256 blockHash;
        uint256 txHash;
        uint256 logIndex;
    }

    /// @notice Entry point for handling new event notifications.
    /// @param log_ Data structure describing the intercepted log record.
    function react(LogRecord calldata log_) external;
}
