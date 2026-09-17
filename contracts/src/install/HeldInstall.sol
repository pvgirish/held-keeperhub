// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ConditionFlat, IERC20, IMorpho, IRolesAdmin, IRolesTargets} from "../Interfaces.sol";

/// @notice THE installation. One definition of what "Held is installed" means.
///
/// This exists because the two things that install Held had drifted apart. The fork
/// harness assigned the controller to both Zodiac Roles, retired the previous runner,
/// applied the tight supply/withdraw/approval condition trees and configured all five
/// allowances. The pre-activation deployment helper sent `enableModule(controller)` to the
/// Safe and stopped -- and the bootstrap checklist then inspected THAT, so the checklist
/// was verifying a permission path the tests never exercised and the tested path was never
/// verified by the checklist.
///
/// Enabling a contract as a Safe module is not the same as making it a member of a
/// restricted Zodiac Role. A module can ask the Safe to execute; a role member is bound by
/// the condition trees and the allowances. Held's design needs both, so both belong in one
/// place that the harness, the deployment and the checklist all read.
///
/// @dev Every function is `internal`, so it inlines into its caller and `msg.sender` is
///      preserved. That matters: these calls must arrive FROM the Safe, whether that is a
///      `vm.prank` in a test or a broadcast from the impersonated Safe in a deployment.
///      A `public` library would be delegatecalled and is not needed here.
library HeldInstall {
    // ---------------------------------------------------------------- pinned market --
    // The Base-mainnet pins. Held's installation is only meaningful against these; a
    // caller that means a different market is not doing this installation.
    address internal constant MORPHO = 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb;
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant COLL = 0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452;
    address internal constant ORACLE = 0xD7A1abA119a236Fea5BBC5cAC6836465cbe9289A;
    address internal constant IRM = 0x46415998764C29aB2a25CbeA6254146D50D22687;
    uint256 internal constant LLTV = 860000000000000000;

    // ------------------------------------------------------------- the five budgets --
    // Each economic dimension gets its OWN non-refilling key. Sharing one would let a
    // withdraw spend the supply budget.
    bytes32 internal constant WITHDRAW_KEY = keccak256("held-withdraw-cap");
    bytes32 internal constant RESTORE_ROLE = keccak256("held-restoration-v1");
    bytes32 internal constant RESTORE_KEY = keccak256("held-restoration-cap");
    bytes32 internal constant NORMAL_COUNT_KEY = keccak256("held-normal-count");
    bytes32 internal constant RESTORE_COUNT_KEY = keccak256("held-restoration-count");

    uint128 internal constant LN = 50_000e6; // normal withdraw amount
    uint128 internal constant LR = 10_000e6; // restoration amount
    uint128 internal constant LS = 50_000e6; // supply amount
    uint128 internal constant MS = 40_000e6; // approval value bound (NOT an allowance)
    uint128 internal constant NORMAL_COUNT = 10;
    uint128 internal constant RESTORE_COUNT = 5;

    /// @dev The lineage this installation belongs to. Held's own history starts here;
    ///      nothing imports pre-Held native consumption into it (V4 §6).
    bytes32 internal constant LINEAGE = bytes32(uint256(0x11));

    /// @param safe          the avatar and owner of the Roles module
    /// @param roles         the Zodiac Roles module
    /// @param controller    the Held controller being installed, PAUSED
    /// @param retireMember  a previous role member to revoke, or address(0) for none
    /// @param normalRole    the operating role key (fixture-supplied)
    /// @param supplyKey     the supply amount allowance key (fixture-supplied)
    struct Params {
        address safe;
        address roles;
        address controller;
        address retireMember;
        bytes32 normalRole;
        bytes32 supplyKey;
    }

    /// @notice Install the controller as the SOLE member of both operating roles, with
    ///         tight conditions and all five budgets configured. Must be called by the Safe.
    /// @dev Does NOT activate. The controller stays paused at epoch 0 with zero
    ///      consumption; activation is a separate, owner-authorised act.
    function install(Params memory p) internal {
        // The controller becomes the role member and the previous operator is retired.
        // V4 §3: the controller is the SOLE member of the operating role; no runner keeps
        // a direct path around it.
        assign(p.roles, p.controller, p.normalRole, true);
        assign(p.roles, p.controller, RESTORE_ROLE, true);
        if (p.retireMember != address(0)) assign(p.roles, p.retireMember, p.normalRole, false);

        // Clear the NORMAL lane's targets before scoping functions on them. This was
        // missing and the asymmetry was easy to miss: the restoration lane below scoped
        // its own target, while the normal lane silently relied on the bash fixture having
        // run `scopeTarget(roleKey, MORPHO)` and `scopeTarget(roleKey, USDC)` first.
        //
        // In Zodiac Roles v2 `scopeFunction` does not grant target clearance, so on a Safe
        // where those fixture steps had not run, install() would complete WITHOUT
        // reverting and leave every normal-lane supply, withdraw and approve failing with
        // TargetAddressNotAllowed. A library that calls itself the one definition of the
        // installation cannot depend on an undeclared precondition.
        IRolesTargets(p.roles).scopeTarget(p.normalRole, MORPHO);
        IRolesTargets(p.roles).scopeTarget(p.normalRole, USDC);

        // A NEW lineage gets a clearly labelled NEW budget. Historical native consumption
        // is deliberately NOT imported (V4 §6).
        scopeSupplyTight(p);
        scopeApproveBounded(p);
        IRolesAdmin(p.roles).setAllowance(p.supplyKey, LS, LS, 0, 0, 0);

        // Withdraw needs its own scoped function and its own non-refilling quota, or Roles
        // rejects it outright (FunctionNotAllowed): scopeTarget sets Clearance.Function, so
        // EVERY function must be scoped explicitly.
        scopeWithdraw(p, p.normalRole, WITHDRAW_KEY, NORMAL_COUNT_KEY);
        IRolesAdmin(p.roles).setAllowance(WITHDRAW_KEY, LN, LN, 0, 0, 0);

        // The RESTORATION lane is a separate role with its OWN non-refilling key, because
        // Zodiac allows one condition tree per (role, target, selector).
        IRolesTargets(p.roles).scopeTarget(RESTORE_ROLE, MORPHO);
        scopeWithdraw(p, RESTORE_ROLE, RESTORE_KEY, RESTORE_COUNT_KEY);
        IRolesAdmin(p.roles).setAllowance(RESTORE_KEY, LR, LR, 0, 0, 0);

        // Native COUNT allowances, one per lane. V4 §5: the shared normal count covers
        // SUPPLY and NORMAL WITHDRAW; restoration has its own.
        IRolesAdmin(p.roles).setAllowance(NORMAL_COUNT_KEY, NORMAL_COUNT, NORMAL_COUNT, 0, 0, 0);
        IRolesAdmin(p.roles).setAllowance(RESTORE_COUNT_KEY, RESTORE_COUNT, RESTORE_COUNT, 0, 0, 0);
    }

    function assign(address roles, address who, bytes32 key, bool member) internal {
        bytes32[] memory keys = new bytes32[](1);
        bool[] memory members = new bool[](1);
        keys[0] = key;
        members[0] = member;
        (bool ok,) =
            roles.call(abi.encodeWithSignature("assignRoles(address,bytes32[],bool[])", who, keys, members));
        require(ok, "assignRoles failed");
    }

    /// @dev TIGHT withdraw tree. Every fixed argument is pinned with EqualTo; only the
    ///      amount is a quota. Leaving shares, onBehalf, receiver and the market tuple as
    ///      `Pass` meant Roles independently restricted nothing except the amount.
    function scopeWithdraw(Params memory p, bytes32 role, bytes32 allowanceKey, bytes32 countKey)
        internal
    {
        ConditionFlat[] memory c = new ConditionFlat[](11);
        c[0] = ConditionFlat(0, 5, 5, ""); // root Calldata/Matches
        c[1] = ConditionFlat(0, 3, 5, ""); // param0 tuple, Matches
        c[2] = ConditionFlat(0, 1, 28, abi.encode(allowanceKey)); // param1 assets WithinAllowance
        c[3] = ConditionFlat(0, 1, 16, abi.encode(uint256(0))); // param2 shares == 0
        c[4] = ConditionFlat(0, 1, 16, abi.encode(p.safe)); // param3 onBehalf == Safe
        c[5] = ConditionFlat(0, 1, 16, abi.encode(p.safe)); // param4 receiver == Safe
        c[6] = ConditionFlat(1, 1, 16, abi.encode(USDC));
        c[7] = ConditionFlat(1, 1, 16, abi.encode(COLL));
        c[8] = ConditionFlat(1, 1, 16, abi.encode(ORACLE));
        c[9] = ConditionFlat(1, 1, 16, abi.encode(IRM));
        c[10] = ConditionFlat(1, 1, 16, abi.encode(LLTV));
        IRolesAdmin(p.roles).scopeFunction(role, MORPHO, IMorpho.withdraw.selector, withCallCount(c, countKey), 0);
    }

    /// @dev TIGHT supply tree, the P02 overlay over the P00 fixture's permissive one.
    function scopeSupplyTight(Params memory p) internal {
        ConditionFlat[] memory c = new ConditionFlat[](11);
        c[0] = ConditionFlat(0, 5, 5, ""); // root Calldata/Matches
        c[1] = ConditionFlat(0, 3, 5, ""); // param0 tuple, Matches
        c[2] = ConditionFlat(0, 1, 28, abi.encode(p.supplyKey)); // param1 assets WithinAllowance
        c[3] = ConditionFlat(0, 1, 16, abi.encode(uint256(0))); // param2 shares == 0
        c[4] = ConditionFlat(0, 1, 16, abi.encode(p.safe)); // param3 onBehalf == Safe
        // EqualTo accepts Dynamic. compValue is hashed on store and compared against
        // keccak256(pluck(...)) at check time, so the empty-bytes encoding below pins the
        // callback to empty AT THE ROLES LAYER, independently of the controller.
        c[5] = ConditionFlat(0, 2, 16, abi.encode(bytes(""))); // param4 data == 0x
        c[6] = ConditionFlat(1, 1, 16, abi.encode(USDC));
        c[7] = ConditionFlat(1, 1, 16, abi.encode(COLL));
        c[8] = ConditionFlat(1, 1, 16, abi.encode(ORACLE));
        c[9] = ConditionFlat(1, 1, 16, abi.encode(IRM));
        c[10] = ConditionFlat(1, 1, 16, abi.encode(LLTV));
        IRolesAdmin(p.roles).scopeFunction(
            p.normalRole, MORPHO, IMorpho.supply.selector, withCallCount(c, NORMAL_COUNT_KEY), 0
        );
    }

    /// @dev P02 overlay for the token approval. The P00 fixture bound the spender to Morpho
    ///      but left the VALUE unrestricted at the native layer. A finite bound is applied
    ///      here; cleanup approve(0) stays permitted because 0 < bound.
    ///
    ///      Deliberately NOT a WithinAllowance: the approval must not charge the economic
    ///      amount quota, which is consumed by the protocol call alone (V4 §5).
    function scopeApproveBounded(Params memory p) internal {
        ConditionFlat[] memory c = new ConditionFlat[](3);
        c[0] = ConditionFlat(0, 5, 5, ""); // root Calldata/Matches
        c[1] = ConditionFlat(0, 1, 16, abi.encode(MORPHO)); // spender == Morpho
        c[2] = ConditionFlat(0, 1, 18, abi.encode(uint256(MS) + 1)); // value < Ms + 1
        IRolesAdmin(p.roles).scopeFunction(p.normalRole, USDC, IERC20.approve.selector, c, 0);
    }

    /// @dev Insert a CallWithinAllowance node so the native COUNT allowance is actually
    ///      CONSUMED by the economic call, not merely checked at activation.
    ///
    ///      Operator 30 / paramType None(0), confirmed from Zodiac Types.sol at the pinned
    ///      source. The node must be INSERTED among the root's children, not appended: the
    ///      condition array is required to be breadth-first, and appending a parent==0 node
    ///      after the parent==1 tuple children reverts NotBFS().
    function withCallCount(ConditionFlat[] memory base, bytes32 countKey)
        internal
        pure
        returns (ConditionFlat[] memory out)
    {
        uint256 insertAt = base.length;
        for (uint256 i = 1; i < base.length; i++) {
            if (base[i].parent != 0) {
                insertAt = i;
                break;
            }
        }
        out = new ConditionFlat[](base.length + 1);
        for (uint256 i = 0; i < insertAt; i++) {
            out[i] = base[i];
        }
        out[insertAt] = ConditionFlat(0, 0, 30, abi.encode(countKey));
        for (uint256 i = insertAt; i < base.length; i++) {
            out[i + 1] = base[i];
            // children referencing the tuple keep pointing at it; the tuple is at index 1
            // and nothing was inserted before it, so parent indices are unchanged.
        }
    }
}
