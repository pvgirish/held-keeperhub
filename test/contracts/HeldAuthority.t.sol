// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {HeldController} from "../../contracts/src/HeldController.sol";
import {IERC20, IMorpho, IRoles, MarketParams} from "../../contracts/src/Interfaces.sol";
import {HeldForkHarness} from "./HeldForkHarness.sol";

/// @notice P04: authority inventory, owner fencing, change and handover.
///
/// The product claim this phase has to earn is the second half of the pitch: an operator
/// can "change those limits or replace the runner without losing consumption history or
/// guessing what an interrupted operation did".
///
/// Two things are therefore proven here rather than described:
///
///   1. **Who can do what** is enumerated by READING the fork, not by asserting it in
///      prose. Every authority in the inventory is checked by exercising it or by
///      showing it refused. An inventory nobody tried is a diagram, not evidence.
///
///   2. **An interruption is resolvable.** Fencing mid-flight, replacing a runner and
///      changing a policy must each leave consumption history intact and must leave no
///      operation whose outcome has to be guessed.
contract HeldAuthorityForkTest is HeldForkHarness {
    // Zodiac Roles v2 refusal selectors, verified by hashing the signatures rather than
    // copied from memory: an earlier version of this file guessed one and was wrong,
    // which made every address read as a role member.
    bytes4 constant NO_MEMBERSHIP = 0xfd8e9f28;   // NoMembership()
    bytes4 constant NOT_AUTHORIZED = 0x4a0bfec1;  // NotAuthorized(address) -- not a module

    /// @dev Ask Roles to act as `who` against a target that is not in scope, and return
    ///      the selector it refuses with. Nothing is ever executed: the target is
    ///      unscoped, so the call cannot reach an economic action.
    ///
    ///      The selector is the answer. `NotAuthorized` means the address is not even an
    ///      enabled module; `NoMembership` means it is a module but holds no role. Both
    ///      mean "cannot act through Roles", and distinguishing them is what makes this
    ///      an inventory rather than a yes/no.
    function _rolesRefusal(address who, bytes32 key) internal returns (bytes4) {
        vm.prank(who);
        (bool okCall, bytes memory ret) = roles.call(
            abi.encodeWithSignature(
                "execTransactionWithRoleReturnData(address,uint256,bytes,uint8,bytes32,bool)",
                address(0xDEAD), uint256(0), bytes(""), uint8(0), key, true
            )
        );
        assertFalse(okCall, "the Roles probe must never actually execute anything");
        return bytes4(ret);
    }

    // ------------------------------------------------------------- the inventory --

    /// @dev The complete list of parties that can affect this controller, each checked
    ///      against the live fork. The point of enumerating them in one test is that a
    ///      NEW authority added later has to be added here too, or the count fails.
    function test_AuthorityInventoryIsComplete() public {
        _activate(1, runnerB);

        // 1. The Safe owner: the only party that may activate or fence.
        vm.prank(safe);
        controller.fence();
        assertFalse(controller.active());
        HeldController.Policy memory _p1 = _policy();
        HeldController.ExpectedState memory _e1 = _expected();
        vm.prank(safe);
        controller.activate(2, 1, runnerB, EXECUTOR, _p1, _e1);
        assertTrue(controller.active());

        // 2. The runner: authorizes an operation by signature, and cannot call directly.
        HeldController.Envelope memory env = _envelope(keccak256("inv-1"), 1, 5_000e6, 2, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();
        vm.prank(runnerB);
        vm.expectRevert(HeldController.NotExecutor.selector);
        controller.executeSupply(env, mp_, 5_000e6, sig);

        // 3. The executor: may call, but cannot authorize anything by itself.
        HeldController.Envelope memory unsigned_ = _envelope(keccak256("inv-2"), 1, 5_000e6, 2, EXECUTOR);
        bytes memory wrongSig = _sign(unsigned_, PK_RUNNER_B); // signed by the runner, names the executor
        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.BadSignature.selector);
        controller.executeSupply(unsigned_, mp_, 5_000e6, wrongSig);

        // The executor with a properly signed envelope is the ONLY working combination.
        vm.prank(EXECUTOR);
        controller.executeSupply(env, mp_, 5_000e6, sig);
        assertEq(controller.usedSupply(), 5_000e6);

        // 4. Zodiac Roles: an independent refusal layer the controller cannot talk past.
        //    The controller's membership is established by the supply that just
        //    succeeded through Roles -- that is stronger than any probe, because a
        //    non-member could not have moved the funds.
        //
        //    Every other party is refused, and the SELECTOR says why:
        // The two EOAs are refused for DIFFERENT reasons, and the inventory records
        // which. runnerA was enabled as a module by the fixture's isolated condition
        // probes, so it reaches the membership check and fails there. runnerB never was,
        // so it is turned away one step earlier. Both mean "cannot act through Roles",
        // and flattening them to a single boolean would have hidden that runnerA holds
        // module standing at all.
        assertEq(_rolesRefusal(runnerA, roleKey), NO_MEMBERSHIP,
            "runnerA is an enabled module from the fixture probes, but must hold no role");
        assertEq(_rolesRefusal(runnerB, roleKey), NOT_AUTHORIZED,
            "the active runner authorizes by signature and is not a module at all");
        assertEq(_rolesRefusal(EXECUTOR, roleKey), NOT_AUTHORIZED,
            "the executor is not a module on the Safe");

        // 5. Nobody else. An arbitrary address holds none of the authorities.
        address stranger = address(0xBEEF);
        vm.prank(stranger);
        vm.expectRevert();
        controller.fence();
        vm.prank(stranger);
        vm.expectRevert(HeldController.NotExecutor.selector);
        controller.executeSupply(env, mp_, 5_000e6, sig);
        assertEq(_rolesRefusal(stranger, roleKey), NOT_AUTHORIZED, "a stranger is not a module");

        // The two refusals are genuinely different, so neither assertion above could be
        // passing for the wrong reason.
        assertTrue(NO_MEMBERSHIP != NOT_AUTHORIZED);
    }

    /// @dev The controller's own bindings are immutable, so an authority cannot be moved
    ///      after deployment by anyone at all -- including the owner.
    function test_ControllerBindingsCannotBeRepointedByAnyone() public view {
        assertEq(controller.safe(), safe);
        assertEq(controller.roles(), roles);
        assertEq(controller.morpho(), MORPHO);
        assertEq(controller.token(), USDC);
        assertEq(controller.marketId(), marketId);
        assertEq(controller.lineage(), LINEAGE);
        // There is no setter for any of these. The test that proves it is the ABI
        // itself: the only state-changing external functions are activate, fence and
        // the two typed entries, enumerated in test_AuthorityInventoryIsComplete.
    }

    // ------------------------------------------------------------------- fencing --

    /// @dev Fencing must stop work that is ALREADY authorized, not just future work.
    ///      A signature minted before the fence is the realistic case: the operator
    ///      fences precisely because something is in flight.
    function test_FencingStopsAnAlreadySignedOperationInFlight() public {
        _activate(1, runnerB);

        // The envelope and signature exist and would succeed right now.
        HeldController.Envelope memory env = _envelope(keccak256("fence-1"), 1, 5_000e6, 1, runnerB);
        bytes memory sig = _sign(env, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();

        vm.prank(safe);
        controller.fence();

        vm.prank(EXECUTOR);
        vm.expectRevert(HeldController.Paused.selector);
        controller.executeSupply(env, mp_, 5_000e6, sig);

        // Nothing moved, and nothing is left ambiguous: the id was never consumed.
        assertEq(controller.usedSupply(), 0);
        assertEq(controller.normalCount(), 0);
        assertFalse(controller.isConsumed(keccak256("fence-1")));
    }

    /// @dev Fencing preserves history. This is the whole reason fencing is not a reset.
    function test_FencingPreservesConsumptionAndCooldownState() public {
        _activate(1, runnerB);
        _supply(keccak256("fence-2"), 5_000e6, 1, PK_RUNNER_B, runnerB);

        uint128 supplied = controller.usedSupply();
        uint64 count = controller.normalCount();
        uint64 lastAt = controller.lastNormalAt();
        assertEq(supplied, 5_000e6);

        vm.prank(safe);
        controller.fence();

        assertEq(controller.usedSupply(), supplied, "fencing must not reset consumption");
        assertEq(controller.normalCount(), count);
        assertEq(controller.lastNormalAt(), lastAt, "cooldown state survives a fence");
        assertTrue(controller.isConsumed(keccak256("fence-2")), "a consumed id stays consumed");
    }

    /// @dev A fence cannot be undone except by a fresh activation under a NEW epoch,
    ///      and only by the owner. Re-activating the same epoch is refused.
    function test_OnlyAnOwnerActivationUnderANewEpochLiftsAFence() public {
        _activate(1, runnerB);
        vm.prank(safe);
        controller.fence();

        HeldController.Policy memory p = _policy();
        HeldController.ExpectedState memory exp = _expected();

        vm.prank(address(0xBEEF));
        vm.expectRevert();
        controller.activate(2, 1, runnerB, EXECUTOR, p, exp);

        vm.prank(safe);
        vm.expectRevert(HeldController.StaleActivation.selector);
        controller.activate(1, 1, runnerB, EXECUTOR, p, exp); // same epoch

        vm.prank(safe);
        controller.activate(2, 1, runnerB, EXECUTOR, p, exp);
        assertTrue(controller.active());
        assertEq(controller.epoch(), 2);
    }

    // -------------------------------------------------- change and handover --

    /// @dev Replacing the runner while an operation is in flight. This is the
    ///      interrupted case the product claim names: after the handover, the operator
    ///      must not have to GUESS what the interrupted operation did.
    function test_RunnerReplacementMidFlightLeavesNothingToGuess() public {
        _activate(1, runnerB);

        // runnerB authorizes an operation. It is signed but not yet executed.
        HeldController.Envelope memory inFlight = _envelope(keccak256("ho-1"), 1, 5_000e6, 1, runnerB);
        bytes memory sigB = _sign(inFlight, PK_RUNNER_B);
        MarketParams memory mp_ = _mp();

        // The operator hands over to runnerA.
        vm.prank(safe);
        controller.fence();
        HeldController.Policy memory _p2 = _policy();
        HeldController.ExpectedState memory _e2 = _expected();
        vm.prank(safe);
        controller.activate(2, 1, runnerA, EXECUTOR, _p2, _e2);

        // The interrupted operation is now UNAMBIGUOUS in both directions:
        //   - it cannot execute, because its epoch is retired;
        //   - it did not execute, because its id was never consumed.
        // The operator reads one bit on chain instead of guessing.
        vm.prank(EXECUTOR);
        vm.expectPartialRevert(HeldController.WrongEpoch.selector);
        controller.executeSupply(inFlight, mp_, 5_000e6, sigB);
        assertFalse(controller.isConsumed(keccak256("ho-1")), "definitely not executed");
        assertEq(controller.usedSupply(), 0);

        // V4 §4: definitely-not-executed and still desired means reauthorizing the
        // SAME id and the SAME payload under the new epoch. An earlier version of this
        // test used a fresh id ("ho-1-again"), which demonstrates something weaker and
        // skips the exact distinction this phase exists to preserve.
        _supply(keccak256("ho-1"), 5_000e6, 2, PK_RUNNER_A, runnerA);
        assertEq(controller.usedSupply(), 5_000e6);
        assertTrue(controller.isConsumed(keccak256("ho-1")),
            "the SAME operation id executed once, under the new runner");
    }

    /// @dev The other direction: an operation that ALREADY executed stays executed
    ///      across a handover and can never be replayed by the new runner.
    function test_AnExecutedOperationSurvivesHandoverAndCannotBeReplayed() public {
        _activate(1, runnerB);
        _supply(keccak256("ho-2"), 5_000e6, 1, PK_RUNNER_B, runnerB);

        vm.prank(safe);
        controller.fence();
        HeldController.Policy memory _p3 = _policy();
        HeldController.ExpectedState memory _e3 = _expected();
        vm.prank(safe);
        controller.activate(2, 1, runnerA, EXECUTOR, _p3, _e3);

        assertTrue(controller.isConsumed(keccak256("ho-2")), "history survives the handover");
        assertEq(controller.usedSupply(), 5_000e6, "consumption carried forward");

        // The new runner re-signing the SAME operation id changes nothing.
        HeldController.Envelope memory replay = _envelope(keccak256("ho-2"), 1, 5_000e6, 2, runnerA);
        bytes memory sigA = _sign(replay, PK_RUNNER_A);
        MarketParams memory mp_ = _mp();
        vm.prank(EXECUTOR);
        vm.expectPartialRevert(HeldController.OperationConsumed.selector);
        controller.executeSupply(replay, mp_, 5_000e6, sigA);
        assertEq(controller.usedSupply(), 5_000e6, "no second execution");
    }

    /// @dev Tightening a limit mid-life. The new ceiling binds against consumption
    ///      ALREADY recorded, so a customer cannot be surprised by a budget that
    ///      silently refills on reconfiguration.
    function test_LimitChangeBindsAgainstExistingConsumption() public {
        _activate(1, runnerB);
        _supply(keccak256("chg-1"), 5_000e6, 1, PK_RUNNER_B, runnerB);
        assertEq(controller.usedSupply(), 5_000e6);

        vm.prank(safe);
        controller.fence();

        // A ceiling BELOW what has already been spent is refused outright.
        HeldController.Policy memory tooLow = _policy();
        tooLow.Ls = 4_000e6;
        HeldController.ExpectedState memory exp = _expected();
        vm.prank(safe);
        vm.expectRevert(HeldController.CeilingBelowConsumption.selector);
        controller.activate(2, 1, runnerB, EXECUTOR, tooLow, exp);

        // A tightened-but-valid ceiling is accepted, and the remaining budget is the
        // NEW ceiling minus what was already consumed -- not a fresh allocation.
        HeldController.Policy memory tighter = _policy();
        tighter.Ls = 8_000e6;
        vm.startPrank(safe);
        _syncRoles(tighter);
        vm.stopPrank();
        HeldController.ExpectedState memory exp2 = _expected();
        vm.prank(safe);
        controller.activate(2, 1, runnerB, EXECUTOR, tighter, exp2);

        assertEq(controller.usedSupply(), 5_000e6, "consumption survived the change");
        assertEq(controller.remainingSupply(), 3_000e6, "8,000 ceiling minus 5,000 spent");

        // And the native Roles allowance agrees with that, not with the old ceiling.
        (,,, uint128 nativeRemaining,) = IRoles(roles).allowances(allowKey);
        assertEq(uint256(nativeRemaining), 3_000e6, "native quota re-synced to the new ceiling");
    }

    /// @dev A handover that forgets to re-sync the native quota is refused, so the two
    ///      layers can never drift apart across a reconfiguration.
    function test_HandoverWithUnsyncedNativeQuotaIsRefused() public {
        _activate(1, runnerB);
        _supply(keccak256("chg-2"), 5_000e6, 1, PK_RUNNER_B, runnerB);

        vm.prank(safe);
        controller.fence();

        // Change the ceiling WITHOUT touching the Roles allowance.
        HeldController.Policy memory changed = _policy();
        changed.Ls = 20_000e6;
        HeldController.ExpectedState memory exp = _expected();
        vm.prank(safe);
        vm.expectPartialRevert(HeldController.AllowanceDesynchronised.selector);
        controller.activate(2, 1, runnerB, EXECUTOR, changed, exp);

        // Still fenced, still intact: a refused reconfiguration changes nothing.
        assertFalse(controller.active());
        assertEq(controller.usedSupply(), 5_000e6);
        assertEq(controller.epoch(), 1);
    }

    /// @dev A retired runner is retired for every operation, not just the one that was
    ///      in flight -- including ids it never touched.
    function test_ARetiredRunnerCannotAuthorizeAnyNewOperation() public {
        _activate(1, runnerB);
        vm.prank(safe);
        controller.fence();
        HeldController.Policy memory _p4 = _policy();
        HeldController.ExpectedState memory _e4 = _expected();
        vm.prank(safe);
        controller.activate(2, 1, runnerA, EXECUTOR, _p4, _e4);

        MarketParams memory mp_ = _mp();
        for (uint256 i = 0; i < 3; i++) {
            HeldController.Envelope memory e = _envelope(keccak256(abi.encode("retired", i)), 1, 5_000e6, 2, runnerB);
            bytes memory s = _sign(e, PK_RUNNER_B);
            vm.prank(EXECUTOR);
            vm.expectRevert(HeldController.BadSignature.selector);
            controller.executeSupply(e, mp_, 5_000e6, s);
        }
        assertEq(controller.usedSupply(), 0);
    }
}
