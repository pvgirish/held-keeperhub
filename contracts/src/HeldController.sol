// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {IERC20, IMorpho, IRoles, MarketParams} from "./Interfaces.sol";

/// @title HeldController
/// @notice Owner-approved strategy limits and recoverable handover for one mandate
///         lineage, one Safe, one Morpho market.
///
/// Design constraints taken directly from Locked V4, and the reasons they are not
/// negotiable:
///
///  * **Paused by default.** A freshly deployed controller can do nothing until the
///    owner Safe activates an epoch (§6). Deployment is not authorisation.
///  * **No generic executor.** Only typed SUPPLY and WITHDRAW entry shapes exist. The
///    controller never accepts a caller-supplied call list (§3).
///  * **Ordinary CALLs only.** The action sequence is sequential `CALL` through Roles,
///    with every nested status checked. No runtime-selected MultiSend or delegatecall
///    shortcut (§3) — note the *native owner* path does use MultiSend for batching, but
///    that is the Safe owners acting, not this contract.
///  * **Consumption is monotonic.** `usedSupply` and friends only ever increase. This is
///    the one mechanism the P00 baseline actually motivates: native `setAllowance` writes
///    an *absolute* remaining value, so a policy update can silently regrant consumed
///    capacity. No ceremony or signature saving is claimed over the native path.
///  * **New lineage, own history.** Nothing imports pre-Held native usage into these
///    counters (§6). The fixture's historical 30,000 stays out.
contract HeldController {
    // ------------------------------------------------------------------ types --
    struct Policy {
        uint128 Ls; // cumulative supply ceiling
        uint128 Ln; // cumulative normal-withdraw ceiling
        uint128 Lr; // cumulative restoration-withdraw ceiling
        uint128 Ms; // per-action supply maximum
        uint128 Mn; // per-action normal-withdraw maximum
        uint128 Mr; // per-action restoration maximum
        uint128 ms; // per-action supply minimum
        uint128 mn; // per-action normal-withdraw minimum
        uint128 F; // liquid cash floor
        uint128 H; // supply-trigger surplus
        uint64 Nn; // normal successful-count limit
        uint64 Nr; // restoration successful-count limit
        uint64 dn; // normal cooldown, chain seconds
        uint64 dr; // restoration cooldown, chain seconds
    }

    struct Envelope {
        bytes32 operationId;
        bytes32 sourceIdentityHash;
        bytes32 payloadHash;
        uint8 actionFamily; // 0 HOLD, 1 SUPPLY, 2 WITHDRAW
        address safe;
        bytes32 lineage;
        uint64 epoch;
        uint32 policyVersion;
        address runner;
    }

    /// @notice The native Roles keys this lineage is bound to. Grouped so every budget
    ///         dimension is supplied explicitly and none can be forgotten at deployment.
    struct Keys {
        bytes32 normalRole;
        bytes32 restorationRole;
        bytes32 supplyAmount;
        bytes32 normalWithdrawAmount;
        bytes32 restorationAmount;
        bytes32 normalCount;
        bytes32 restorationCount;
    }

    /// @notice What the owner believes the controller's consumption to be when they
    ///         sign an activation. A stale preparation must not execute.
    struct ExpectedState {
        uint128 usedSupply;
        uint128 usedNormalWithdraw;
        uint128 usedRestoration;
        uint64 normalCount;
        uint64 restorationCount;
    }

    uint8 internal constant FAMILY_HOLD = 0;
    uint8 internal constant FAMILY_SUPPLY = 1;
    uint8 internal constant FAMILY_WITHDRAW = 2;

    /// @dev Must match packages/core/held_core/identity.py byte for byte.
    bytes32 internal constant ENVELOPE_TYPEHASH = keccak256(
        "Envelope(bytes32 operationId,bytes32 sourceIdentityHash,bytes32 payloadHash,uint8 actionFamily,address safe,bytes32 lineage,uint64 epoch,uint32 policyVersion,address runner)"
    );
    bytes32 internal constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 internal constant ACTION_TYPEHASH =
        keccak256("Action(uint8 family,bytes32 marketId,address asset,uint256 amount,address onBehalf)");

    // -------------------------------------------------------------- immutables --
    address public immutable owner; // the customer Safe; owner authority
    address public immutable safe; // the same Safe, as the account being operated
    address public immutable roles; // Zodiac Roles modifier
    address public immutable morpho;
    address public immutable token; // the loan asset, e.g. native USDC
    bytes32 public immutable marketId;
    bytes32 public immutable lineage;
    /// @dev Separate normal and restoration roles. Zodiac allows ONE condition tree per
    ///      (role, target, selector), so a single role cannot bind `withdraw`'s amount to
    ///      two different allowance keys. V4 §3 explicitly permits separate
    ///      normal/restoration roles; each remains controller-only.
    bytes32 public immutable normalRoleKey;
    bytes32 public immutable restorationRoleKey;
    /// @dev EVERY native budget dimension, not just the two amount lanes. V4 §5 requires
    ///      each Roles remaining allowance to equal its ceiling minus consumption, and
    ///      lists the shared normal count and the separate restoration count alongside the
    ///      amount quotas. Checking only supply and restoration amounts left the
    ///      normal-withdraw amount and both counts unsynchronised.
    bytes32 public immutable supplyAllowanceKey;
    bytes32 public immutable normalWithdrawAllowanceKey;
    bytes32 public immutable restorationAllowanceKey;
    bytes32 public immutable normalCountKey;
    bytes32 public immutable restorationCountKey;

    // ------------------------------------------------------------------ state --
    bool public active; // paused by default
    uint64 public epoch;
    uint32 public policyVersion;
    address public runner; // current-epoch authorization key
    address public executor; // configured outer sender (e.g. the KeeperHub route)
    Policy public policy;

    uint128 public usedSupply;
    uint128 public usedNormalWithdraw;
    uint128 public usedRestoration;
    uint64 public normalCount;
    uint64 public restorationCount;
    uint64 public lastNormalAt;
    uint64 public lastRestorationAt;

    /// @notice operationId => payload hash of the execution that consumed it.
    mapping(bytes32 => bytes32) public consumed;

    uint256 private _entered;

    // ----------------------------------------------------------------- errors --
    error NotOwner();
    error NotExecutor();
    error Paused();
    error AlreadyActive();
    error BadSignature();
    error WrongEpoch(uint64 got, uint64 want);
    error WrongPolicyVersion(uint32 got, uint32 want);
    error WrongScope();
    error WrongFamily();
    error PayloadMismatch();
    error OperationConsumed(bytes32 operationId);
    error HoldIsNotExecutable();
    error AmountOutOfRange();
    error CeilingExceeded();
    error CountExhausted();
    error CooldownActive();
    error FloorViolated();
    error EntryAllowanceNotZero();
    error ExitAllowanceNotZero();
    error NestedCallFailed(address target);
    error TokenReturnedFalse(address target);
    error EffectNotObserved(string what);
    error BorrowSharesPresent();
    error CollateralChanged();
    error StaleActivation();
    error AllowanceDesynchronised(uint256 rolesRemaining, uint256 expected);
    error CeilingBelowConsumption();
    error Reentrancy();

    // ----------------------------------------------------------------- events --
    event Activated(uint64 indexed epoch, uint32 policyVersion, address runner, address executor);
    event Fenced(uint64 indexed epoch);
    event OperationConsumedEvent(
        bytes32 indexed operationId, uint8 indexed family, uint256 amount, bytes32 payloadHash, uint64 epoch
    );

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier nonReentrant() {
        if (_entered != 0) revert Reentrancy();
        _entered = 1;
        _;
        _entered = 0;
    }

    constructor(
        address _owner,
        address _roles,
        address _morpho,
        address _token,
        bytes32 _marketId,
        bytes32 _lineage,
        Keys memory k
    ) {
        owner = _owner;
        safe = _owner; // the owner Safe is the operated account
        roles = _roles;
        morpho = _morpho;
        token = _token;
        marketId = _marketId;
        lineage = _lineage;
        normalRoleKey = k.normalRole;
        restorationRoleKey = k.restorationRole;
        supplyAllowanceKey = k.supplyAmount;
        normalWithdrawAllowanceKey = k.normalWithdrawAmount;
        restorationAllowanceKey = k.restorationAmount;
        normalCountKey = k.normalCount;
        restorationCountKey = k.restorationCount;
        // active stays false: deployment is not authorisation.
    }

    // ------------------------------------------------------------ owner actions --

    /// @notice Owner activates a fresh epoch with a policy, runner and executor.
    /// @dev Guarded three ways, all of which must hold atomically:
    ///      1. `expected` must equal the controller's actual consumption, so a stale
    ///         preparation cannot execute against state that moved underneath it.
    ///      2. A ceiling may never be set below what has already been consumed.
    ///      3. The native Roles remaining allowance must equal `Ls - usedSupply`.
    ///         This is the activation-consistency guard of V4 §5, and it is the
    ///         mechanism the P00 baseline's I2 case actually motivates: after 35,000
    ///         is consumed, an 80,000 ceiling is only consistent with 45,000 remaining,
    ///         and a stale 50,000 is refused rather than silently accepted.
    function activate(
        uint64 newEpoch,
        uint32 newPolicyVersion,
        address newRunner,
        address newExecutor,
        Policy calldata p,
        ExpectedState calldata expected
    ) external onlyOwner {
        if (active) revert AlreadyActive();
        if (newEpoch <= epoch) revert StaleActivation();

        if (
            expected.usedSupply != usedSupply || expected.usedNormalWithdraw != usedNormalWithdraw
                || expected.usedRestoration != usedRestoration || expected.normalCount != normalCount
                || expected.restorationCount != restorationCount
        ) revert StaleActivation();

        if (p.Ls < usedSupply || p.Ln < usedNormalWithdraw || p.Lr < usedRestoration) {
            revert CeilingBelowConsumption();
        }
        // A count ceiling below the consumed count is the same error in the count domain.
        if (p.Nn < normalCount || p.Nr < restorationCount) revert CeilingBelowConsumption();

        // EVERY dimension, amounts AND counts. A mismatch on any one blocks activation.
        _requireSynced(supplyAllowanceKey, uint256(p.Ls) - uint256(usedSupply));
        _requireSynced(normalWithdrawAllowanceKey, uint256(p.Ln) - uint256(usedNormalWithdraw));
        _requireSynced(restorationAllowanceKey, uint256(p.Lr) - uint256(usedRestoration));
        _requireSynced(normalCountKey, uint256(p.Nn) - uint256(normalCount));
        _requireSynced(restorationCountKey, uint256(p.Nr) - uint256(restorationCount));

        epoch = newEpoch;
        policyVersion = newPolicyVersion;
        runner = newRunner;
        executor = newExecutor;
        policy = p;
        active = true;
        emit Activated(newEpoch, newPolicyVersion, newRunner, newExecutor);
    }

    /// @notice Owner fences the current epoch on-chain. Consumption is preserved.
    function fence() external onlyOwner {
        active = false;
        emit Fenced(epoch);
    }

    // ------------------------------------------------------------ typed entries --

    function executeSupply(Envelope calldata env, MarketParams calldata mp, uint256 amount, bytes calldata signature)
        external
        nonReentrant
    {
        _authorize(env, FAMILY_SUPPLY, mp, amount, safe, signature);

        uint256 balanceBefore = IERC20(token).balanceOf(safe);
        Policy memory p = policy;

        // V4 §5 SUPPLY predicates, in base units, no float, no MAX sentinel.
        if (balanceBefore < uint256(p.F) + uint256(p.H)) revert FloorViolated();
        if (amount < p.ms || amount > p.Ms) revert AmountOutOfRange();
        if (amount > balanceBefore - p.F) revert FloorViolated();
        if (uint256(usedSupply) + amount > p.Ls) revert CeilingExceeded();
        if (normalCount >= p.Nn) revert CountExhausted();
        if (lastNormalAt != 0 && block.timestamp < uint256(lastNormalAt) + p.dn) revert CooldownActive();

        (uint256 shares0, uint128 borrow0, uint128 collateral0) = IMorpho(morpho).position(marketId, safe);
        if (borrow0 != 0) revert BorrowSharesPresent();
        if (IERC20(token).allowance(safe, morpho) != 0) revert EntryAllowanceNotZero();

        _approveThroughRoles(amount);
        _callThroughRoles(morpho, abi.encodeCall(IMorpho.supply, (mp, amount, 0, safe, bytes(""))), normalRoleKey);
        _approveThroughRoles(0);

        // Read the EXACT effects. V4 §5: never infer success from the outer receipt.
        uint256 balanceAfter = IERC20(token).balanceOf(safe);
        if (balanceBefore - balanceAfter != amount) revert EffectNotObserved("safe debit");
        if (balanceAfter < p.F) revert FloorViolated();
        (uint256 shares1, uint128 borrow1, uint128 collateral1) = IMorpho(morpho).position(marketId, safe);
        if (shares1 <= shares0) revert EffectNotObserved("supply shares did not increase");
        if (borrow1 != 0) revert BorrowSharesPresent();
        if (collateral1 != collateral0) revert CollateralChanged();
        if (IERC20(token).allowance(safe, morpho) != 0) revert ExitAllowanceNotZero();

        usedSupply += uint128(amount);
        normalCount += 1;
        lastNormalAt = uint64(block.timestamp);
        consumed[env.operationId] = env.payloadHash;
        emit OperationConsumedEvent(env.operationId, FAMILY_SUPPLY, amount, env.payloadHash, env.epoch);
    }

    function executeWithdraw(Envelope calldata env, MarketParams calldata mp, uint256 amount, bytes calldata signature)
        external
        nonReentrant
    {
        _authorize(env, FAMILY_WITHDRAW, mp, amount, safe, signature);

        uint256 balanceBefore = IERC20(token).balanceOf(safe);
        Policy memory p = policy;

        // The controller DERIVES the lane from the Safe balance. A runner cannot pick
        // the restoration lane to evade normal limits (V4 §5).
        bool restoration = balanceBefore < p.F;
        if (restoration) {
            if (amount == 0 || amount > p.Mr) revert AmountOutOfRange();
            if (amount > uint256(p.F) - balanceBefore) revert AmountOutOfRange();
            if (uint256(usedRestoration) + amount > p.Lr) revert CeilingExceeded();
            if (restorationCount >= p.Nr) revert CountExhausted();
            if (lastRestorationAt != 0 && block.timestamp < uint256(lastRestorationAt) + p.dr) revert CooldownActive();
        } else {
            if (amount < p.mn || amount > p.Mn) revert AmountOutOfRange();
            if (uint256(usedNormalWithdraw) + amount > p.Ln) revert CeilingExceeded();
            if (normalCount >= p.Nn) revert CountExhausted();
            if (lastNormalAt != 0 && block.timestamp < uint256(lastNormalAt) + p.dn) revert CooldownActive();
        }

        (uint256 shares0, uint128 borrow0, uint128 collateral0) = IMorpho(morpho).position(marketId, safe);
        if (borrow0 != 0) revert BorrowSharesPresent();

        // Withdraw needs no token approval: Morpho moves its own accounting. The
        // managed allowance must still be zero on both sides of the call.
        if (IERC20(token).allowance(safe, morpho) != 0) revert EntryAllowanceNotZero();
        _callThroughRoles(
            morpho,
            abi.encodeCall(IMorpho.withdraw, (mp, amount, 0, safe, safe)),
            restoration ? restorationRoleKey : normalRoleKey
        );

        uint256 balanceAfter = IERC20(token).balanceOf(safe);
        if (balanceAfter - balanceBefore != amount) revert EffectNotObserved("safe receipt");
        (uint256 shares1, uint128 borrow1, uint128 collateral1) = IMorpho(morpho).position(marketId, safe);
        if (shares1 >= shares0) revert EffectNotObserved("supply shares did not decrease");
        if (borrow1 != 0) revert BorrowSharesPresent();
        if (collateral1 != collateral0) revert CollateralChanged();
        if (IERC20(token).allowance(safe, morpho) != 0) revert ExitAllowanceNotZero();

        if (restoration) {
            usedRestoration += uint128(amount);
            restorationCount += 1;
            lastRestorationAt = uint64(block.timestamp);
        } else {
            usedNormalWithdraw += uint128(amount);
            normalCount += 1;
            lastNormalAt = uint64(block.timestamp);
        }
        consumed[env.operationId] = env.payloadHash;
        emit OperationConsumedEvent(env.operationId, FAMILY_WITHDRAW, amount, env.payloadHash, env.epoch);
    }

    // ---------------------------------------------------------------- internals --

    /// @dev One Roles allowance must equal its ceiling minus the corresponding
    ///      consumption. Used for every amount lane and every count lane alike.
    function _requireSynced(bytes32 key, uint256 expected) internal view {
        (,,, uint128 remaining,) = IRoles(roles).allowances(key);
        if (uint256(remaining) != expected) revert AllowanceDesynchronised(remaining, expected);
    }

    function _authorize(
        Envelope calldata env,
        uint8 family,
        MarketParams calldata mp,
        uint256 amount,
        address onBehalf,
        bytes calldata signature
    ) internal view {
        if (!active) revert Paused();
        if (msg.sender != executor) revert NotExecutor();
        if (family == FAMILY_HOLD || env.actionFamily == FAMILY_HOLD) revert HoldIsNotExecutable();
        if (env.actionFamily != family) revert WrongFamily();
        if (env.epoch != epoch) revert WrongEpoch(env.epoch, epoch);
        if (env.policyVersion != policyVersion) revert WrongPolicyVersion(env.policyVersion, policyVersion);
        if (env.safe != safe || env.lineage != lineage) revert WrongScope();
        if (env.runner != runner) revert BadSignature();
        if (consumed[env.operationId] != bytes32(0)) revert OperationConsumed(env.operationId);

        // The payload hash must be derivable from the typed action the caller supplied.
        // Otherwise a signature over one economic action could carry another.
        bytes32 computed = keccak256(
            abi.encode(ACTION_TYPEHASH, family, _marketIdOf(mp), mp.loanToken, amount, onBehalf)
        );
        if (computed != env.payloadHash) revert PayloadMismatch();
        if (_marketIdOf(mp) != marketId) revert WrongScope();
        if (mp.loanToken != token) revert WrongScope();

        address signer = ECDSA.recover(_signingHash(env), signature);
        if (signer != env.runner) revert BadSignature();
    }

    /// @dev Morpho's market id is the keccak of the packed market parameters.
    function _marketIdOf(MarketParams calldata mp) internal pure returns (bytes32) {
        return keccak256(abi.encode(mp));
    }

    function _domainSeparator() internal view returns (bytes32) {
        return keccak256(
            abi.encode(DOMAIN_TYPEHASH, keccak256(bytes("Held")), keccak256(bytes("1")), block.chainid, address(this))
        );
    }

    function _signingHash(Envelope calldata env) internal view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                ENVELOPE_TYPEHASH,
                env.operationId,
                env.sourceIdentityHash,
                env.payloadHash,
                env.actionFamily,
                env.safe,
                env.lineage,
                env.epoch,
                env.policyVersion,
                env.runner
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", _domainSeparator(), structHash));
    }

    /// @dev ERC20 `approve` through Roles, with the token's own return value checked.
    ///      A token that returns `false` instead of reverting must not be treated as
    ///      success — that is exactly the class of bug V4 §5 step 4 is about.
    function _approveThroughRoles(uint256 value) internal {
        bytes memory ret = _callThroughRoles(token, abi.encodeCall(IERC20.approve, (morpho, value)), normalRoleKey);
        if (ret.length >= 32 && abi.decode(ret, (uint256)) == 0) revert TokenReturnedFalse(token);
    }

    /// @dev One ordinary CALL through Roles → Safe. `shouldRevert=true` makes Roles
    ///      bubble a failure, and the success flag is checked as well rather than
    ///      trusted. No delegatecall, no MultiSend, no runtime-selected route.
    function _callThroughRoles(address to, bytes memory data, bytes32 key) internal returns (bytes memory) {
        (bool ok, bytes memory ret) =
            IRoles(roles).execTransactionWithRoleReturnData(to, 0, data, 0 /* Operation.Call */, key, true);
        if (!ok) revert NestedCallFailed(to);
        return ret;
    }

    // ------------------------------------------------------------------- views --

    function remainingSupply() external view returns (uint256) {
        return uint256(policy.Ls) - uint256(usedSupply);
    }

    function isConsumed(bytes32 operationId) external view returns (bool) {
        return consumed[operationId] != bytes32(0);
    }

    function actionHash(uint8 family, bytes32 market, address asset, uint256 amount, address onBehalf)
        external
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(ACTION_TYPEHASH, family, market, asset, amount, onBehalf));
    }

    function signingHash(Envelope calldata env) external view returns (bytes32) {
        return _signingHash(env);
    }
}
