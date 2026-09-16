// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {HeldController} from "../../../contracts/src/HeldController.sol";
import {MarketParams} from "../../../contracts/src/Interfaces.sol";

/// @notice ADVERSARIAL FIXTURES. Deliberately hostile stand-ins used ONLY to exercise
///         failure branches that cannot be reached with well-behaved production
///         contracts: reentrancy, an ERC20 that returns false, and a cleanup call that
///         fails after the economic action has already executed.
///
/// These are NOT the production profile. They are never used in the real-pinned-route
/// fork suite, and no result from this file may be described as native USDC, real
/// Zodiac Roles or real Morpho behaviour.

/// @dev Stands in for the Roles modifier + Safe: performs the call the controller asks
///      for, so the controller's own nested-status handling is what is under test.
contract MockRoles {
    /// @dev Per-key balances. The controller checks FIVE dimensions (supply,
    ///      normal-withdraw and restoration amounts, plus normal and restoration counts),
    ///      and amounts and counts cannot share one value.
    mapping(bytes32 => uint128) public balances;
    bytes32 public supplyKey;
    bytes32 public restorationKey;

    function setKeyBalance(bytes32 key, uint128 value) external {
        balances[key] = value;
    }

    function setAllowances(uint128 supply_, uint128 restoration_) external {
        balances[supplyKey] = supply_;
        balances[restorationKey] = restoration_;
    }

    function setKeys(bytes32 s, bytes32 r) external {
        supplyKey = s;
        restorationKey = r;
    }

    function supplyBalance() external view returns (uint128) {
        return balances[supplyKey];
    }

    /// @dev The controller now checks FIVE keys (supply, normal-withdraw and restoration
    ///      amounts, plus normal and restoration counts). Any key other than the two
    ///      configured amount keys answers from `otherBalance`, which the harness sets to
    ///      whatever the policy requires.
    function allowances(bytes32 key) external view returns (uint128, uint128, uint64, uint128, uint64) {
        uint128 bal = balances[key];
        return (0, bal, 0, bal, 0);
    }

    function execTransactionWithRoleReturnData(
        address to,
        uint256 value,
        bytes calldata data,
        uint8,
        bytes32,
        bool shouldRevert
    ) external returns (bool success, bytes memory returnData) {
        (success, returnData) = to.call{value: value}(data);
        if (!success && shouldRevert) {
            assembly {
                revert(add(returnData, 0x20), mload(returnData))
            }
        }
    }
}

/// @dev Minimal Morpho stand-in that RECORDS whether the economic action was reached.
contract MockMorpho {
    uint256 public supplyCount;
    uint256 public shares;
    uint128 public borrowShares;
    uint128 public collateral;

    function supply(MarketParams memory, uint256 assets, uint256, address, bytes memory)
        external
        returns (uint256, uint256)
    {
        supplyCount += 1;
        shares += assets;
        MockToken(_token).pull(assets);
        return (assets, assets);
    }

    address internal _token;

    function setToken(address t) external {
        _token = t;
    }

    function withdraw(MarketParams memory, uint256 assets, uint256, address, address receiver)
        external
        returns (uint256, uint256)
    {
        shares -= assets;
        MockToken(_token).push(receiver, assets);
        return (assets, assets);
    }

    function position(bytes32, address) external view returns (uint256, uint128, uint128) {
        return (shares, borrowShares, collateral);
    }

    function isAuthorized(address, address) external pure returns (bool) {
        return false;
    }
}

/// @dev Base token the hostile variants extend. Balances are moved by the mock Morpho
///      so the controller's exact-effect readbacks still hold on the happy path.
contract MockToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    address public safeAddr;
    address public morphoAddr;

    function init(address safe_, address morpho_, uint256 amount) external {
        safeAddr = safe_;
        morphoAddr = morpho_;
        balanceOf[safe_] = amount;
    }

    function approve(address spender, uint256 value) external virtual returns (bool) {
        allowance[msg.sender][spender] = value;
        return true;
    }

    function pull(uint256 assets) external {
        balanceOf[safeAddr] -= assets;
    }

    function push(address to, uint256 assets) external {
        balanceOf[to] += assets;
    }
}

/// @dev Returns FALSE from approve instead of reverting -- the classic non-standard
///      ERC20 that a bare success flag would wave through.
contract FalseReturnToken is MockToken {
    function approve(address spender, uint256 value) external override returns (bool) {
        allowance[msg.sender][spender] = value;
        return false;
    }
}

/// @dev Fails the CLEANUP approval, and only after observing that the economic action
///      already executed. The revert identity is therefore itself proof that the
///      supply was reached before cleanup failed.
contract CleanupFailingToken is MockToken {
    error CleanupFailedAfterSupply();

    MockMorpho public morphoRef;

    function setMorpho(MockMorpho m) external {
        morphoRef = m;
    }

    function approve(address spender, uint256 value) external override returns (bool) {
        if (value == 0 && morphoRef.supplyCount() > 0) revert CleanupFailedAfterSupply();
        allowance[msg.sender][spender] = value;
        return true;
    }
}

/// @dev Reenters the controller during the approval leg. It performs the reentry with a
///      low-level call and, if the controller refuses with Reentrancy(), reverts with a
///      unique error -- so the guard firing is observable through the outer revert.
contract ReenteringToken is MockToken {
    error ReentrancyWasRefused();
    error ReentrancyWasNOTRefused();

    HeldController public controller;
    bool public armed;

    function arm(HeldController c) external {
        controller = c;
        armed = true;
    }

    function approve(address spender, uint256 value) external override returns (bool) {
        if (armed) {
            armed = false; // one attempt only
            HeldController.Envelope memory env;
            MarketParams memory mp;
            (bool ok, bytes memory ret) = address(controller).call(
                abi.encodeCall(HeldController.executeSupply, (env, mp, 1, ""))
            );
            if (ok) revert ReentrancyWasNOTRefused();
            if (bytes4(ret) == HeldController.Reentrancy.selector) revert ReentrancyWasRefused();
            revert ReentrancyWasNOTRefused();
        }
        allowance[msg.sender][spender] = value;
        return true;
    }
}
