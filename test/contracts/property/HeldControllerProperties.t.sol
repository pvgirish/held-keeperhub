// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {HeldController} from "../../../contracts/src/HeldController.sol";
import {MarketParams} from "../../../contracts/src/Interfaces.sol";
import {MockMorpho, MockRoles, MockToken} from "../adversarial/Adversarial.sol";

/// @notice PROPERTY / FUZZ suite for the controller's policy arithmetic.
///
/// The example-based fork suite proves specific cases against the real pinned contracts.
/// This suite asks a different question: does the implementation agree with an
/// INDEPENDENT reference predicate across the whole input space, rather than only at the
/// points a human happened to pick?
///
/// It runs on the local mock harness (labelled, not the production profile) because a
/// fuzz campaign needs thousands of runs; the real-pinned-route evidence lives in
/// test/contracts/HeldController.t.sol and is unaffected by anything here.
contract HeldControllerPropertiesTest is Test {
    uint256 constant PK_RUNNER = 0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a;
    address constant EXECUTOR = address(0xE0E0);
    address constant SAFE = address(0x5AFE);
    bytes32 constant LINEAGE = bytes32(uint256(0x11));
    bytes32 constant NORMAL_ROLE = keccak256("n");
    bytes32 constant RESTORE_ROLE = keccak256("r");
    bytes32 constant SUPPLY_KEY = keccak256("sk");
    bytes32 constant RESTORE_KEY = keccak256("rk");

    // The policy under test. Fixed so the reference predicate is readable.
    uint128 constant LS = 100_000e6;
    uint128 constant MS = 40_000e6;
    uint128 constant MIN_S = 1_000e6;
    uint128 constant F = 1_000e6;
    uint128 constant H = 500e6;
    uint64 constant NN = 50;

    HeldController controller;
    MockRoles roles;
    MockMorpho morpho;
    MockToken token;
    MarketParams mp;
    address runner;

    function setUp() public {
        runner = vm.addr(PK_RUNNER);
    }

    function _fresh(uint256 safeBalance) internal {
        roles = new MockRoles();
        morpho = new MockMorpho();
        token = new MockToken();
        roles.setKeys(SUPPLY_KEY, RESTORE_KEY);
        roles.setAllowances(LS, 10_000e6);
        morpho.setToken(address(token));
        token.init(SAFE, address(morpho), safeBalance);

        mp = MarketParams({
            loanToken: address(token),
            collateralToken: address(0xC0),
            oracle: address(0x0A),
            irm: address(0x12),
            lltv: 860000000000000000
        });
        controller = new HeldController(
            SAFE, address(roles), address(morpho), address(token),
            keccak256(abi.encode(mp)), LINEAGE, NORMAL_ROLE, RESTORE_ROLE, SUPPLY_KEY, RESTORE_KEY
        );

        HeldController.Policy memory p;
        p.Ls = LS; p.Ln = 50_000e6; p.Lr = 10_000e6;
        p.Ms = MS; p.Mn = 10_000e6; p.Mr = 5_000e6;
        p.ms = MIN_S; p.mn = 1_000e6;
        p.F = F; p.H = H;
        p.Nn = NN; p.Nr = 5; p.dn = 0; p.dr = 0;
        HeldController.ExpectedState memory e;
        vm.prank(SAFE);
        controller.activate(1, 1, runner, EXECUTOR, p, e);
    }

    function _env(bytes32 opId, uint256 amount) internal view returns (HeldController.Envelope memory env) {
        env.operationId = opId;
        env.sourceIdentityHash = keccak256("src");
        env.payloadHash = controller.actionHash(1, keccak256(abi.encode(mp)), address(token), amount, SAFE);
        env.actionFamily = 1;
        env.safe = SAFE;
        env.lineage = LINEAGE;
        env.epoch = 1;
        env.policyVersion = 1;
        env.runner = runner;
    }

    function _sig(HeldController.Envelope memory env) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(PK_RUNNER, controller.signingHash(env));
        return abi.encodePacked(r, s, v);
    }

    /// @dev The INDEPENDENT reference: V4 §5's SUPPLY predicates, written out plainly.
    ///      If the controller and this disagree anywhere in the input space, one is wrong.
    function _referenceSupplyAllowed(uint256 balance, uint256 amount, uint256 used)
        internal
        pure
        returns (bool)
    {
        if (balance < uint256(F) + uint256(H)) return false;
        if (amount < MIN_S || amount > MS) return false;
        if (amount > balance - F) return false;
        if (used + amount > LS) return false;
        return true;
    }

    // ------------------------------------------------------------------ fuzz --

    /// @notice A supply succeeds EXACTLY when the V4 §5 predicates hold. Not "usually".
    function testFuzz_SupplySucceedsExactlyWhenPredicatesHold(uint256 balance, uint256 amount) public {
        balance = bound(balance, 0, 300_000e6);
        amount = bound(amount, 0, 60_000e6);
        _fresh(balance);

        bool expected = _referenceSupplyAllowed(balance, amount, 0);

        HeldController.Envelope memory env = _env(keccak256("fuzz"), amount);
        bytes memory sig = _sig(env);
        vm.prank(EXECUTOR);
        (bool ok,) = address(controller).call(
            abi.encodeCall(HeldController.executeSupply, (env, mp, amount, sig))
        );

        assertEq(ok, expected, "controller disagreed with the reference predicate");
        if (ok) {
            assertEq(controller.usedSupply(), amount, "consumption equals the amount supplied");
            assertGe(token.balanceOf(SAFE), F, "cash floor retained");
        } else {
            assertEq(controller.usedSupply(), 0, "a refusal consumes nothing");
            assertEq(controller.normalCount(), 0);
        }
    }

    /// @notice Consumption never exceeds the ceiling, and remaining never underflows,
    ///         across an arbitrary sequence of amounts.
    function testFuzz_ConsumptionIsMonotonicAndBounded(uint256[8] memory amounts) public {
        _fresh(300_000e6);
        uint128 previous = 0;

        for (uint256 i = 0; i < amounts.length; i++) {
            uint256 amount = bound(amounts[i], 0, 60_000e6);
            HeldController.Envelope memory env = _env(keccak256(abi.encode("seq", i)), amount);
            bytes memory sig = _sig(env);
            vm.prank(EXECUTOR);
            address(controller).call(abi.encodeCall(HeldController.executeSupply, (env, mp, amount, sig)));

            uint128 used = controller.usedSupply();
            assertGe(used, previous, "consumption decreased");
            assertLe(used, LS, "consumption exceeded the ceiling");
            assertEq(controller.remainingSupply(), uint256(LS) - uint256(used), "remaining is exact");
            assertLe(controller.normalCount(), NN, "count exceeded its limit");
            previous = used;
        }
    }

    /// @notice A consumed operation id can never execute again, whatever the amount.
    function testFuzz_ConsumedOperationIdNeverExecutesAgain(uint256 second) public {
        _fresh(300_000e6);
        HeldController.Envelope memory first = _env(keccak256("once"), 5_000e6);
        bytes memory sig1 = _sig(first);
        vm.prank(EXECUTOR);
        controller.executeSupply(first, mp, 5_000e6, sig1);
        uint128 usedAfterFirst = controller.usedSupply();

        second = bound(second, 0, 60_000e6);
        HeldController.Envelope memory again = _env(keccak256("once"), second);
        bytes memory sig2 = _sig(again);
        vm.prank(EXECUTOR);
        (bool ok,) = address(controller).call(
            abi.encodeCall(HeldController.executeSupply, (again, mp, second, sig2))
        );
        assertFalse(ok, "a consumed id executed a second time");
        assertEq(controller.usedSupply(), usedAfterFirst, "consumption changed on a refused replay");
    }

    /// @notice Distinct economic actions never share a payload hash. A collision would
    ///         let one signed envelope carry a different action.
    function testFuzz_ActionHashIsInjective(uint256 a1, uint256 a2, address on1, address on2) public {
        _fresh(100_000e6);
        vm.assume(a1 != a2 || on1 != on2);
        bytes32 m = keccak256(abi.encode(mp));
        bytes32 h1 = controller.actionHash(1, m, address(token), a1, on1);
        bytes32 h2 = controller.actionHash(1, m, address(token), a2, on2);
        assertTrue(h1 != h2, "distinct actions collided");
        // Family is bound too: SUPPLY and WITHDRAW of the same amount differ.
        assertTrue(
            controller.actionHash(1, m, address(token), a1, on1)
                != controller.actionHash(2, m, address(token), a1, on1),
            "family not bound into the payload hash"
        );
    }

    /// @notice Any mutation of a signed envelope invalidates the signature.
    function testFuzz_MutatedEnvelopeNeverVerifies(uint8 field, uint64 delta) public {
        _fresh(300_000e6);
        // Every branch must STRICTLY change the field. An earlier version used
        // `1 + (delta % 1000)` for policyVersion, which the fuzzer defeated with
        // delta = 1e11 (1e11 % 1000 == 0) -- it wrote back the original value 1, so
        // the envelope was never mutated and the signature legitimately verified.
        // The counterexample was a flaw in this test, not in the controller.
        delta = uint64(bound(delta, 1, 1_000_000));
        HeldController.Envelope memory env = _env(keccak256("mutate"), 5_000e6);
        bytes memory sig = _sig(env); // signed over the ORIGINAL

        uint8 which = field % 5;
        if (which == 0) env.operationId = keccak256(abi.encode("op", delta));
        else if (which == 1) env.sourceIdentityHash = keccak256(abi.encode("src", delta));
        else if (which == 2) env.epoch = 1 + delta;           // delta >= 1, so never 1
        else if (which == 3) env.policyVersion = 1 + uint32(delta); // delta >= 1, so never 1
        else env.lineage = keccak256(abi.encode("lin", delta));

        assertTrue(
            env.epoch != 1 || env.policyVersion != 1 || env.operationId != keccak256("mutate")
                || env.sourceIdentityHash != keccak256("src") || env.lineage != LINEAGE,
            "test bug: nothing was actually mutated"
        );

        vm.prank(EXECUTOR);
        (bool ok,) = address(controller).call(
            abi.encodeCall(HeldController.executeSupply, (env, mp, 5_000e6, sig))
        );
        assertFalse(ok, "a mutated envelope was accepted under the original signature");
        assertEq(controller.usedSupply(), 0);
    }

    /// @notice The withdraw lane is DERIVED from the Safe balance, never chosen. Below the
    ///         floor it must be restoration; at or above it, normal.
    function testFuzz_WithdrawLaneIsDerivedFromBalance(uint256 balance) public {
        balance = bound(balance, 0, 50_000e6);
        _fresh(300_000e6);

        // Build a position first, then force the Safe balance to the fuzzed value.
        HeldController.Envelope memory sup = _env(keccak256("lane-setup"), 20_000e6);
        bytes memory sigS = _sig(sup);
        vm.prank(EXECUTOR);
        controller.executeSupply(sup, mp, 20_000e6, sigS);

        token.init(SAFE, address(morpho), balance);
        uint256 amount = 500e6;

        HeldController.Envelope memory env = _env(keccak256("lane"), amount);
        env.actionFamily = 2;
        env.payloadHash = controller.actionHash(2, keccak256(abi.encode(mp)), address(token), amount, SAFE);
        bytes memory sig = _sig(env);
        vm.prank(EXECUTOR);
        (bool ok,) = address(controller).call(
            abi.encodeCall(HeldController.executeWithdraw, (env, mp, amount, sig))
        );

        if (ok) {
            bool wasRestoration = balance < F;
            assertEq(controller.usedRestoration() > 0, wasRestoration, "wrong lane charged");
            assertEq(controller.usedNormalWithdraw() > 0, !wasRestoration, "wrong lane charged");
        }
        // Whichever lane ran, neither budget may exceed its ceiling.
        assertLe(controller.usedRestoration(), 10_000e6);
        assertLe(controller.usedNormalWithdraw(), 50_000e6);
    }
}
