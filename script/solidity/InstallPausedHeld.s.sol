// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script} from "forge-std/Script.sol";

import {HeldController} from "../../contracts/src/HeldController.sol";
import {HeldInstall} from "../../contracts/src/install/HeldInstall.sol";
import {MarketParams} from "../../contracts/src/Interfaces.sol";

/// @notice Install an already-deployed, PAUSED Held controller through the tested route.
///
/// This is the pre-activation half of `fixtures/scripts/03d`. It exists because the
/// checklist has to inspect the installation Held actually intends to run under, and the
/// deployment helper used to send `enableModule(controller)` and nothing else -- no Roles
/// membership, no condition trees, none of the five budgets. The checklist was therefore
/// reporting on a permission path the tests never exercised.
///
/// It calls the SAME `HeldInstall.install` the fork harness calls. If the two ever diverge
/// the harness's own suite fails, which is the point of having one definition.
///
/// @dev Broadcast as the Safe (`--unlocked --sender $HELD_SAFE`): every call here is an
///      owner act. Nothing activates the controller -- it stays paused at epoch 0 with
///      zero consumption, which is what V4 §6 requires before initial activation.
contract InstallPausedHeld is Script {
    function run() external {
        address safe = vm.envAddress("HELD_SAFE");
        address roles = vm.envAddress("HELD_ROLES");
        bytes32 roleKey = vm.envBytes32("HELD_ROLE_KEY");
        bytes32 allowKey = vm.envBytes32("HELD_ALLOW_KEY");
        // The P00 native runner, retired as part of installing the new lineage. Absent
        // means "nothing to retire" rather than "skip the check".
        address retire = vm.envOr("HELD_RETIRE_MEMBER", address(0));

        bytes32 marketId = _marketId();

        // Deploy, enable and install in ONE owner act, so the controller's budget keys and
        // the keys the installation configures cannot be two different sets. They were:
        // the old helper derived its own keys in bash ("held.restoration.role" and
        // friends) while the tested installation used HeldInstall's, so the deployed
        // controller was bound to budgets nothing ever configured.
        vm.startBroadcast(safe);

        HeldController controller = new HeldController(
            safe,
            roles,
            HeldInstall.MORPHO,
            HeldInstall.USDC,
            marketId,
            HeldInstall.LINEAGE,
            HeldController.Keys({
                normalRole: roleKey,
                restorationRole: HeldInstall.RESTORE_ROLE,
                supplyAmount: allowKey,
                normalWithdrawAmount: HeldInstall.WITHDRAW_KEY,
                restorationAmount: HeldInstall.RESTORE_KEY,
                normalCount: HeldInstall.NORMAL_COUNT_KEY,
                restorationCount: HeldInstall.RESTORE_COUNT_KEY
            })
        );

        // The Safe enables its own module: msg.sender is the Safe, which is what its
        // `authorized` modifier requires.
        (bool ok,) = safe.call(abi.encodeWithSignature("enableModule(address)", address(controller)));
        require(ok, "enableModule failed");

        HeldInstall.install(
            HeldInstall.Params({
                safe: safe,
                roles: roles,
                controller: address(controller),
                retireMember: retire,
                normalRole: roleKey,
                supplyKey: allowKey
            })
        );
        vm.stopBroadcast();

        // Paused is not an aspiration; it is asserted before anything else is claimed.
        require(!controller.active(), "controller is ACTIVE after installation");
        require(controller.epoch() == 0, "controller epoch is not 0");

        _writeManifest(safe, roles, address(controller), roleKey, allowKey, retire, marketId);
    }

    function _marketId() internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                MarketParams({
                    loanToken: HeldInstall.USDC,
                    collateralToken: HeldInstall.COLL,
                    oracle: HeldInstall.ORACLE,
                    irm: HeldInstall.IRM,
                    lltv: HeldInstall.LLTV
                })
            )
        );
    }

    /// @dev The DECLARED installation, written so the checklist compares live state against
    ///      something stated in advance rather than against whatever it happens to read.
    ///      These are candidate terms, not controller policy: the controller's own budgets
    ///      are all zero until activation, and that distinction is preserved here.
    function _writeManifest(
        address safe,
        address roles,
        address controller,
        bytes32 roleKey,
        bytes32 allowKey,
        address retire,
        bytes32 marketId
    ) internal {
        string memory o = "install";
        vm.serializeAddress(o, "safe", safe);
        vm.serializeAddress(o, "roles", roles);
        vm.serializeAddress(o, "controller", controller);
        vm.serializeAddress(o, "retiredMember", retire);
        vm.serializeAddress(o, "morpho", HeldInstall.MORPHO);
        vm.serializeAddress(o, "usdc", HeldInstall.USDC);
        vm.serializeBytes32(o, "marketId", marketId);
        vm.serializeBytes32(o, "lineage", HeldController(controller).lineage());

        vm.serializeBytes32(o, "normalRole", roleKey);
        vm.serializeBytes32(o, "restorationRole", HeldInstall.RESTORE_ROLE);
        vm.serializeBytes32(o, "supplyAmountKey", allowKey);
        vm.serializeBytes32(o, "normalWithdrawKey", HeldInstall.WITHDRAW_KEY);
        vm.serializeBytes32(o, "restorationKey", HeldInstall.RESTORE_KEY);
        vm.serializeBytes32(o, "normalCountKey", HeldInstall.NORMAL_COUNT_KEY);
        vm.serializeBytes32(o, "restorationCountKey", HeldInstall.RESTORE_COUNT_KEY);

        vm.serializeUint(o, "supplyAmountLimit", uint256(HeldInstall.LS));
        vm.serializeUint(o, "normalWithdrawLimit", uint256(HeldInstall.LN));
        vm.serializeUint(o, "restorationLimit", uint256(HeldInstall.LR));
        vm.serializeUint(o, "normalCountLimit", uint256(HeldInstall.NORMAL_COUNT));
        vm.serializeUint(o, "restorationCountLimit", uint256(HeldInstall.RESTORE_COUNT));
        vm.serializeUint(o, "approvalValueBound", uint256(HeldInstall.MS));

        string memory out = vm.serializeString(
            o,
            "_note",
            "DECLARED candidate installation, written by script/solidity/InstallPausedHeld.s.sol "
            "before activation. The amount/count limits are the NATIVE Roles allowances this "
            "installation configures; the controller's own policy is zero until an owner "
            "activates it. Not a reading of live state -- the checklist reads that separately "
            "and compares."
        );
        vm.writeJson(out, "./fixtures/generated/held-install-manifest.json");
    }
}
