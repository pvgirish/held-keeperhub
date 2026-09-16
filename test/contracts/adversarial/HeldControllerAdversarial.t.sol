// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {HeldController} from "../../../contracts/src/HeldController.sol";
import {MarketParams} from "../../../contracts/src/Interfaces.sol";
import {CleanupFailingToken, FalseReturnToken, MockMorpho, MockRoles, MockToken, ReenteringToken}
    from "./Adversarial.sol";

/// @notice ADVERSARIAL SUITE — labelled mock fixtures, NOT the production profile.
///
/// These branches cannot be reached with well-behaved contracts: real USDC does not
/// return false, and real Morpho does not reenter. The real-pinned-route evidence lives
/// in test/contracts/HeldController.t.sol and is kept entirely separate. Nothing here
/// may be reported as native USDC, real Zodiac Roles or real Morpho behaviour.
contract HeldControllerAdversarialTest is Test {
    uint256 constant PK_RUNNER = 0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a;
    address constant EXECUTOR = address(0xE0E0);
    address constant SAFE = address(0x5AFE);
    bytes32 constant LINEAGE = bytes32(uint256(0x11));
    bytes32 constant NORMAL_ROLE = keccak256("n");
    bytes32 constant RESTORE_ROLE = keccak256("r");
    bytes32 constant SUPPLY_KEY = keccak256("sk");
    bytes32 constant RESTORE_KEY = keccak256("rk");
    bytes32 constant NW_KEY = keccak256("nw");
    bytes32 constant NC_KEY = keccak256("nc");
    bytes32 constant RC_KEY = keccak256("rc");

    uint128 constant LS = 50_000e6;
    uint128 constant LR = 10_000e6;

    MockRoles roles;
    MockMorpho morpho;
    address runner;

    function _deploy(MockToken token) internal returns (HeldController c, MarketParams memory mp) {
        roles = new MockRoles();
        morpho = new MockMorpho();
        roles.setKeys(SUPPLY_KEY, RESTORE_KEY);
        roles.setAllowances(LS, LR);
        morpho.setToken(address(token));
        token.init(SAFE, address(morpho), 50_000e6);

        mp = MarketParams({
            loanToken: address(token),
            collateralToken: address(0xC0),
            oracle: address(0x0A),
            irm: address(0x12),
            lltv: 860000000000000000
        });
        c = new HeldController(
            SAFE, address(roles), address(morpho), address(token),
            keccak256(abi.encode(mp)), LINEAGE, HeldController.Keys({
                normalRole: NORMAL_ROLE,
                restorationRole: RESTORE_ROLE,
                supplyAmount: SUPPLY_KEY,
                normalWithdrawAmount: NW_KEY,
                restorationAmount: RESTORE_KEY,
                normalCount: NC_KEY,
                restorationCount: RC_KEY
            })
        );

        HeldController.Policy memory p;
        p.Ls = LS; p.Ln = 50_000e6; p.Lr = LR;
        p.Ms = 40_000e6; p.Mn = 10_000e6; p.Mr = 5_000e6;
        p.ms = 1_000e6; p.mn = 1_000e6;
        p.F = 1_000e6; p.H = 0;
        p.Nn = 10; p.Nr = 5; p.dn = 0; p.dr = 0;
        roles.setEconomicTarget(address(morpho));
        roles.setLane(NORMAL_ROLE, MockMorpho.supply.selector, SUPPLY_KEY, NC_KEY);
        roles.setLane(NORMAL_ROLE, MockMorpho.withdraw.selector, NW_KEY, NC_KEY);
        roles.setLane(RESTORE_ROLE, MockMorpho.withdraw.selector, RESTORE_KEY, RC_KEY);
        roles.setKeyBalance(NW_KEY, p.Ln);
        roles.setKeyBalance(NC_KEY, uint128(p.Nn));
        roles.setKeyBalance(RC_KEY, uint128(p.Nr));
        HeldController.ExpectedState memory e;
        runner = vm.addr(PK_RUNNER);
        vm.prank(SAFE);
        c.activate(1, 1, runner, EXECUTOR, p, e);
    }

    function _env(HeldController c, MarketParams memory mp, bytes32 opId, uint256 amount)
        internal view returns (HeldController.Envelope memory env)
    {
        env.operationId = opId;
        env.sourceIdentityHash = keccak256("src");
        env.payloadHash = c.actionHash(1, keccak256(abi.encode(mp)), mp.loanToken, amount, SAFE);
        env.actionFamily = 1;
        env.safe = SAFE;
        env.lineage = LINEAGE;
        env.epoch = 1;
        env.policyVersion = 1;
        env.runner = runner;
    }

    function _sig(HeldController c, HeldController.Envelope memory env) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(PK_RUNNER, c.signingHash(env));
        return abi.encodePacked(r, s, v);
    }

    /// @dev Control: the harness itself must be able to SUCCEED, or every negative below
    ///      would pass for the wrong reason.
    function test_MockHarnessHappyPathSucceeds() public {
        (HeldController c, MarketParams memory mp) = _deploy(new MockToken());
        HeldController.Envelope memory env = _env(c, mp, keccak256("ok"), 5_000e6);
        bytes memory sig = _sig(c, env);
        vm.prank(EXECUTOR);
        c.executeSupply(env, mp, 5_000e6, sig);
        assertEq(c.usedSupply(), 5_000e6);
        assertEq(morpho.supplyCount(), 1, "economic action was reached");
    }

    function test_TokenReturningFalseIsRejected() public {
        (HeldController c, MarketParams memory mp) = _deploy(new FalseReturnToken());
        HeldController.Envelope memory env = _env(c, mp, keccak256("false"), 5_000e6);
        bytes memory sig = _sig(c, env);
        vm.prank(EXECUTOR);
        vm.expectRevert(abi.encodeWithSelector(HeldController.TokenReturnedFalse.selector, mp.loanToken));
        c.executeSupply(env, mp, 5_000e6, sig);
        assertEq(morpho.supplyCount(), 0, "nothing executed");
        assertEq(c.usedSupply(), 0);
    }

    /// @dev The required cleanup-failure branch. The token refuses the cleanup approval
    ///      ONLY after observing that supply already ran, so the revert identity is
    ///      itself proof that the economic action was reached before cleanup failed.
    function test_CleanupFailureAfterEconomicActionRollsBackEverything() public {
        CleanupFailingToken token = new CleanupFailingToken();
        (HeldController c, MarketParams memory mp) = _deploy(token);
        token.setMorpho(morpho);

        uint256 safeBefore = token.balanceOf(SAFE);
        HeldController.Envelope memory env = _env(c, mp, keccak256("cleanup"), 5_000e6);
        bytes memory sig = _sig(c, env);

        vm.prank(EXECUTOR);
        vm.expectRevert(CleanupFailingToken.CleanupFailedAfterSupply.selector);
        c.executeSupply(env, mp, 5_000e6, sig);

        // Everything the economic action did is gone again.
        assertEq(morpho.supplyCount(), 0, "supply rolled back");
        assertEq(token.balanceOf(SAFE), safeBefore, "no token moved");
        assertEq(c.usedSupply(), 0, "counter not advanced");
        assertFalse(c.isConsumed(keccak256("cleanup")), "operation id not consumed");
        assertEq(token.allowance(SAFE, address(morpho)), 0, "no residual approval");
    }

    function test_ReentrancyIsRefused() public {
        ReenteringToken token = new ReenteringToken();
        (HeldController c, MarketParams memory mp) = _deploy(token);
        token.arm(c);

        HeldController.Envelope memory env = _env(c, mp, keccak256("reenter"), 5_000e6);
        bytes memory sig = _sig(c, env);
        vm.prank(EXECUTOR);
        vm.expectRevert(ReenteringToken.ReentrancyWasRefused.selector);
        c.executeSupply(env, mp, 5_000e6, sig);
        assertEq(c.usedSupply(), 0);
    }
}
