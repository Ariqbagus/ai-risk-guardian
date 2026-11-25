// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

/// @title Common interface for the Reactive system contract and callback proxies.
/// @notice Implemented by the party a payer contract owes execution fees to.
interface IPayable {
    /// @notice Allows the provider to accept payments (used by `depositTo` flows and debt settlement).
    receive() external payable;

    /// @notice Current outstanding debt of a contract, as recorded by the provider.
    /// @param contract_ Contract whose debt is queried.
    /// @return debt_ Outstanding debt in the provider chain's native currency.
    function debt(address contract_) external view returns (uint256 debt_);

    /// @notice Reserves (pre-paid fee credit) held by the provider for a contract.
    /// @param contract_ Contract whose reserves are queried.
    /// @return reserves_ Reserve balance in native currency.
    function reserves(address contract_) external view returns (uint256 reserves_);

    /// @notice Credits reserves (settling debt first) for an arbitrary contract, paid by the caller.
    /// @param contract_ Contract to credit.
    function depositTo(address contract_) external payable;
}
