// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script} from "forge-std/Script.sol";

import {HeldController} from "../../contracts/src/HeldController.sol";
import {HeldInstall} from "../../contracts/src/install/HeldInstall.sol";
import {MarketParams} from "../../contracts/src/Interfaces.sol";

/// @notice Emit the EXACT owner calldata for the mainnet ceremony, without sending it.
///
/// ## Why this exists
///
/// `InstallPausedHeld.s.sol` broadcasts as the Safe, which only works on a fork where the
/// Safe can be impersonated. On mainnet the Safe is a contract: every one of these calls
/// has to arrive through `execTransaction` with 2-of-3 owner signatures. The owner
/// therefore needs the calldata, not a script that sends it.
///
/// ## Why it is not hand-written
///
/// The calldata is produced by calling the SAME `HeldInstall.install()` the fork harness
/// and the P02/P03 suites exercise. Re-encoding the condition trees by hand in a document
/// is exactly the drift the 67eed71 review found once already, where the deployment helper
/// derived its own budget keys and the checklist then verified a path no test ran. Nothing
/// here restates the installation; it runs it and records what it emitted.
///
/// Run it WITHOUT `--broadcast`. Forge writes every simulated transaction, with its `to`,
/// `value` and `data`, to `broadcast/BuildOwnerCeremony.s.sol/8453/dry-run/run-latest.json`.
/// `script/build_owner_ceremony.py` turns that into the owner action list.
///
/// ## What it deliberately does NOT do
///
///   * It does not deploy the controller. On mainnet the owner EOA deploys it directly --
///     the constructor takes `_owner` as an argument, so the deployer does not become the
///     owner and the Safe does not need to send that transaction.
///   * It does not activate. Activation is a separate owner act with its own arguments,
///     and V4 §6 requires the controller to stay paused until the authority evidence is
///     complete.
///   * It sends nothing. There is no path in this file that broadcasts.
contract BuildOwnerCeremony is Script {
    function run() external {
        address safe = vm.envAddress("HELD_SAFE");
        address roles = vm.envAddress("HELD_ROLES");
        address controller = vm.envAddress("HELD_CONTROLLER");
        bytes32 roleKey = vm.envBytes32("HELD_ROLE_KEY");
        bytes32 allowKey = vm.envBytes32("HELD_ALLOW_KEY");
        address retire = vm.envOr("HELD_RETIRE_MEMBER", address(0));

        // The controller must already exist and must already belong to this Safe. A
        // ceremony built against the wrong controller would be valid calldata for the
        // wrong installation, which is worse than no calldata at all.
        require(controller.code.length > 0, "controller has no code at that address");
        HeldController c = HeldController(controller);
        require(c.owner() == safe, "controller owner is not this Safe");
        require(c.roles() == roles, "controller roles module is not this Roles");
        require(c.marketId() == _marketId(), "controller market is not the pinned market");
        require(c.lineage() == HeldInstall.LINEAGE, "controller lineage is not the declared one");
        require(c.normalRoleKey() == roleKey, "controller normal role key mismatch");
        require(c.supplyAllowanceKey() == allowKey, "controller supply allowance key mismatch");
        require(!c.active() && c.epoch() == 0, "controller is not paused at epoch 0");

        vm.startBroadcast(safe);

        // The Safe enables its own module: msg.sender is the Safe, which is what Safe's
        // `authorized` modifier requires.
        (bool ok,) = safe.call(abi.encodeWithSignature("enableModule(address)", controller));
        require(ok, "enableModule failed");

        HeldInstall.install(
            HeldInstall.Params({
                safe: safe,
                roles: roles,
                controller: controller,
                retireMember: retire,
                normalRole: roleKey,
                supplyKey: allowKey
            })
        );

        vm.stopBroadcast();

        // Paused is not an aspiration; it is asserted after the installation too.
        require(!c.active(), "controller is ACTIVE after installation");
        require(c.epoch() == 0, "controller epoch is not 0");
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
}
