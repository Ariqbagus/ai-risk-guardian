// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { IPayable } from "../interfaces/IPayable.sol";
import { AbstractPayer } from "./AbstractPayer.sol";

/// @title Base contract for contracts receiving Reactive Network callbacks.
/// @notice Callbacks are delivered by the chain's callback proxy, which overwrites
///         the first 160 bits of the payload with the requesting reactive contract's
///         address. A callback method must therefore declare an `address` as its
///         first parameter and check both that the caller is the proxy
///         (`onlyServiceProvider`, inherited) and that the injected address is the
///         authorized reactive contract (`onlyCallbackSender`).
abstract contract AbstractCallback is AbstractPayer {
    /// @notice The injected callback sender is not the authorized reactive contract.
    error CallbackNotAuthorized(address sender_, address expectedSender_);

    /// @notice Address of the reactive contract allowed to send callbacks here.
    address public immutable _CALLBACK_SENDER;

    /// @param callbackProxy_ The callback proxy contract on this chain (the service provider).
    /// @param callbackSender_ The reactive contract allowed to trigger callbacks here.
    constructor(IPayable callbackProxy_, address callbackSender_) AbstractPayer(callbackProxy_) {
        _CALLBACK_SENDER = callbackSender_;
    }

    /// @notice Guards callback methods by the injected reactive-contract address.
    modifier onlyCallbackSender(address callbackSender_) {
        _onlyCallbackSender(callbackSender_);
        _;
    }

    function _onlyCallbackSender(address callbackSender_) internal view {
        if (callbackSender_ != _CALLBACK_SENDER) {
            revert CallbackNotAuthorized(callbackSender_, _CALLBACK_SENDER);
        }
    }
}
