// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.29;

import { IPayable } from "./interfaces/IPayable.sol";
import { IERC20 } from "./interfaces/IERC20.sol";
import { IUniswapV2Router02 } from "./interfaces/IUniswapV2.sol";
import { AbstractCallback } from "./base/AbstractCallback.sol";

/// @title StopExecutor — callback contract on Base Sepolia.
/// @notice Receives execution callbacks from RiskGuardianReactive (delivered by the
///         Base Sepolia callback proxy) and sells the client's risk-token position
///         into the stable token through the canonical Uniswap V2 router, sending
///         the proceeds straight back to the client. Emits `StopExecuted`, which
///         the reactive contract watches as its completion confirmation.
///
///         The client must `approve` this contract to spend the risk token first.
contract StopExecutor is AbstractCallback {
    IUniswapV2Router02 public immutable router;
    address public immutable pair;
    address public immutable tokenIn;  // risk token (sold)
    address public immutable tokenOut; // stable token (bought)

    event StopExecuted(address indexed client, address indexed pair, uint256 amountIn, uint256 amountOut);

    constructor(
        address callbackProxy_,
        address reactiveContract_,
        address router_,
        address pair_,
        address tokenIn_,
        address tokenOut_
    ) payable AbstractCallback(IPayable(payable(callbackProxy_)), reactiveContract_) {
        router = IUniswapV2Router02(router_);
        pair = pair_;
        tokenIn = tokenIn_;
        tokenOut = tokenOut_;
    }

    /// @notice Executes the protective swap. Callable only by the callback proxy,
    ///         and only for callbacks originating from the authorized reactive contract.
    /// @param reactive_ Injected by the network: the requesting reactive contract.
    /// @param client_ Position owner; tokens are pulled from and proceeds sent to them.
    /// @param amountIn_ Risk-token amount to sell.
    /// @param minOut_ Minimum stable-token amount accepted (slippage guard).
    function executeStop(address reactive_, address client_, uint256 amountIn_, uint256 minOut_)
        external
        onlyServiceProvider
        onlyCallbackSender(reactive_)
    {
        require(IERC20(tokenIn).transferFrom(client_, address(this), amountIn_), "transferFrom failed");
        require(IERC20(tokenIn).approve(address(router), amountIn_), "approve failed");

        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;

        // Deadline uses a timestamp, not a block number (Base Sepolia blocks are ~200ms).
        uint256[] memory amounts =
            router.swapExactTokensForTokens(amountIn_, minOut_, path, client_, block.timestamp + 600);

        emit StopExecuted(client_, pair, amountIn_, amounts[amounts.length - 1]);
    }

    /// @notice Settles outstanding debt to the callback proxy from this contract's balance.
    function coverDebt() external {
        _coverDebt();
    }
}
