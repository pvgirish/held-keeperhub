// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {console2} from "forge-std/Test.sol";

import {HeldController} from "../../contracts/src/HeldController.sol";
import {IERC20, IMorpho, IRoles} from "../../contracts/src/Interfaces.sol";
import {HeldForkHarness} from "./HeldForkHarness.sol";

/// @notice Measure the gas of the ONE `executeSupply` the M1 execution would broadcast.
///
/// ## Why this file exists
///
/// `evidence/P03/m1-cost-ceiling.json` carried `one_execute_supply: 1200000` with the
/// source `"NOT MEASURED — a stated upper bound"`, and both that file and
/// `evidence/P03/public-action-request.json` say the figure "should be replaced with its
/// receipt before request B is granted". This is that replacement.
///
/// ## What is measured, exactly
///
/// The bytes are `fixtures/generated/composed-call.json` — the SAME calldata the composed
/// run builds from the real pinned Almanak compiler output and executes against the real
/// controller. Nothing is re-encoded here and no argument is adjusted to make a number
/// come out nicer; if the bytes did not execute, the measurement would revert rather than
/// report.
///
/// Two components are recorded separately because they are established differently:
///
///   * `execution_gas` — a `gasleft()` delta across the outer call, so it is the EVM's own
///     accounting for the controller's work: the Roles route, the three inner calls
///     (approve, Morpho.supply, approve-to-zero), every readback, and the consumption
///     writes. It includes the CALL opcode and its memory expansion.
///   * `intrinsic_gas` — COMPUTED, not measured: 21,000 plus 16 per non-zero and 4 per
///     zero calldata byte (EIP-2028). A `gasleft()` delta inside a test cannot observe
///     this, because there is no transaction envelope to charge it against.
///
/// The total of the two is what a receipt's `gasUsed` would report, with one deliberate
/// difference stated below.
///
/// ## What this is NOT, said plainly
///
///   * **Not a receipt.** A receipt requires a real transaction. Producing one on the fork
///     would need the controller deployed AND activated on anvil rather than inside the
///     forge VM, and the composed calldata rebuilt against that address, because the
///     EIP-712 domain separator commits to the controller. That path does not exist and
///     was not invented for a figure this size.
///   * **Not refund-adjusted.** EIP-3529 storage refunds are applied at the end of a real
///     transaction and can only make a receipt LOWER. Reporting the un-refunded figure
///     errs in the ceiling direction, which is the direction a ceiling must err in.
///   * **Not the whole Base fee.** Base is an OP-stack chain and charges an L1 data fee on
///     top of `gasUsed * gasPrice`. It is not part of any gas figure and is not included
///     here — exactly as it is not included in the existing ceremony measurement. This is
///     recorded as a known gap, not silently omitted.
///   * **Not a mainnet transaction.** Nothing leaves the local fork. Nothing is deployed
///     publicly and nothing is spent.
contract HeldExecuteSupplyGasForkTest is HeldForkHarness {
    string constant CALL_FILE = "./fixtures/generated/composed-call.json";
    string constant OUT_FILE = "./fixtures/generated/execute-supply-gas.json";

    /// @dev Identical to the composed run's activation. The fixture's default per-action
    ///      minimum is 1,000 USDC and the real compiler produced 100 USDC, so `ms` is
    ///      lowered to admit the action rather than the action being rewritten to fit.
    ///      Every other limit is unchanged. Measuring under a DIFFERENT activation than
    ///      the composed run executes under would measure a different call.
    function _activateForComposedAmount(uint256 amount) internal {
        HeldController.Policy memory p = _policy();
        require(amount <= p.Ms, "composed amount exceeds the per-action maximum");
        p.ms = uint128(amount);
        _activateWith(1, runnerB, p);
    }

    /// @dev 21,000 + 16 per non-zero byte + 4 per zero byte. No access list, not a
    ///      contract creation, so there is nothing else in the intrinsic cost.
    function _intrinsicGas(bytes memory data) internal pure returns (uint256 g) {
        g = 21000;
        for (uint256 i = 0; i < data.length; i++) {
            g += data[i] == 0 ? 4 : 16;
        }
    }

    function test_MeasureTheOneExecuteSupplyBroadcast() public {
        string memory raw = vm.readFile(CALL_FILE);
        bytes memory data = vm.parseJsonBytes(raw, ".calldata");
        uint256 amount = vm.parseUint(vm.parseJsonString(raw, ".amount"));
        bytes32 opId = vm.parseJsonBytes32(raw, ".operationId");

        _activateForComposedAmount(amount);

        uint256 safeBefore = IERC20(USDC).balanceOf(safe);
        (uint256 shares0,,) = IMorpho(MORPHO).position(marketId, safe);

        vm.prank(EXECUTOR);
        uint256 before = gasleft();
        (bool ok, bytes memory ret) = address(controller).call(data);
        uint256 executionGas = before - gasleft();
        if (!ok) {
            assembly { revert(add(ret, 0x20), mload(ret)) }
        }

        // A gas number is only worth recording if the call it measures actually did the
        // work. Without these, a call that reverted cheaply — or one the controller
        // refused — would be filed as a measurement of the execution.
        assertEq(safeBefore - IERC20(USDC).balanceOf(safe), amount, "exact Safe debit");
        (uint256 shares1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertGt(shares1, shares0, "Morpho position increased");
        assertTrue(controller.isConsumed(opId), "operation id not consumed");
        assertEq(controller.usedSupply(), amount, "Held counter");

        uint256 intrinsic = _intrinsicGas(data);
        uint256 total = executionGas + intrinsic;

        // The figure being replaced. If a change ever pushed the real cost above the old
        // unmeasured bound, that is a finding, not a number to quietly write down.
        assertLt(total, 1200000, "the measured cost exceeds the unmeasured bound it replaces");

        string memory o = "execute-supply-gas";
        vm.serializeUint(o, "execution_gas", executionGas);
        vm.serializeUint(o, "intrinsic_gas", intrinsic);
        vm.serializeUint(o, "calldata_bytes", data.length);
        vm.serializeUint(o, "amount", amount);
        vm.serializeAddress(o, "controller", address(controller));
        vm.serializeUint(o, "chain_id", block.chainid);
        vm.serializeUint(o, "fork_block", block.number);
        vm.serializeUint(o, "superseded_upper_bound", 1200000);
        string memory out = vm.serializeUint(o, "total_gas", total);
        vm.writeJson(out, OUT_FILE);

        console2.log("execute_supply execution gas:", executionGas);
        console2.log("execute_supply intrinsic gas:", intrinsic);
        console2.log("execute_supply total gas    :", total);
    }
}
