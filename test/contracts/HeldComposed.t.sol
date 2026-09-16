// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {HeldController} from "../../contracts/src/HeldController.sol";
import {IERC20, IMorpho, IRoles, MarketParams} from "../../contracts/src/Interfaces.sol";
import {HeldForkHarness} from "./HeldForkHarness.sol";

/// @notice The composed local run: Held's OWN request bytes, executed by the real
///         controller against real pinned Morpho.
///
/// Everything before this file proved pieces. The Python adapter proved it could admit a
/// real compiler bundle, sign an envelope and encode a request; the fork proved the
/// controller enforces its limits. Nothing proved those two halves fit together.
///
/// This does. `fixtures/generated/composed-call.json` is written by
/// `tests/integration/test_p03_composed.py` from the REAL pinned Almanak compiler
/// output: admitted action -> runner signature -> typed controller call -> ABI-encoded
/// calldata. This test takes those bytes verbatim, hands them to the deployed controller
/// through the configured executor, and checks the economic effect.
///
/// If the Python encoder and the Solidity ABI disagreed by a single byte, the controller
/// would revert and this test would fail. That is the point: it is the first thing in
/// the project that would catch such a disagreement.
///
/// WHAT THIS IS NOT. KeeperHub is not involved. The calldata is delivered directly,
/// because the hosted route needs an organisation credential (L10) that does not exist.
/// So this establishes that Held builds a request the real controller accepts and that
/// the request produces the intended effect. It does NOT establish that KeeperHub would
/// deliver it, nor that its server-side encoder reproduces these bytes.
contract HeldComposedForkTest is HeldForkHarness {
    string constant CALL_FILE = "./fixtures/generated/composed-call.json";

    /// @dev The fixture's default policy sets the per-action minimum at 1,000 USDC,
    ///      but the real pinned compiler produced a 100 USDC supply. A customer who
    ///      wants that action authorized must set a minimum that admits it, so the
    ///      composed run activates with ms lowered rather than rewriting the compiler's
    ///      output to fit the fixture. Every other limit is unchanged.
    function _activateForComposedAmount(uint256 amount) internal {
        HeldController.Policy memory p = _policy();
        require(amount <= p.Ms, "composed amount exceeds the per-action maximum");
        p.ms = uint128(amount);
        _activateWith(1, runnerB, p);
    }

    function _readCall() internal view returns (bytes memory data, uint256 amount, bytes32 opId) {
        string memory raw = vm.readFile(CALL_FILE);
        data = vm.parseJsonBytes(raw, ".calldata");
        amount = vm.parseUint(vm.parseJsonString(raw, ".amount"));
        opId = vm.parseJsonBytes32(raw, ".operationId");
    }

    /// @dev The adapter's own bytes, executed. The controller was deployed by this run's
    ///      setUp, and the Python side built the call against the address a previous run
    ///      published -- so an address mismatch would surface as a signature failure
    ///      rather than passing silently.
    function test_HeldsOwnRequestBytesExecuteAgainstTheRealController() public {
        (bytes memory data, uint256 amount, bytes32 opId) = _readCall();

        // The signing vector was produced under epoch 1 with runnerB, so the controller
        // is activated exactly that way. The REQUEST is never adjusted to fit.
        _activateForComposedAmount(amount);

        uint256 safeBefore = IERC20(USDC).balanceOf(safe);
        (uint256 shares0,,) = IMorpho(MORPHO).position(marketId, safe);
        (,,, uint128 quotaBefore,) = IRoles(roles).allowances(allowKey);

        vm.prank(EXECUTOR);
        (bool ok, bytes memory ret) = address(controller).call(data);
        if (!ok) {
            // Surface the controller's reason rather than a bare "call failed".
            assembly { revert(add(ret, 0x20), mload(ret)) }
        }

        // The economic effect the adapter intended, read from chain state.
        assertEq(safeBefore - IERC20(USDC).balanceOf(safe), amount, "exact Safe debit");
        (uint256 shares1,,) = IMorpho(MORPHO).position(marketId, safe);
        assertGt(shares1, shares0, "Morpho position increased");
        assertEq(controller.usedSupply(), amount, "Held counter");
        assertEq(controller.normalCount(), 1);

        // The native quota was charged exactly once by the economic call.
        (,,, uint128 quotaAfter,) = IRoles(roles).allowances(allowKey);
        assertEq(uint256(quotaBefore) - uint256(quotaAfter), amount, "native quota charged once");

        // And the operation is consumed under the payload the adapter bound to it --
        // which is precisely what the adapter's reconcile() reads to reach CONFIRMED.
        assertTrue(controller.isConsumed(opId), "operation id not consumed");
        assertEq(controller.consumed(opId), controller.actionHash(1, marketId, USDC, amount, safe),
            "consumed payload is not the admitted action hash");

        // Publish the reconciliation input so the Python side can complete the loop
        // against a real reading instead of an in-test double.
        string memory o = "composed-result";
        vm.serializeBytes32(o, "operationId", opId);
        vm.serializeBytes32(o, "consumedPayload", controller.consumed(opId));
        vm.serializeAddress(o, "controller", address(controller));
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeUint(o, "usedSupply", controller.usedSupply());
        string memory out = vm.serializeBool(o, "executed", true);
        vm.writeJson(out, "./fixtures/generated/composed-result.json");
    }

    /// @dev A single flipped byte in the adapter's request must not execute. This is what
    ///      makes the test above a real cross-language check rather than a smoke test:
    ///      the controller recomputes the payload from the arguments it receives, so
    ///      corrupted bytes cannot satisfy the signature.
    function test_ASingleCorruptedByteInTheRequestIsRefused() public {
        (bytes memory data, uint256 amount,) = _readCall();
        _activateForComposedAmount(amount);

        // Flip a byte inside the encoded arguments, past the 4-byte selector.
        bytes memory corrupted = data;
        corrupted[80] = bytes1(uint8(corrupted[80]) ^ 0x01);

        vm.prank(EXECUTOR);
        (bool ok,) = address(controller).call(corrupted);
        assertFalse(ok, "a corrupted request executed");
        assertEq(controller.usedSupply(), 0, "corrupted request moved funds");
    }

    /// @dev The same bytes, replayed. The controller consumes the operation id, so the
    ///      second delivery of an identical request cannot execute again -- which is the
    ///      on-chain half of the adapter's duplicate-submission defence.
    function test_ReplayingTheSameRequestBytesIsRefused() public {
        (bytes memory data, uint256 amount, bytes32 opId) = _readCall();
        _activateForComposedAmount(amount);

        vm.prank(EXECUTOR);
        (bool first,) = address(controller).call(data);
        assertTrue(first, "the first delivery should succeed");
        uint128 used = controller.usedSupply();

        vm.prank(EXECUTOR);
        (bool second,) = address(controller).call(data);
        assertFalse(second, "the identical request executed twice");
        assertEq(controller.usedSupply(), used, "a replay changed consumption");
        assertTrue(controller.isConsumed(opId));
    }
}
