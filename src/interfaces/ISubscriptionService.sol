// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

/// @title Event subscription service exposed by the Reactive system contract.
interface ISubscriptionService {
    /// @notice Subscribes the caller to event logs matching all six criteria.
    /// @dev Use chainId 0 / address(0) / REACTIVE_IGNORE as wildcards per position.
    function subscribe(
        uint256 chainId_,
        address contract_,
        uint256 topic0_,
        uint256 topic1_,
        uint256 topic2_,
        uint256 topic3_
    ) external;

    /// @notice Removes a subscription matching all six criteria exactly.
    function unsubscribe(
        uint256 chainId_,
        address contract_,
        uint256 topic0_,
        uint256 topic1_,
        uint256 topic2_,
        uint256 topic3_
    ) external;
}
