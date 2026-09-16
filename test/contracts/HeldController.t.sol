// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test, console2} from "forge-std/Test.sol";

import {HeldController} from "../../contracts/src/HeldController.sol";
import {ConditionFlat, IERC20, IMorpho, IRoles, IRolesAdmin, IRolesTargets, MarketParams} from "../../contracts/src/Interfaces.sol";

/// @notice P02 fork tests against the REAL pinned Base-mainnet contracts.
///
/// These run against a live anvil fork that fixtures/scripts/01..03b has already
/// populated with a genuine 2-of-3 Safe and a Zodiac Roles module, so the Safe,
/// Roles, Morpho, USDC and market are all real code — nothing is mocked. The Safe's
/// owner authority is exercised with `vm.prank(safe)`; the real two-signature
/// ceremony is separately evidenced in P00 and is not re-proven here.
contract HeldControllerForkTest is Test {
    address constant MORPHO = 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb;
    address constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address constant COLL = 0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452;
    address constant ORACLE = 0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A;
    address constant IRM = 0x46415998764C29aB2a25CbeA6254146D50D22687;
    uint256 constant LLTV = 860000000000000000;
    uint256 constant USDC_SLOT = 9;

    // anvil deterministic accounts — LOCAL FIXTURE IDENTITIES ONLY, never real custody
    uint256 constant PK_RUNNER_B = 0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a;
    uint256 constant PK_RUNNER_A = 0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6;
    address constant EXECUTOR = 0x976EA74026E726554dB657fA54763abd0C3a0aa9; // the configured outer sender

    HeldController controller;
    address safe;
    address roles;
    address runnerB;
    address runnerA;
    bytes32 roleKey;
    bytes32 allowKey;
    bytes32 marketId;
    bytes32 constant LINEAGE = bytes32(uint256(0x11));

    bytes32 constant WITHDRAW_KEY = keccak256("held-withdraw-cap");
    bytes32 constant RESTORE_ROLE = keccak256("held-restoration-v1");
    bytes32 constant RESTORE_KEY = keccak256("held-restoration-cap");
    bytes32 constant NORMAL_COUNT_KEY = keccak256("held-normal-count");
    bytes32 constant RESTORE_COUNT_KEY = keccak256("held-restoration-count");
    uint128 constant LN = 50_000e6;
    uint128 constant LR = 10_000e6;
    uint128 constant LS = 50_000e6;
    uint128 constant MS = 40_000e6;

    function setUp() public {
        safe = vm.envAddress("HELD_SAFE");
        roles = vm.envAddress("HELD_ROLES");
        roleKey = vm.envBytes32("HELD_ROLE_KEY");
        allowKey = vm.envBytes32("HELD_ALLOW_KEY");
        runnerB = vm.addr(PK_RUNNER_B);
        runnerA = vm.addr(PK_RUNNER_A);
        marketId = keccak256(abi.encode(_mp()));

        controller = new HeldController(
            safe, roles, MORPHO, USDC, marketId, LINEAGE,
            HeldController.Keys({
                normalRole: roleKey,
                restorationRole: RESTORE_ROLE,
                supplyAmount: allowKey,
                normalWithdrawAmount: WITHDRAW_KEY,
                restorationAmount: RESTORE_KEY,
                normalCount: NORMAL_COUNT_KEY,
                restorationCount: RESTORE_COUNT_KEY
            })
        );

        // Owner installs the new lineage: the controller becomes the role member and
        // the previous operator is retired. V4 §3: the controller is the SOLE member
        // of the operating role; neither runner gets a direct path around it.
        vm.startPrank(safe);
        _assign(address(controller), roleKey, true);
        _assign(address(controller), RESTORE_ROLE, true);
        _assign(runnerA, roleKey, false);
        // A NEW lineage gets a clearly labelled NEW budget. The native fixture's
        // historical 30,000 is deliberately NOT imported (V4 §6).
        // P02 OVERLAY: re-scope supply with TIGHT argument conditions. The P00 fixture
        // bound only the `assets` allowance and left the market tuple, shares and
        // onBehalf permissive. Roles must be an INDEPENDENT defence: controller-side
        // checks do not substitute for it.
        _scopeSupplyTight();
        _scopeApproveBounded();
        _setAllowance(LS, LS);
        // Withdraw needs its own scoped function and its own non-refilling quota, or
        // Roles rejects it outright (FunctionNotAllowed) -- scopeTarget sets
        // Clearance.Function, so EVERY function must be scoped explicitly. Defence in
        // depth: the amount is bound to a separate allowance key, exactly as supply is.
        _scopeWithdraw(roleKey, WITHDRAW_KEY, NORMAL_COUNT_KEY);
        IRolesAdmin(roles).setAllowance(WITHDRAW_KEY, LN, LN, 0, 0, 0);
        // The RESTORATION lane is a separate role with its OWN non-refilling key, because
        // Zodiac allows one condition tree per (role, target, selector). V4 §3 permits
        // separate normal/restoration roles; both remain controller-only.
        IRolesTargets(roles).scopeTarget(RESTORE_ROLE, MORPHO);
        _scopeWithdraw(RESTORE_ROLE, RESTORE_KEY, RESTORE_COUNT_KEY);
        IRolesAdmin(roles).setAllowance(RESTORE_KEY, LR, LR, 0, 0, 0);
        // Native COUNT allowances, one per lane. V4 §5: the shared normal count covers
        // SUPPLY and NORMAL WITHDRAW; restoration has its own.
        IRolesAdmin(roles).setAllowance(NORMAL_COUNT_KEY, 10, 10, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(RESTORE_COUNT_KEY, 5, 5, 0, 0, 0);
        vm.stopPrank();

        _fundSafe(50_000e6);
    }

    // ------------------------------------------------------------------ helpers --
    function _mp() internal pure returns (MarketParams memory) {
        return MarketParams({loanToken: USDC, collateralToken: COLL, oracle: ORACLE, irm: IRM, lltv: LLTV});
    }

    function _assign(address who, bytes32 key, bool member) internal {
        bytes32[] memory keys = new bytes32[](1);
        bool[] memory members = new bool[](1);
        keys[0] = key;
        members[0] = member;
        (bool ok,) = roles.call(abi.encodeWithSignature("assignRoles(address,bytes32[],bool[])", who, keys, members));
        require(ok, "assignRoles failed");
    }

    function _setAllowance(uint128 balance, uint128 maxRefill) internal {
        (bool ok,) = roles.call(
            abi.encodeWithSignature(
                "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)", allowKey, balance, maxRefill, 0, 0, 0
            )
        );
        require(ok, "setAllowance failed");
    }

    /// @dev Flat condition tree for Morpho.withdraw(MarketParams,uint256,uint256,address,address):
    ///      root Calldata/Matches, param0 the MarketParams tuple with Pass on its five
    ///      fields, param1 `assets` bound WithinAllowance to the withdraw key, Pass on
    ///      the rest. Same shape as the supply tree built by fixture step 3b.
    /// @dev TIGHT withdraw tree. Every fixed argument is pinned with EqualTo; only the
    ///      amount is a quota. Previously shares, onBehalf, receiver and the market tuple
    ///      fields were all `Pass`, which meant Roles was not independently restricting
    ///      anything except the amount.
    function _scopeWithdraw(bytes32 role, bytes32 allowanceKey, bytes32 countKey) internal {
        ConditionFlat[] memory c = new ConditionFlat[](11);
        c[0] = ConditionFlat(0, 5, 5, "");                                   // root Calldata/Matches
        c[1] = ConditionFlat(0, 3, 5, "");                                   // param0 tuple, Matches
        c[2] = ConditionFlat(0, 1, 28, abi.encode(allowanceKey));            // param1 assets WithinAllowance
        c[3] = ConditionFlat(0, 1, 16, abi.encode(uint256(0)));              // param2 shares == 0
        c[4] = ConditionFlat(0, 1, 16, abi.encode(safe));                    // param3 onBehalf == Safe
        c[5] = ConditionFlat(0, 1, 16, abi.encode(safe));                    // param4 receiver == Safe
        c[6] = ConditionFlat(1, 1, 16, abi.encode(USDC));
        c[7] = ConditionFlat(1, 1, 16, abi.encode(COLL));
        c[8] = ConditionFlat(1, 1, 16, abi.encode(ORACLE));
        c[9] = ConditionFlat(1, 1, 16, abi.encode(IRM));
        c[10] = ConditionFlat(1, 1, 16, abi.encode(LLTV));
        IRolesAdmin(roles).scopeFunction(role, MORPHO, IMorpho.withdraw.selector, _withCallCount(c, countKey), 0);
    }

    /// @dev TIGHT supply tree, the P02 overlay over the P00 fixture's permissive one.
    function _scopeSupplyTight() internal {
        ConditionFlat[] memory c = new ConditionFlat[](11);
        c[0] = ConditionFlat(0, 5, 5, "");                                   // root Calldata/Matches
        c[1] = ConditionFlat(0, 3, 5, "");                                   // param0 tuple, Matches
        c[2] = ConditionFlat(0, 1, 28, abi.encode(allowKey));                // param1 assets WithinAllowance
        c[3] = ConditionFlat(0, 1, 16, abi.encode(uint256(0)));              // param2 shares == 0
        c[4] = ConditionFlat(0, 1, 16, abi.encode(safe));                    // param3 onBehalf == Safe
        // EqualTo accepts Dynamic. compValue is hashed on store and compared against
        // keccak256(pluck(...)) at check time, so the empty-bytes encoding below pins
        // the callback to empty AT THE ROLES LAYER, independently of the controller.
        c[5] = ConditionFlat(0, 2, 16, abi.encode(bytes("")));               // param4 data == 0x
        c[6] = ConditionFlat(1, 1, 16, abi.encode(USDC));
        c[7] = ConditionFlat(1, 1, 16, abi.encode(COLL));
        c[8] = ConditionFlat(1, 1, 16, abi.encode(ORACLE));
        c[9] = ConditionFlat(1, 1, 16, abi.encode(IRM));
        c[10] = ConditionFlat(1, 1, 16, abi.encode(LLTV));
        IRolesAdmin(roles).scopeFunction(roleKey, MORPHO, IMorpho.supply.selector, _withCallCount(c, NORMAL_COUNT_KEY), 0);
    }

    /// @dev P02 overlay for the token approval. The P00 fixture bound the spender to
    ///      Morpho but left the VALUE unrestricted at the native layer. A finite bound is
    ///      applied here; cleanup approve(0) stays permitted because 0 < bound.
    ///
    ///      Deliberately NOT a WithinAllowance: the approval must not charge the economic
    ///      amount quota, which is consumed by the protocol call alone (V4 §5).
    function _scopeApproveBounded() internal {
        ConditionFlat[] memory c = new ConditionFlat[](3);
        c[0] = ConditionFlat(0, 5, 5, "");                                   // root Calldata/Matches
        c[1] = ConditionFlat(0, 1, 16, abi.encode(MORPHO));                  // spender == Morpho
        c[2] = ConditionFlat(0, 1, 18, abi.encode(uint256(MS) + 1));         // value < Ms + 1
        IRolesAdmin(roles).scopeFunction(roleKey, USDC, IERC20.approve.selector, c, 0);
    }

    /// @dev Insert a CallWithinAllowance node so the native COUNT allowance is actually
    ///      CONSUMED by the economic call, not merely checked at activation.
    ///
    ///      Operator 30 / paramType None(0), confirmed from Zodiac Types.sol at the
    ///      pinned source. The node must be INSERTED among the root's children, not
    ///      appended: the condition array is required to be breadth-first, and appending
    ///      a parent==0 node after the parent==1 tuple children reverts NotBFS().
    function _withCallCount(ConditionFlat[] memory base, bytes32 countKey)
        internal pure returns (ConditionFlat[] memory out)
    {
        uint256 insertAt = base.length;
        for (uint256 i = 1; i < base.length; i++) {
            if (base[i].parent != 0) { insertAt = i; break; }
        }
        out = new ConditionFlat[](base.length + 1);
        for (uint256 i = 0; i < insertAt; i++) out[i] = base[i];
        out[insertAt] = ConditionFlat(0, 0, 30, abi.encode(countKey));
        for (uint256 i = insertAt; i < base.length; i++) {
            out[i + 1] = base[i];
            // children referencing the tuple keep pointing at it; the tuple is at index 1
            // and nothing was inserted before it, so parent indices are unchanged.
        }
    }

    /// @dev Sync every dimension EXCEPT the supply amount, so a test can vary that one
    ///      alone and observe the guard. Must be called under an active prank.
    function _syncNonSupply(HeldController.Policy memory p) internal {
        IRolesAdmin(roles).setAllowance(WITHDRAW_KEY, p.Ln - controller.usedNormalWithdraw(), p.Ln, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(RESTORE_KEY, p.Lr - controller.usedRestoration(), p.Lr, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(NORMAL_COUNT_KEY, p.Nn - controller.normalCount(), p.Nn, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(RESTORE_COUNT_KEY, p.Nr - controller.restorationCount(), p.Nr, 0, 0, 0);
    }

    /// @dev Bring every native allowance into agreement with a policy and the
    ///      controller's current consumption, as an owner would before activating.
    function _syncRoles(HeldController.Policy memory p) internal {
        IRolesAdmin(roles).setAllowance(allowKey, p.Ls - controller.usedSupply(), p.Ls, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(WITHDRAW_KEY, p.Ln - controller.usedNormalWithdraw(), p.Ln, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(RESTORE_KEY, p.Lr - controller.usedRestoration(), p.Lr, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(NORMAL_COUNT_KEY, p.Nn - controller.normalCount(), p.Nn, 0, 0, 0);
        IRolesAdmin(roles).setAllowance(RESTORE_COUNT_KEY, p.Nr - controller.restorationCount(), p.Nr, 0, 0, 0);
    }

    function _fundSafe(uint256 amount) internal {
        vm.store(USDC, keccak256(abi.encode(safe, USDC_SLOT)), bytes32(amount));
        assertEq(IERC20(USDC).balanceOf(safe), amount, "safe funding readback");
    }

    function _policy() internal pure returns (HeldController.Policy memory p) {
        p = _policyWith(10, 0, 0);
    }

    function _policyWith(uint64 nn, uint64 dn, uint64 dr) internal pure returns (HeldController.Policy memory p) {
        p.Ls = LS;
        p.Ln = LN;
        p.Lr = LR;
        p.Ms = MS;
        p.Mn = 10_000e6;
        p.Mr = 5_000e6;
        p.ms = 1_000e6;
        p.mn = 1_000e6;
        p.F = 1_000e6;
        p.H = 0;
        p.Nn = nn;
        p.Nr = 5;
        p.dn = dn;
        p.dr = dr;
    }

    function _activateWith(uint64 ep, address who, HeldController.Policy memory p) internal {
        // Hoisted deliberately: vm.prank applies to the NEXT call, and _expected()
        // makes external view calls that would consume it before activate() runs.
        // startPrank, not prank: _syncRoles makes FIVE owner calls and vm.prank only
        // covers the first, which left four arriving from the test contract and
        // reverting OwnableUnauthorizedAccount.
        vm.startPrank(safe);
        _syncRoles(p);
        vm.stopPrank();
        HeldController.ExpectedState memory exp = _expected();
        vm.prank(safe);
        controller.activate(ep, 1, who, EXECUTOR, p, exp);
    }

    function _expected() internal view returns (HeldController.ExpectedState memory e) {
        e.usedSupply = controller.usedSupply();
        e.usedNormalWithdraw = controller.usedNormalWithdraw();
        e.usedRestoration = controller.usedRestoration();
        e.normalCount = controller.normalCount();
        e.restorationCount = controller.restorationCount();
    }

    function _activate(uint64 ep, address who) internal {
        _activateWith(ep, who, _policy());
    }

    function _envelope(bytes32 opId, uint8 family, uint256 amount, uint64 ep, address who)
        internal
        view
        returns (HeldController.Envelope memory env)
    {
        env.operationId = opId;
        env.sourceIdentityHash = keccak256("native-decision");
        env.payloadHash = controller.actionHash(family, marketId, USDC, amount, safe);
        env.actionFamily = family;
        env.safe = safe;
        env.lineage = LINEAGE;
        env.epoch = ep;
        env.policyVersion = 1;
        env.runner = who;
    }

    function _sign(HeldController.Envelope memory env, uint256 pk) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, controller.signingHash(env));
        return abi.encodePacked(r, s, v);
    }

    function _supply(bytes32 opId, uint256 amount, uint64 ep, uint256 pk, address who) internal {
        HeldController.Envelope memory env = _envelope(opId, 1, amount, ep, who);
        bytes memory sig = _sign(env, pk); // hoisted: signingHash() is an external view call
        MarketParams memory mp = _mp();
        vm.prank(EXECUTOR);
        controller.executeSupply(env, mp, amount, sig);
    }

    // --------------------------------------- real 2-of-3 Safe batch helpers ----
    address constant MULTISEND = 0x9641d764fc13c8B624c04430C7356C1C7C8102e2; // MultiSendCallOnly 1.4.1
    uint256 constant PK_OWNER1 = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    uint256 constant PK_OWNER2 = 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d;

    function _msPart(address to, bytes memory data) internal pure returns (bytes memory) {
        return abi.encodePacked(uint8(0), to, uint256(0), uint256(data.length), data);
    }

    function _batch(bytes memory rolesCall, bytes memory controllerCall) internal view returns (bytes memory) {
        bytes memory payload = abi.encodePacked(_msPart(roles, rolesCall), _msPart(address(controller), controllerCall));
        return abi.encodeWithSignature("multiSend(bytes)", payload);
    }

    /// @dev A genuine Safe execTransaction with TWO owner signatures, delegatecalling
    ///      MultiSendCallOnly. This is the real ceremony, not vm.prank.
    function _safeExecBatch(bytes memory multiSendCall) internal returns (bool, bytes memory) {
        uint256 nonce = abi.decode(_staticcall(safe, abi.encodeWithSignature("nonce()")), (uint256));
        bytes32 txHash = abi.decode(
            _staticcall(
                safe,
                abi.encodeWithSignature(
                    "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)",
                    MULTISEND, uint256(0), multiSendCall, uint8(1), uint256(0), uint256(0), uint256(0),
                    address(0), address(0), nonce
                )
            ),
            (bytes32)
        );
        (uint8 v1, bytes32 r1, bytes32 s1) = vm.sign(PK_OWNER1, txHash);
        (uint8 v2, bytes32 r2, bytes32 s2) = vm.sign(PK_OWNER2, txHash);
        // Safe requires signatures ordered by ascending signer address; owner2 < owner1.
        bytes memory sigs = abi.encodePacked(r2, s2, v2, r1, s1, v1);
        return safe.call(
            abi.encodeWithSignature(
                "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)",
                MULTISEND, uint256(0), multiSendCall, uint8(1), uint256(0), uint256(0), uint256(0),
                address(0), address(0), sigs
            )
        );
    }

    function _staticcall(address target, bytes memory data) internal view returns (bytes memory) {
        (bool ok, bytes memory ret) = target.staticcall(data);
        require(ok, "staticcall failed");
        return ret;
    }

    // ================================================================== tests ====

    function test_DeploymentIsPausedAndCannotOperate() public {
        assertFalse(controller.active(), "a fresh controller must be paused");
        assertEq(controller.epoch(), 0);
        assertEq(controller.usedSupply(), 0, "Held starts its OWN history, not the native 30,000");

        HeldController.Envelope memory env = _envelope(keccak256("op-paused"), 1, 5_000e6, 0, runnerB);
        bytes memory sig_ = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.Paused.selector);
        controller.executeSupply(env, mp_, 5_000e6, sig_);
    }

    function test_SupplySucceedsAndConsumesExactly() public {
        _activate(1, runnerB);

        uint256 safeBefore = IERC20(USDC).balanceOf(safe);
        (uint256 shares0,,) = IMorpho(MORPHO).position(marketId, safe);
        (,,, uint128 rolesBefore,) = IRoles(roles).allowances(allowKey);

        _supply(keccak256("op-1"), 10_000e6, 1, PK_RUNNER_B, runnerB);

        assertEq(IERC20(USDC).balanceOf(safe), safeBefore - 10_000e6, "exact safe debit");
        (uint256 shares1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertGt(shares1, shares0, "supply shares increased");
        assertEq(controller.usedSupply(), 10_000e6, "controller counter");
        assertEq(controller.normalCount(), 1);
        assertEq(IERC20(USDC).allowance(safe, MORPHO), 0, "managed allowance ends at zero");

        // The economic budget is charged ONCE, on the protocol call -- the approval and
        // its cleanup must not double-charge it (V4 §5).
        (,,, uint128 rolesAfter,) = IRoles(roles).allowances(allowKey);
        assertEq(rolesBefore - rolesAfter, 10_000e6, "Roles allowance charged exactly once");
        assertEq(uint256(rolesAfter), controller.remainingSupply(), "controller and Roles agree");
    }

    function test_ReplayOfConsumedOperationIsRejected() public {
        _activate(1, runnerB);
        _supply(keccak256("op-replay"), 5_000e6, 1, PK_RUNNER_B, runnerB);

        HeldController.Envelope memory env = _envelope(keccak256("op-replay"), 1, 5_000e6, 1, runnerB);
        bytes memory sigR = _sign(env, PK_RUNNER_B);
        MarketParams memory mpR = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(
            abi.encodeWithSelector(HeldController.OperationConsumed.selector, keccak256("op-replay"))
        );
        controller.executeSupply(env, mpR, 5_000e6, sigR);
    }

    function test_PayloadMutationUnderSignedEnvelopeIsRejected() public {
        _activate(1, runnerB);
        HeldController.Envelope memory env = _envelope(keccak256("op-mutate"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        // Same signed envelope, different economic amount.
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.PayloadMismatch.selector);
        controller.executeSupply(env, _mp(), 9_000e6, sig);
    }

    function test_OnlyConfiguredExecutorMayCall() public {
        _activate(1, runnerB);
        HeldController.Envelope memory env = _envelope(keccak256("op-exec"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        vm.prank(address(0xBEEF));
        vm.expectRevert(HeldController.NotExecutor.selector);
        controller.executeSupply(env, _mp(), 5_000e6, sig);
    }

    /// @dev The decisive authority test: the transport sender is UNCHANGED, and the old
    ///      runner's key still exists. Only the epoch retired. V4 §3: "Old Runner A
    ///      credentials cannot become Runner B just by copying the new epoch number."
    function test_RetiredRunnerCannotExecuteEvenWithSameExecutor() public {
        _activate(1, runnerA);
        _supply(keccak256("op-a1"), 5_000e6, 1, PK_RUNNER_A, runnerA);

        vm.prank(safe);
        controller.fence();
        (,,, uint128 remaining,) = IRoles(roles).allowances(allowKey);
        vm.prank(safe);
        _setAllowance(remaining, LS); // owner keeps Roles consistent across the change
        _activate(2, runnerB);

        // A signs an envelope carrying the NEW epoch, submitted by the SAME executor.
        HeldController.Envelope memory env = _envelope(keccak256("op-a2"), 1, 5_000e6, 2, runnerA);
        bytes memory sig_ = _sign(env, PK_RUNNER_A);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.BadSignature.selector);
        controller.executeSupply(env, mp_, 5_000e6, sig_);

        // B, on the same epoch and same executor, works.
        _supply(keccak256("op-b1"), 5_000e6, 2, PK_RUNNER_B, runnerB);
        assertEq(controller.usedSupply(), 10_000e6, "consumption preserved across the handover");
    }

    function test_HoldIsNeverExecutable() public {
        _activate(1, runnerB);
        HeldController.Envelope memory env = _envelope(keccak256("op-hold"), 0, 0, 1, runnerB);
        bytes memory sig_ = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.HoldIsNotExecutable.selector);
        controller.executeSupply(env, mp_, 0, sig_);
    }

    function test_CeilingAndFloorAreEnforced() public {
        _activate(1, runnerB);

        // 1. Above the per-action maximum Ms (40,000).
        HeldController.Envelope memory tooBig = _envelope(keccak256("op-big"), 1, 45_000e6, 1, runnerB);
        bytes memory sigBig = _sign(tooBig, PK_RUNNER_B);
        MarketParams memory mpBig = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.AmountOutOfRange.selector);
        controller.executeSupply(tooBig, mpBig, 45_000e6, sigBig);

        // 2. Cumulative ceiling. Consume 40,000 of the 50,000 Ls, top the Safe back up so
        //    the cash floor cannot be what binds, then ask for 15,000.
        _supply(keccak256("op-ceil-setup"), 40_000e6, 1, PK_RUNNER_B, runnerB);
        assertEq(controller.usedSupply(), 40_000e6);
        _fundSafe(60_000e6);

        HeldController.Envelope memory overCeiling = _envelope(keccak256("op-ceil"), 1, 15_000e6, 1, runnerB);
        bytes memory sigCeil = _sign(overCeiling, PK_RUNNER_B);
        MarketParams memory mpCeil = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.CeilingExceeded.selector);
        controller.executeSupply(overCeiling, mpCeil, 15_000e6, sigCeil);

        // 3. Liquid cash floor. With 10,000 in the Safe and F = 1,000, only 9,000 is
        //    spendable; 9,500 is within Ms and within the remaining ceiling, so the
        //    floor is the only thing that can refuse it.
        _fundSafe(10_000e6);
        HeldController.Envelope memory floorBreak = _envelope(keccak256("op-floor"), 1, 9_500e6, 1, runnerB);
        bytes memory sigFloor = _sign(floorBreak, PK_RUNNER_B);
        MarketParams memory mpFloor = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.FloorViolated.selector);
        controller.executeSupply(floorBreak, mpFloor, 9_500e6, sigFloor);
    }

    /// @dev THE activation-consistency case, with the exact numbers from the review:
    ///      after Held has verified 35,000 of consumption, an 80,000 ceiling is only
    ///      consistent with 45,000 remaining. A stale 50,000 must be refused.
    function test_ActivationRefusesStaleAllowanceAndAcceptsConsistentOne() public {
        _activate(1, runnerB);
        _supply(keccak256("op-35a"), 20_000e6, 1, PK_RUNNER_B, runnerB);
        _supply(keccak256("op-35b"), 15_000e6, 1, PK_RUNNER_B, runnerB);
        assertEq(controller.usedSupply(), 35_000e6, "Held verified 35,000 of its OWN consumption");

        vm.prank(safe);
        controller.fence();

        HeldController.Policy memory p = _policy();
        p.Ls = 80_000e6;
        // Every OTHER dimension is made consistent, so the supply amount is the only
        // variable and the guard's verdict is unambiguous.
        vm.startPrank(safe);
        _syncNonSupply(p);
        vm.stopPrank();

        // The naive value: 80,000 - 30,000, i.e. computed from a stale Used figure.
        vm.prank(safe);
        _setAllowance(50_000e6, 80_000e6);
        HeldController.ExpectedState memory e2 = _expected();
        vm.prank(safe);
        vm.expectRevert(
            abi.encodeWithSelector(HeldController.AllowanceDesynchronised.selector, 50_000e6, 45_000e6)
        );
        controller.activate(2, 2, runnerB, EXECUTOR, p, e2);

        // The consistent value.
        vm.prank(safe);
        _setAllowance(45_000e6, 80_000e6);
        HeldController.ExpectedState memory e3 = _expected();
        vm.prank(safe);
        controller.activate(2, 2, runnerB, EXECUTOR, p, e3);
        assertTrue(controller.active());
        assertEq(controller.remainingSupply(), 45_000e6, "80,000 ceiling minus 35,000 consumed");
    }

    function test_CeilingBelowConsumptionIsRejected() public {
        _activate(1, runnerB);
        _supply(keccak256("op-c1"), 20_000e6, 1, PK_RUNNER_B, runnerB);
        vm.prank(safe);
        controller.fence();

        HeldController.Policy memory p = _policy();
        p.Ls = 10_000e6; // below the 20,000 already consumed
        HeldController.ExpectedState memory e1 = _expected();
        vm.prank(safe);
        vm.expectRevert(HeldController.CeilingBelowConsumption.selector);
        controller.activate(2, 2, runnerB, EXECUTOR, p, e1);
    }

    function test_StaleExpectedStateIsRejected() public {
        _activate(1, runnerB);
        HeldController.ExpectedState memory snapshot = _expected(); // taken BEFORE the supply
        _supply(keccak256("op-stale"), 5_000e6, 1, PK_RUNNER_B, runnerB);

        vm.prank(safe);
        controller.fence();
        vm.prank(safe);
        vm.expectRevert(HeldController.StaleActivation.selector);
        controller.activate(2, 2, runnerB, EXECUTOR, _policy(), snapshot);
    }

    function test_OnlyOwnerMayActivateOrFence() public {
        HeldController.Policy memory p0 = _policy();
        HeldController.ExpectedState memory e0 = _expected();
        vm.prank(address(0xBEEF));
        vm.expectRevert(HeldController.NotOwner.selector);
        controller.activate(1, 1, runnerB, EXECUTOR, p0, e0);

        _activate(1, runnerB);
        vm.prank(address(0xBEEF));
        vm.expectRevert(HeldController.NotOwner.selector);
        controller.fence();
    }

    /// @dev PRECISE FAILURE STAGE: Roles refuses PERMISSION for the Morpho call, because
    ///      the quota is set below the requested amount. Morpho itself is never entered,
    ///      so this is NOT evidence that the economic action executed and then failed.
    ///      The cleanup-failure branch -- approval succeeds, the economic action runs,
    ///      THEN cleanup fails -- is covered separately in
    ///      test/contracts/adversarial/HeldControllerAdversarial.t.sol.
    function test_RolesRefusalBeforeMorphoRollsBackEverything() public {
        _activate(1, runnerB);

        vm.prank(safe);
        _setAllowance(1_000e6, LS); // quota now smaller than the action

        uint256 safeBefore = IERC20(USDC).balanceOf(safe);
        (uint256 shares0,,) = IMorpho(MORPHO).position(marketId, safe);

        HeldController.Envelope memory env = _envelope(keccak256("op-rollback"), 1, 5_000e6, 1, runnerB);
        bytes memory sig_ = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert();
        controller.executeSupply(env, mp_, 5_000e6, sig_);

        assertEq(IERC20(USDC).balanceOf(safe), safeBefore, "no token moved");
        (uint256 shares1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertEq(shares1, shares0, "no shares minted");
        assertEq(controller.usedSupply(), 0, "counter not advanced");
        assertEq(controller.normalCount(), 0, "count not advanced");
        assertFalse(controller.isConsumed(keccak256("op-rollback")), "operation id NOT consumed");
        assertEq(shares1, shares0, "Morpho was never entered: position identical");
        assertEq(IERC20(USDC).allowance(safe, MORPHO), 0, "no residual approval");
    }

    function test_WithdrawReturnsToSafeAndDecreasesShares() public {
        _activate(1, runnerB);
        _supply(keccak256("op-w0"), 10_000e6, 1, PK_RUNNER_B, runnerB);

        uint256 safeBefore = IERC20(USDC).balanceOf(safe);
        (uint256 shares0,,) = IMorpho(MORPHO).position(marketId, safe);

        HeldController.Envelope memory env = _envelope(keccak256("op-w1"), 2, 2_000e6, 1, runnerB);
        bytes memory sig_ = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        controller.executeWithdraw(env, mp_, 2_000e6, sig_);

        assertEq(IERC20(USDC).balanceOf(safe), safeBefore + 2_000e6, "exact safe receipt");
        (uint256 shares1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertLt(shares1, shares0, "supply shares decreased");
        assertEq(controller.usedNormalWithdraw(), 2_000e6);
        assertEq(controller.usedSupply(), 10_000e6, "withdrawal never refills supply capacity");
    }

    function test_WrongEpochIsRejected() public {
        _activate(1, runnerB);
        HeldController.Envelope memory env = _envelope(keccak256("op-epoch"), 1, 5_000e6, 99, runnerB);
        bytes memory sig_ = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(abi.encodeWithSelector(HeldController.WrongEpoch.selector, uint64(99), uint64(1)));
        controller.executeSupply(env, mp_, 5_000e6, sig_);
    }

    /// @dev V4 §3 requires a reviewed library rather than hand-written ecrecover.
    ///      OpenZeppelin's ECDSA rejects the high-s counterpart of a valid signature, so
    ///      a malleated signature cannot be replayed as a second distinct authorization.
    function test_MalleableSignatureIsRejected() public {
        _activate(1, runnerB);
        HeldController.Envelope memory env = _envelope(keccak256("op-malleable"), 1, 5_000e6, 1, runnerB);
        (uint8 v, bytes32 r, bytes32 sSig) = vm.sign(PK_RUNNER_B, controller.signingHash(env));

        // s' = n - s, v flipped: the classic malleable twin of the same signature.
        uint256 n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
        bytes32 sMalleated = bytes32(n - uint256(sSig));
        uint8 vFlipped = v == 27 ? 28 : 27;
        bytes memory bad = abi.encodePacked(r, sMalleated, vFlipped);
        MarketParams memory mp_ = _mp();

        vm.prank(EXECUTOR);
        vm.expectRevert(); // ECDSA rejects high-s before the controller ever compares signers
        controller.executeSupply(env, mp_, 5_000e6, bad);

        // The honest counterpart: the ORIGINAL signature still works.
        bytes memory good = abi.encodePacked(r, sSig, v);
        vm.prank(EXECUTOR);
        controller.executeSupply(env, mp_, 5_000e6, good);
        assertEq(controller.usedSupply(), 5_000e6);
    }

    // ------------------------------------------- cooldowns and lane separation --

    /// @dev V4 §5: SUPPLY and NORMAL WITHDRAW share the normal count and timestamp;
    ///      restoration has its own. The worked case: the floor is 1,000, cash has
    ///      fallen to 200, and NORMAL capacity is exhausted -- a restoration withdrawal
    ///      of up to the 800 shortfall must still be possible on its own budget.
    function test_RestorationLaneIsIndependentOfExhaustedNormalCapacity() public {
        HeldController.Policy memory p = _policyWith(1, 0, 0); // Nn = 1: one normal op only
        _activateWith(1, runnerB, p);

        _supply(keccak256("op-r-supply"), 5_000e6, 1, PK_RUNNER_B, runnerB);
        assertEq(controller.normalCount(), 1, "normal count now exhausted");

        // Cash falls below the floor.
        _fundSafe(200e6);

        // A normal withdrawal is impossible: the count is spent. Prove it by asking for
        // an amount the restoration lane would also refuse, so only the lane matters.
        HeldController.Envelope memory tooMuch = _envelope(keccak256("op-r-over"), 2, 5_000e6, 1, runnerB);
        bytes memory sigOver = _sign(tooMuch, PK_RUNNER_B);
        MarketParams memory mpOver = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.AmountOutOfRange.selector); // > F - B = 800
        controller.executeWithdraw(tooMuch, mpOver, 5_000e6, sigOver);

        // Restoration of exactly the 800 shortfall succeeds on its OWN count and budget.
        (,,, uint128 restoreBefore,) = IRoles(roles).allowances(RESTORE_KEY);
        (,,, uint128 normalWithdrawBefore,) = IRoles(roles).allowances(WITHDRAW_KEY);

        HeldController.Envelope memory env = _envelope(keccak256("op-restore"), 2, 800e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        controller.executeWithdraw(env, mp_, 800e6, sig);

        assertEq(IERC20(USDC).balanceOf(safe), 1_000e6, "restored exactly to the floor");
        assertEq(controller.usedRestoration(), 800e6, "restoration counter");
        assertEq(controller.restorationCount(), 1);
        assertEq(controller.usedNormalWithdraw(), 0, "normal withdraw budget untouched");
        assertEq(controller.normalCount(), 1, "normal count unchanged by a restoration");

        (,,, uint128 restoreAfter,) = IRoles(roles).allowances(RESTORE_KEY);
        (,,, uint128 normalWithdrawAfter,) = IRoles(roles).allowances(WITHDRAW_KEY);
        assertEq(restoreBefore - restoreAfter, 800e6, "restoration key charged");
        assertEq(normalWithdrawAfter, normalWithdrawBefore, "normal key NOT charged");
    }

    function test_CooldownBlocksThenAllows() public {
        HeldController.Policy memory p = _policyWith(10, 3600, 0); // dn = 1 hour
        _activateWith(1, runnerB, p);

        _supply(keccak256("op-cd1"), 5_000e6, 1, PK_RUNNER_B, runnerB);
        uint64 stamped = controller.lastNormalAt();
        assertEq(stamped, uint64(block.timestamp));

        // One second before the cooldown expires.
        vm.warp(block.timestamp + 3599);
        HeldController.Envelope memory early = _envelope(keccak256("op-cd2"), 1, 5_000e6, 1, runnerB);
        bytes memory sigE = _sign(early, PK_RUNNER_B);
        MarketParams memory mpE = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.CooldownActive.selector);
        controller.executeSupply(early, mpE, 5_000e6, sigE);

        // A refused operation must NOT advance the successful-operation timestamp.
        assertEq(controller.lastNormalAt(), stamped, "failed op advanced the timestamp");
        assertEq(controller.usedSupply(), 5_000e6, "failed op advanced consumption");

        // Exactly at the boundary it is permitted.
        vm.warp(block.timestamp + 1);
        _supply(keccak256("op-cd3"), 5_000e6, 1, PK_RUNNER_B, runnerB);
        assertEq(controller.usedSupply(), 10_000e6);
        assertGt(controller.lastNormalAt(), stamped);
    }

    function test_TimestampsAndConsumptionSurviveRunnerAndPolicyChange() public {
        HeldController.Policy memory p = _policyWith(10, 3600, 0);
        _activateWith(1, runnerA, p);
        _supply(keccak256("op-ts1"), 5_000e6, 1, PK_RUNNER_A, runnerA);

        uint64 stamped = controller.lastNormalAt();
        uint128 used = controller.usedSupply();

        vm.prank(safe);
        controller.fence();
        (,,, uint128 remaining,) = IRoles(roles).allowances(allowKey);
        vm.prank(safe);
        _setAllowance(remaining, LS);
        HeldController.Policy memory p2 = _policyWith(10, 7200, 0); // new cooldown, new epoch
        _activateWith(2, runnerB, p2);

        assertEq(controller.lastNormalAt(), stamped, "timestamp preserved across handover");
        assertEq(controller.usedSupply(), used, "consumption preserved across handover");
        assertEq(controller.restorationCount(), 0);
    }

    // ------------------------------------------- atomic owner activation batch --

    /// @dev The owner updates the Roles allowance AND activates in ONE Safe transaction,
    ///      via MultiSendCallOnly delegatecall with two genuine owner signatures. If the
    ///      activation guard rejects, the allowance update in the same batch must roll
    ///      back too -- otherwise a failed activation would leave Roles rewritten.
    function test_OwnerBatchActivationIsAtomicAndRollsBackAllowance() public {
        _activate(1, runnerB);
        _supply(keccak256("op-batch"), 20_000e6, 1, PK_RUNNER_B, runnerB);
        vm.prank(safe);
        controller.fence();

        (,,, uint128 before,) = IRoles(roles).allowances(allowKey);
        assertEq(before, 30_000e6, "50,000 ceiling less 20,000 consumed");

        HeldController.Policy memory p = _policy();
        p.Ls = 80_000e6;
        vm.startPrank(safe);
        _syncNonSupply(p);
        vm.stopPrank();
        HeldController.ExpectedState memory exp = _expected();

        // STALE: the expected state claims no consumption. The batch must revert whole.
        HeldController.ExpectedState memory stale;
        bytes memory badBatch = _batch(
            abi.encodeWithSignature(
                "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)", allowKey, uint128(60_000e6), uint128(80_000e6), uint128(0), uint64(0), uint64(0)
            ),
            abi.encodeCall(HeldController.activate, (2, 2, runnerB, EXECUTOR, p, stale))
        );
        (bool okBad,) = _safeExecBatch(badBatch);
        assertFalse(okBad, "stale activation batch must fail");
        (,,, uint128 afterBad,) = IRoles(roles).allowances(allowKey);
        assertEq(afterBad, before, "the allowance update rolled back with the batch");
        assertFalse(controller.active(), "controller stays paused");

        // CONSISTENT: 80,000 ceiling less 20,000 consumed = 60,000.
        bytes memory goodBatch = _batch(
            abi.encodeWithSignature(
                "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)", allowKey, uint128(60_000e6), uint128(80_000e6), uint128(0), uint64(0), uint64(0)
            ),
            abi.encodeCall(HeldController.activate, (2, 2, runnerB, EXECUTOR, p, exp))
        );
        (bool okGood,) = _safeExecBatch(goodBatch);
        assertTrue(okGood, "consistent activation batch succeeds");
        assertTrue(controller.active());
        assertEq(controller.remainingSupply(), 60_000e6);
    }

    /// @dev The native COUNT allowance must be CONSUMED by the economic call, not merely
    ///      checked at activation. Without a CallWithinAllowance node it would sit at its
    ///      ceiling forever while the controller's own count advanced.
    function test_NativeCountAllowanceIsConsumedByTheEconomicCall() public {
        _activate(1, runnerB);
        (,,, uint128 countBefore,) = IRoles(roles).allowances(NORMAL_COUNT_KEY);
        (,,, uint128 restoreCountBefore,) = IRoles(roles).allowances(RESTORE_COUNT_KEY);

        _supply(keccak256("op-count"), 5_000e6, 1, PK_RUNNER_B, runnerB);

        (,,, uint128 countAfter,) = IRoles(roles).allowances(NORMAL_COUNT_KEY);
        (,,, uint128 restoreCountAfter,) = IRoles(roles).allowances(RESTORE_COUNT_KEY);
        assertEq(countBefore - countAfter, 1, "normal count allowance charged exactly once");
        assertEq(restoreCountAfter, restoreCountBefore, "restoration count must not move");
        assertEq(uint256(countAfter), uint256(_policy().Nn) - controller.normalCount(),
            "native count and controller count agree");
    }

    /// @dev THE independent-defence test. It bypasses the controller entirely: a role
    ///      MEMBER calls Roles directly with bad arguments. If Roles admits these, the
    ///      native layer is not restricting anything and the controller is the only
    ///      defence -- which is exactly what V4 §5 says it must not be.
    ///
    ///      The caller is an EOA temporarily assigned to the role rather than the
    ///      controller: conditions are per-role, so this exercises the same tree, and
    ///      pranking a contract address produced zero-gas frames under --fork-url.
    ///
    ///      Each refusal asserts the SPECIFIC Roles condition error (0xd0a9bf58
    ///      ConditionViolation), so "Roles refused" is distinguished from "Morpho
    ///      reverted later".
    function test_RolesIndependentlyRefusesBadArgumentsFromARoleMember() public {
        _activate(1, runnerB);
        _supply(keccak256("op-indep-setup"), 10_000e6, 1, PK_RUNNER_B, runnerB);

        vm.prank(safe);
        _assign(runnerA, roleKey, true); // an EOA member, purely to probe the conditions
        address stranger = address(0xDEAD);

        _expectRolesRefusal(
            abi.encodeCall(IMorpho.withdraw, (_mp(), 1_000e6, 0, safe, stranger)),
            "withdraw to a foreign recipient");
        _expectRolesRefusal(
            abi.encodeCall(IMorpho.withdraw, (_mp(), 1_000e6, 0, stranger, safe)),
            "withdraw onBehalf of a stranger");
        _expectRolesRefusal(
            abi.encodeCall(IMorpho.withdraw, (_mp(), 0, 5, safe, safe)),
            "shares-denominated withdraw");
        MarketParams memory other = _mp();
        other.lltv = 770000000000000000;
        _expectRolesRefusal(
            abi.encodeCall(IMorpho.withdraw, (other, 1_000e6, 0, safe, safe)),
            "foreign market");

        // CONTROL: the well-formed call is admitted, so the refusals above are real
        // decisions and not a blanket rejection.
        vm.prank(runnerA);
        (bool ok,) = roles.call(abi.encodeWithSignature(
            "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
            MORPHO, uint256(0), abi.encodeCall(IMorpho.withdraw, (_mp(), 1_000e6, 0, safe, safe)),
            uint8(0), roleKey, true));
        assertTrue(ok, "Roles refused a well-formed withdraw: the negatives prove nothing");
    }

    /// @dev Assert Roles refuses with its own ConditionViolation, not some later failure.
    function _expectRolesRefusal(bytes memory inner, string memory what) internal {
        vm.prank(runnerA);
        (bool ok, bytes memory ret) = roles.call(abi.encodeWithSignature(
            "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
            MORPHO, uint256(0), inner, uint8(0), roleKey, true));
        assertFalse(ok, string.concat("Roles ADMITTED: ", what));
        assertEq(bytes4(ret), bytes4(0xd0a9bf58),
            string.concat("refused, but not by a Roles condition: ", what));
    }

    /// @dev THE operating-synchronisation regression. Activation is correct, then the
    ///      native quota DRIFTS upward with plenty of capacity left, so a quota shortage
    ///      cannot be the reason for refusal. Without an operating check the supply would
    ///      succeed and leave native remaining at 55,000 while the controller believed
    ///      45,000.
    function test_OperatingDriftInTheNativeQuotaIsRefused() public {
        _activate(1, runnerB);
        (,,, uint128 remaining,) = IRoles(roles).allowances(allowKey);
        assertEq(remaining, LS, "starts synchronised");

        vm.prank(safe);
        _setAllowance(60_000e6, 80_000e6); // drift UP: capacity is not the constraint

        HeldController.Envelope memory env = _envelope(keccak256("op-drift"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(abi.encodeWithSelector(
            HeldController.AllowanceDesynchronised.selector, uint256(60_000e6), uint256(LS)));
        controller.executeSupply(env, mp_, 5_000e6, sig);

        assertEq(controller.usedSupply(), 0, "nothing consumed under drift");

        // Restore agreement and replay the SAME envelope and signature. Using a new
        // operation id here would have made this a weaker claim than the comment said.
        vm.prank(safe);
        _setAllowance(LS, LS);
        vm.prank(EXECUTOR);
        controller.executeSupply(env, mp_, 5_000e6, sig);
        assertEq(controller.usedSupply(), 5_000e6, "the SAME operation succeeded after repair");
        assertTrue(controller.isConsumed(keccak256("op-drift")));
    }

    /// @dev Drift in a COUNT quota is refused on the same footing as an amount quota.
    function test_OperatingDriftInTheNativeCountIsRefused() public {
        _activate(1, runnerB);
        vm.prank(safe);
        IRolesAdmin(roles).setAllowance(NORMAL_COUNT_KEY, 7, 10, 0, 0, 0); // drift, still plenty

        HeldController.Envelope memory env = _envelope(keccak256("op-cdrift"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(abi.encodeWithSelector(
            HeldController.AllowanceDesynchronised.selector, uint256(7), uint256(10)));
        controller.executeSupply(env, mp_, 5_000e6, sig);
    }

    /// @dev A stored balance that matches today does not mean the quota cannot accrue
    ///      tomorrow. Roles keeps refill and period separately; a refilling quota is
    ///      outside the admitted non-refilling profile and is refused at BOTH boundaries.
    function test_RefillingAllowanceIsRefusedAtActivationAndAtOperatingTime() public {
        // operating time: activate clean, then make the quota refilling
        _activate(1, runnerB);
        vm.prank(safe);
        IRolesAdmin(roles).setAllowance(allowKey, LS, LS, 1, 3600, 0); // balance still matches

        HeldController.Envelope memory env = _envelope(keccak256("op-refill"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(abi.encodeWithSelector(
            HeldController.AllowanceRefillsNotPermitted.selector, allowKey, uint128(1), uint64(3600)));
        controller.executeSupply(env, mp_, 5_000e6, sig);

        // activation: same configuration must not be admitted either
        vm.prank(safe);
        controller.fence();
        HeldController.Policy memory p = _policy();
        HeldController.ExpectedState memory exp = _expected();
        vm.prank(safe);
        vm.expectRevert(abi.encodeWithSelector(
            HeldController.AllowanceRefillsNotPermitted.selector, allowKey, uint128(1), uint64(3600)));
        controller.activate(2, 2, runnerB, EXECUTOR, p, exp);
    }

    /// @dev The approval bound and empty-callback restriction at the ROLES layer,
    ///      exercised directly by a role member with the controller out of the picture.
    function test_RolesIndependentlyBoundsApprovalAndRequiresEmptyCallback() public {
        _activate(1, runnerB);
        vm.prank(safe);
        _assign(runnerA, roleKey, true);

        // excessive approval
        vm.prank(runnerA);
        (bool okBig, bytes memory retBig) = roles.call(abi.encodeWithSignature(
            "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
            USDC, uint256(0), abi.encodeCall(IERC20.approve, (MORPHO, type(uint256).max)),
            uint8(0), roleKey, true));
        assertFalse(okBig, "Roles admitted an unlimited approval");
        assertEq(bytes4(retBig), bytes4(0xd0a9bf58),
            "approval refused, but not by a Roles condition");

        // non-empty callback on the economic call
        bytes memory withCallback = abi.encodeCall(
            IMorpho.supply, (_mp(), 1_000e6, 0, safe, hex"01"));
        vm.prank(runnerA);
        (bool okCb, bytes memory retCb) = roles.call(abi.encodeWithSignature(
            "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
            MORPHO, uint256(0), withCallback, uint8(0), roleKey, true));
        assertFalse(okCb, "Roles admitted a non-empty callback");
        assertEq(bytes4(retCb), bytes4(0xd0a9bf58), "callback refused, but not by a Roles condition");

        // CONTROLS: a bounded approval and an empty callback are admitted.
        vm.prank(runnerA);
        (bool okOk,) = roles.call(abi.encodeWithSignature(
            "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
            USDC, uint256(0), abi.encodeCall(IERC20.approve, (MORPHO, 1_000e6)),
            uint8(0), roleKey, true));
        assertTrue(okOk, "Roles refused a bounded approval: the negatives prove nothing");
        vm.prank(runnerA);
        (bool okZero,) = roles.call(abi.encodeWithSignature(
            "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
            USDC, uint256(0), abi.encodeCall(IERC20.approve, (MORPHO, 0)),
            uint8(0), roleKey, true));
        assertTrue(okZero, "cleanup approve(0) must stay permitted");
    }

    /// @dev CROSS-LANGUAGE check. The vector in fixtures/crosslang-vectors.json is
    ///      produced by the Python adapter from the REAL pinned compiler's output; this
    ///      asserts the DEPLOYED controller computes the same actionHash. Until now the
    ///      Python test recomputed the hash with the same ABI library, which only ever
    ///      proved Python agreed with itself.
    function test_ControllerActionHashMatchesTheAdapterVector() public view {
        string memory raw = vm.readFile("fixtures/crosslang-vectors.json");
        uint8 family = uint8(vm.parseJsonUint(raw, ".family"));
        bytes32 market = vm.parseJsonBytes32(raw, ".marketId");
        address asset = vm.parseJsonAddress(raw, ".asset");
        uint256 amount = vm.parseUint(vm.parseJsonString(raw, ".amount"));
        address onBehalf = vm.parseJsonAddress(raw, ".onBehalf");
        bytes32 expected = vm.parseJsonBytes32(raw, ".expectedActionHash");

        assertEq(
            controller.actionHash(family, market, asset, amount, onBehalf),
            expected,
            "the deployed controller and the Python adapter disagree on actionHash"
        );
    }

    /// @dev P02 required work 7: exact token/share rounding.
    ///
    ///      Morpho reports the (assets, shares) it actually moved -- fixed-asset supply
    ///      rounds shares DOWN and fixed-asset withdraw rounds them UP, both after
    ///      accruing interest. The controller now binds that report to the observed
    ///      position change, so this exercises the relation across amounts where the
    ///      conversion is not exact, and after interest has accrued.
    function test_ExactShareAccountingHoldsAcrossRoundingBoundaries() public {
        _activate(1, runnerB);

        uint256[4] memory amounts = [uint256(1_000e6), 1_000e6 + 1, 3_333_333_333, 7_777e6];
        uint256 totalSupplied;
        for (uint256 i = 0; i < amounts.length; i++) {
            // Let interest accrue between operations so the conversion ratio moves and a
            // stale pre-accrual ratio could not satisfy the check.
            vm.warp(block.timestamp + 6 hours);
            vm.roll(block.number + 1);

            (uint256 before,,) = IMorpho(MORPHO).position(marketId, safe);
            uint256 safeBefore = IERC20(USDC).balanceOf(safe);
            _supply(keccak256(abi.encode("round", i)), amounts[i], 1, PK_RUNNER_B, runnerB);
            (uint256 afterShares,,) = IMorpho(MORPHO).position(marketId, safe);

            // Token side is exact; share side is whatever Morpho reported, and the
            // controller already refused any disagreement.
            assertEq(safeBefore - IERC20(USDC).balanceOf(safe), amounts[i], "exact token debit");
            assertGt(afterShares, before, "shares minted");
            totalSupplied += amounts[i];
        }
        assertEq(controller.usedSupply(), totalSupplied);

        // Withdraw on the normal lane, again after accrual.
        vm.warp(block.timestamp + 12 hours);
        vm.roll(block.number + 1);
        (uint256 s0,,) = IMorpho(MORPHO).position(marketId, safe);
        uint256 b0 = IERC20(USDC).balanceOf(safe);

        HeldController.Envelope memory env = _envelope(keccak256("round-w"), 2, 1_234_567_891, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        controller.executeWithdraw(env, mp_, 1_234_567_891, sig);

        (uint256 s1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertEq(IERC20(USDC).balanceOf(safe) - b0, 1_234_567_891, "exact token receipt");
        assertLt(s1, s0, "shares burned");
        assertEq(controller.usedNormalWithdraw(), 1_234_567_891);

        // The RESTORATION lane runs the same share contract on different quota keys, so
        // it is exercised too rather than assumed equivalent. A non-round shortfall keeps
        // the asset->share conversion inexact.
        _fundSafe(137_654_321);
        vm.warp(block.timestamp + 3 hours);
        vm.roll(block.number + 1);
        uint256 shortfall = 1_000e6 - 137_654_321;
        (uint256 r0,,) = IMorpho(MORPHO).position(marketId, safe);

        HeldController.Envelope memory renv = _envelope(keccak256("round-r"), 2, shortfall, 1, runnerB);
        bytes memory rsig = _sign(renv, PK_RUNNER_B);
        MarketParams memory rmp = _mp();
        vm.prank(EXECUTOR);
        controller.executeWithdraw(renv, rmp, shortfall, rsig);

        (uint256 r1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertEq(IERC20(USDC).balanceOf(safe), 1_000e6, "restored exactly to the floor");
        assertEq(controller.usedRestoration(), shortfall, "restoration lane counter");
        assertLt(r1, r0, "restoration burned shares");
    }

    /// @dev The report must BIND to the observation, not merely be decoded.
    ///
    ///      Driven against the real controller on the real fork. `vm.mockCall` is used
    ///      only to make the position READBACK disagree with Morpho's truthful report --
    ///      the supply itself really executes and really moves USDC. This is a labelled
    ///      cheat-code fixture, not native Morpho behaviour.
    function test_ReportedSharesMustEqualTheObservedPositionChange() public {
        _activate(1, runnerB);

        // Readback pinned to a constant, so the observed delta is 0 while Morpho
        // truthfully reports the shares it minted.
        vm.mockCall(
            MORPHO,
            abi.encodeWithSelector(IMorpho.position.selector, marketId, safe),
            abi.encode(uint256(777), uint128(0), uint128(0))
        );

        uint256 balBefore = IERC20(USDC).balanceOf(safe);
        HeldController.Envelope memory env = _envelope(keccak256("op-lie"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        // Selector-only match: the reported share count depends on live market state, but
        // a bare expectRevert() would have accepted a revert for ANY other reason.
        vm.expectPartialRevert(HeldController.ReportedEffectMismatch.selector);
        controller.executeSupply(env, mp_, 5_000e6, sig);
        vm.clearMockedCalls();

        // The refusal rolled EVERYTHING back: tokens, native quota, counters and the
        // operation id. A half-applied failure is the outcome this whole design exists
        // to prevent, so it is asserted rather than assumed.
        assertEq(IERC20(USDC).balanceOf(safe), balBefore, "token effect not rolled back");
        assertEq(controller.usedSupply(), 0, "counter moved on a refused operation");
        assertEq(controller.normalCount(), 0, "count moved on a refused operation");
        assertEq(controller.isConsumed(keccak256("op-lie")), false, "id consumed by a refusal");
        (,,, uint128 quotaAfter,) = IRoles(roles).allowances(allowKey);
        assertEq(uint256(quotaAfter), uint256(LS), "native quota consumed by a refusal");

        // Without the mock the SAME operation succeeds, so the refusal above was the
        // disagreement and not a broken path.
        vm.prank(EXECUTOR);
        controller.executeSupply(env, mp_, 5_000e6, sig);
        assertEq(controller.usedSupply(), 5_000e6);
    }

    /// @dev A return that is not two words is refused before anything is inferred from
    ///      it. Reached ahead of the debit check because the decode happens on the raw
    ///      returndata. Labelled cheat-code fixture, not native Morpho behaviour.
    function test_MalformedEconomicReturnIsRefusedBeforeAnyInference() public {
        _activate(1, runnerB);
        uint256 balBefore = IERC20(USDC).balanceOf(safe);

        vm.mockCall(
            MORPHO,
            abi.encodeWithSelector(IMorpho.supply.selector),
            abi.encode(uint256(5_000e6)) // one word where the ABI promises two
        );
        HeldController.Envelope memory env = _envelope(keccak256("op-shape"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectRevert(abi.encodeWithSelector(HeldController.UnexpectedReturnShape.selector, uint256(32)));
        controller.executeSupply(env, mp_, 5_000e6, sig);
        vm.clearMockedCalls();

        assertEq(IERC20(USDC).balanceOf(safe), balBefore);
        assertEq(controller.usedSupply(), 0);
        assertEq(controller.isConsumed(keccak256("op-shape")), false);
    }

    function test_ForeignMarketIsRejected() public {
        _activate(1, runnerB);
        MarketParams memory other = _mp();
        other.lltv = 770000000000000000; // a different, real-shaped market
        uint256 amount = 5_000e6;

        HeldController.Envelope memory env = _envelope(keccak256("op-market"), 1, amount, 1, runnerB);
        env.payloadHash = controller.actionHash(1, keccak256(abi.encode(other)), USDC, amount, safe);
        bytes memory sig_ = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = other;
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.WrongScope.selector);
        controller.executeSupply(env, mp_, amount, sig_);
    }
}


