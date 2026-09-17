// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test, console2} from "forge-std/Test.sol";

import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {HeldController} from "../../contracts/src/HeldController.sol";
import {HeldInstall} from "../../contracts/src/install/HeldInstall.sol";
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
    // Taken from HeldInstall rather than restated, so the configuration these tests
    // exercise and the configuration a deployment installs cannot drift apart.
    address constant MORPHO = HeldInstall.MORPHO;
    address constant USDC = HeldInstall.USDC;
    address constant COLL = HeldInstall.COLL;
    address constant ORACLE = HeldInstall.ORACLE;
    address constant IRM = HeldInstall.IRM;
    uint256 constant LLTV = HeldInstall.LLTV;
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
    bytes32 constant LINEAGE = HeldInstall.LINEAGE;

    bytes32 constant WITHDRAW_KEY = HeldInstall.WITHDRAW_KEY;
    bytes32 constant RESTORE_ROLE = HeldInstall.RESTORE_ROLE;
    bytes32 constant RESTORE_KEY = HeldInstall.RESTORE_KEY;
    bytes32 constant NORMAL_COUNT_KEY = HeldInstall.NORMAL_COUNT_KEY;
    bytes32 constant RESTORE_COUNT_KEY = HeldInstall.RESTORE_COUNT_KEY;
    uint128 constant LN = HeldInstall.LN;
    uint128 constant LR = HeldInstall.LR;
    uint128 constant LS = HeldInstall.LS;
    uint128 constant MS = HeldInstall.MS;

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

        // THE installation, from the one definition of it. Previously this block spelled
        // the whole thing out here, which is why the pre-activation deployment helper was
        // able to install something else entirely and nobody noticed.
        vm.startPrank(safe);
        HeldInstall.install(
            HeldInstall.Params({
                safe: safe,
                roles: roles,
                controller: address(controller),
                retireMember: runnerA,
                normalRole: roleKey,
                supplyKey: allowKey
            })
        );
        vm.stopPrank();

        _fundSafe(50_000e6);
    }

    // ------------------------------------------------------------------ helpers --
    function _mp() internal pure returns (MarketParams memory) {
        return MarketParams({loanToken: USDC, collateralToken: COLL, oracle: ORACLE, irm: IRM, lltv: LLTV});
    }

    function _assign(address who, bytes32 key, bool member) internal {
        HeldInstall.assign(roles, who, key, member);
    }

    function _setAllowance(uint128 balance, uint128 maxRefill) internal {
        (bool ok,) = roles.call(
            abi.encodeWithSignature(
                "setAllowance(bytes32,uint128,uint128,uint128,uint64,uint64)", allowKey, balance, maxRefill, 0, 0, 0
            )
        );
        require(ok, "setAllowance failed");
    }

    /// @dev The supply, withdraw and approval condition trees, and the CallWithinAllowance
    ///      insertion, now live in HeldInstall -- one definition, used by this harness and
    ///      by the pre-activation deployment alike.
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
