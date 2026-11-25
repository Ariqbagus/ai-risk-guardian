// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

/// @title Interface for contracts that pay execution fees to a service provider
///        (the Reactive system contract, or a destination-chain callback proxy).
interface IPayer {
    /// @notice Accepts plain native-currency transfers (the contract's spendable balance).
    receive() external payable;

    /// @notice Pays the given amount to the service provider. Only callable by the provider itself.
    /// @param amount_ Amount to hand over, in native currency.
    function pay(uint256 amount_) external;
}
