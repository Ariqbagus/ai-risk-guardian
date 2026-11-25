// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { IPayer } from "../interfaces/IPayer.sol";
import { IPayable } from "../interfaces/IPayable.sol";

/// @title Base contract for contracts that pay execution fees to a service provider
///        (the Reactive system contract on Reactive chains, or a callback proxy on
///        destination chains).
/// @notice The provider charges fees after execution: charges draw on the contract's
///         reserves held by the provider first; any shortfall becomes debt, which the
///         provider settles by calling `pay()` here. While debt is outstanding the
///         provider stops delivering work, so staying funded is a liveness requirement.
abstract contract AbstractPayer is IPayer {
    /// @notice The caller is not the authorized service provider.
    error NotAuthorized(address sender_, address provider_);

    /// @notice The contract balance cannot cover a requested payment.
    error InsufficientFunds(uint256 required_, uint256 available_);

    /// @notice A payment transfer to the service provider failed.
    error TransferFailed();

    /// @notice Service provider contract allowed to request payments from this contract.
    IPayable public immutable _SERVICE_PROVIDER;

    constructor(IPayable serviceProvider_) {
        _SERVICE_PROVIDER = serviceProvider_;
    }

    /// @inheritdoc IPayer
    receive() external payable virtual {}

    /// @notice Guards methods that may only be called by the service provider.
    modifier onlyServiceProvider() {
        _onlyServiceProvider();
        _;
    }

    function _onlyServiceProvider() internal view {
        if (msg.sender != address(_SERVICE_PROVIDER)) {
            revert NotAuthorized(msg.sender, address(_SERVICE_PROVIDER));
        }
    }

    /// @inheritdoc IPayer
    function pay(uint256 amount_) external onlyServiceProvider {
        _pay(payable(msg.sender), amount_);
    }

    /// @notice Settles the full outstanding debt from this contract's own balance,
    ///         provided the balance covers it.
    function _coverDebt() internal {
        uint256 amount = _SERVICE_PROVIDER.debt(address(this));
        _pay(payable(address(_SERVICE_PROVIDER)), amount);
    }

    /// @notice Transfers `amount_` to `recipient_`, reverting if underfunded or on failure.
    function _pay(address payable recipient_, uint256 amount_) internal {
        if (address(this).balance < amount_) {
            revert InsufficientFunds(amount_, address(this).balance);
        }
        if (amount_ > 0) {
            (bool success,) = recipient_.call{value: amount_}(new bytes(0));
            if (!success) {
                revert TransferFailed();
            }
        }
    }
}
