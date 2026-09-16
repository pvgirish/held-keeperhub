// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @notice Morpho Blue market parameters, in the pinned field order.
/// @dev The account field is `onBehalf`. V4 §2: the compiler's Morpho helper living in a
///      file named aave_helpers.py does not make this an Aave integration.
struct MarketParams {
    address loanToken;
    address collateralToken;
    address oracle;
    address irm;
    uint256 lltv;
}

interface IMorpho {
    function supply(
        MarketParams memory marketParams,
        uint256 assets,
        uint256 shares,
        address onBehalf,
        bytes memory data
    ) external returns (uint256 assetsSupplied, uint256 sharesSupplied);

    function withdraw(
        MarketParams memory marketParams,
        uint256 assets,
        uint256 shares,
        address onBehalf,
        address receiver
    ) external returns (uint256 assetsWithdrawn, uint256 sharesWithdrawn);

    /// @return supplyShares borrowShares collateral
    function position(bytes32 id, address user) external view returns (uint256, uint128, uint128);

    function isAuthorized(address authorizer, address authorized) external view returns (bool);
}

interface IERC20 {
    function approve(address spender, uint256 value) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
}

/// @notice Zodiac Roles v2 modifier.
/// @dev Only the ReturnData variant is used. The plain variant discards the inner
///      return payload, and V4 §5 requires every nested return status and token
///      behaviour to be checked — a bare success bool is not enough for an ERC20
///      whose `approve` returns false instead of reverting.
interface IRoles {
    function execTransactionWithRoleReturnData(
        address to,
        uint256 value,
        bytes calldata data,
        uint8 operation,
        bytes32 roleKey,
        bool shouldRevert
    ) external returns (bool success, bytes memory returnData);

    function allowances(bytes32 key)
        external
        view
        returns (uint128 refill, uint128 maxRefill, uint64 period, uint128 balance, uint64 timestamp);
}

/// @notice Zodiac Roles v2 flat condition node.
/// @dev Enums are carried as uint8 so the ABI encoding is explicit and readable.
///      ParameterType: Static=1 Dynamic=2 Tuple=3 Calldata=5
///      Operator:      Pass=0 Matches=5 EqualTo=16 WithinAllowance=28
struct ConditionFlat {
    uint8 parent;
    uint8 paramType;
    uint8 operator;
    bytes compValue;
}

interface IRolesAdmin {
    function scopeFunction(
        bytes32 roleKey,
        address targetAddress,
        bytes4 selector,
        ConditionFlat[] memory conditions,
        uint8 options
    ) external;

    function setAllowance(
        bytes32 key,
        uint128 balance,
        uint128 maxRefill,
        uint128 refill,
        uint64 period,
        uint64 timestamp
    ) external;

    function assignRoles(address module, bytes32[] memory roleKeys, bool[] memory memberOf) external;
}

interface IRolesTargets {
    function scopeTarget(bytes32 roleKey, address targetAddress) external;
}
