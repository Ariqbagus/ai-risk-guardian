// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { IPayable } from "./IPayable.sol";
import { ISubscriptionService } from "./ISubscriptionService.sol";

/// @title Interface for the Reactive Network's system contract (0x8888...8888 on
///        both Reactive Mainnet and the Lasna testnet).
interface ISystemContract is IPayable, ISubscriptionService {
    /// @notice Supported callback configuration versions.
    enum CallbackVersion { V_1_0 }

    /// @notice Callback configuration for the V_1_0 delivery format.
    struct CallbackConfiguration_V_1_0 {
        uint256 chainId;   // destination chain id
        address recipient; // target contract on the destination chain
        uint64 gasLimit;   // execution gas limit for the callback
        bytes payload;     // ABI-encoded call; first argument must be an `address`
                           // placeholder that the network overwrites with the
                           // requesting reactive contract's address
    }

    /// @notice Requests a callback using a version flag plus an encoded configuration.
    function requestCallback(CallbackVersion version_, bytes memory config_) external;

    /// @notice Requests a V_1_0 callback using the typed configuration struct.
    function requestCallbackV_1_0(CallbackConfiguration_V_1_0 memory config_) external;
}
