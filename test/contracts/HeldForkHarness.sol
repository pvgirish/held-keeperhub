// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test, console2} from "forge-std/Test.sol";

import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {HeldController} from "../../contracts/src/HeldController.sol";
import {ConditionFlat, IERC20, IMorpho, IRoles, IRolesAdmin, IRolesTargets, MarketParams} from "../../contracts/src/Interfaces.sol";

/// @notice Shared fork harness: the REAL pinned Base-mainnet fixture.
///
/// These run against a live anvil fork that fixtures/scripts/01..03b has already
/// populated with a genuine 2-of-3 Safe and a Zodiac Roles module, so the Safe,
/// Roles, Morpho, USDC and market are all real code — nothing is mocked. The Safe's
/// owner authority is exercised with `vm.prank(safe)`; the real two-signature
/// ceremony is separately evidenced in P00 and is not re-proven here.
/// @dev Abstract, so forge does not run it as a suite. It holds the fixture wiring and
///      the helpers that both the P02 controller suite and the P04 authority suite need;
///      duplicating ~350 lines of fixture setup into a second file would have let the
///      two drift apart silently.
abstract contract HeldForkHarness is Test {
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

}
