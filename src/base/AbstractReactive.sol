// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { ISystemContract } from "../interfaces/ISystemContract.sol";
import { IReactive } from "../interfaces/IReactive.sol";
import { AbstractPayer } from "./AbstractPayer.sol";

/// @title Base contract for reactive contracts (Reactive Omni model).
/// @notice A reactive contract is an ordinary contract on Reactive Network that
///         subscribes to event logs through the system contract and receives
///         matching logs via `react()`, which only the system contract may call.
abstract contract AbstractReactive is AbstractPayer, IReactive {
    /// @notice The Reactive system contract (same address on mainnet and Lasna).
    ISystemContract internal constant SYSTEM =
        ISystemContract(payable(0x8888888888888888888888888888888888888888));

    /// @notice Wildcard topic value for event subscriptions.
    uint256 internal constant REACTIVE_IGNORE =
        0xa65f96fc951c35ead38878e0f0b7a3c744a6f5ccc1476b313353ce31712313ad;

    constructor() AbstractPayer(SYSTEM) {}

    /// @notice Guards methods (above all `react()`) that only the system contract may call.
    modifier onlySystem() {
        _onlyServiceProvider();
        _;
    }
}
