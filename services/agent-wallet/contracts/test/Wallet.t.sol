// SPDX-License-Identifier: MIT
pragma solidity 0.8.11;

import "../src/AgentWallet.sol";
import "../src/FinancingVault.sol";
import "../src/MockStable.sol";
import "../src/PolicyGuard.sol";
import "../src/ReceivableRegistry.sol";

interface Vm {
    function prank(address) external;
    function expectRevert(bytes calldata) external;
    function warp(uint256) external;
}

/// @dev Foundry tests without forge-std, so nothing is downloaded. Each test gets a fresh deployment from setUp().
/// The reverts mirror the Python mock: the same strings for the same attacks (CLAUDE.md 5.4, 11).
contract WalletTest {
    Vm private constant vm = Vm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    address constant AGENT = address(0xA6E7);
    address constant APPROVER = address(0xA990);
    address constant RISK_ORACLE = address(0x0AC1E);
    address constant SELLER = address(0xA1);
    address constant LENDER_A = address(0xA2);
    address constant PLATFORM = address(0xA4);
    address constant BUYER = address(0xB1);
    address constant STRANGER = address(0xBAD);

    bytes32 constant FP = keccak256("fp:happy");
    bytes32 constant FP2 = keccak256("fp:second");
    bytes32 constant FP3 = keccak256("fp:third");
    bytes32 constant DH = keccak256("decision:happy");
    uint256 constant START = 1790000000;
    uint256 constant EXPIRY = 1795000000;

    // tTHB units, 2 decimals: 524,300.00 THB is 52430000
    uint256 constant FACE = 74900000; // 749,000.00
    uint256 constant LIMIT = 52430000; // 524,300.00
    uint256 constant LENDER_FEE = 534786; // 5,347.86
    uint256 constant PLATFORM_FEE = 224700; // 2,247.00

    MockStable token;
    PolicyGuard guard;
    ReceivableRegistry registry;
    FinancingVault vault;
    AgentWallet wallet;

    function setUp() public {
        vm.warp(START);
        token = new MockStable();
        guard = new PolicyGuard(1);
        registry = new ReceivableRegistry(RISK_ORACLE);
        vault = new FinancingVault(token, PLATFORM);
        wallet = new AgentWallet(AGENT, APPROVER, guard);
        guard.wire(address(wallet));
        registry.wire(address(wallet), address(vault), guard);
        vault.wire(address(wallet), registry, guard);
        vault.setSettlementPayer(BUYER);
        // Mandate: 1.5m per tx, 3m per day, 70% advance, 12% APR, human review at 837,500.00, expiring at EXPIRY
        guard.setMandate(150000000, 300000000, 7000, 1200, 83750000, uint64(EXPIRY), keccak256("mandate-1"));
        guard.setCall(address(registry), ReceivableRegistry.register.selector, true);
        guard.setCall(address(vault), FinancingVault.draw.selector, true);
        guard.setCall(address(vault), FinancingVault.repay.selector, true);
        guard.setPayee(SELLER, true);
        guard.setPayee(LENDER_A, true);
        guard.setPayee(PLATFORM, true);
        token.mint(LENDER_A, 500000000);
        token.mint(BUYER, 500000000);
        vm.prank(LENDER_A);
        token.approve(address(vault), type(uint256).max);
        vm.prank(LENDER_A);
        vault.deposit(500000000);
        vm.prank(BUYER);
        token.approve(address(vault), type(uint256).max);
    }

    // ----- helpers -----

    function _exec(address target, bytes memory data, uint256 amount, uint16 apr, bytes32 fp)
        internal
        returns (uint256)
    {
        vm.prank(AGENT);
        return wallet.execute(target, data, amount, apr, fp, DH);
    }

    function _register(bytes32 fp, uint256 face, address seller) internal returns (uint256) {
        bytes memory data = abi.encodeWithSelector(
            ReceivableRegistry.register.selector, fp, bytes32(uint256(1)), seller, face, uint64(START + 30 days)
        );
        return _exec(address(registry), data, 0, 0, fp);
    }

    function _approve(bytes32 fp, uint256 limit, uint16 apr) internal {
        vm.prank(RISK_ORACLE);
        registry.approve(fp, limit, apr, DH);
    }

    function _draw(bytes32 fp, uint256 amount, uint16 apr, uint256 lenderFee, uint256 platformFee)
        internal
        returns (uint256)
    {
        bytes memory data = abi.encodeWithSelector(
            FinancingVault.draw.selector, fp, amount, apr, LENDER_A, lenderFee, platformFee
        );
        return _exec(address(vault), data, amount, apr, fp);
    }

    function _repay(bytes32 fp, uint256 paid) internal returns (uint256) {
        bytes memory data = abi.encodeWithSelector(FinancingVault.repay.selector, fp, paid);
        return _exec(address(vault), data, 0, 0, fp);
    }

    // ----- the happy path and the money -----

    function testHappyPathLoop() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
        require(token.balanceOf(SELLER) == 51670514, "seller nets 516,705.14");
        require(token.balanceOf(PLATFORM) == PLATFORM_FEE, "platform fee 2,247.00");
        require(vault.lenderFees(LENDER_A) == LENDER_FEE, "lender fee booked, not paid");
        _repay(FP, 74900000);
        require(token.balanceOf(LENDER_A) == LIMIT, "lender principal back");
        require(token.balanceOf(SELLER) == 51670514 + 22470000, "seller reserve 224,700.00");
        require(registry.get(FP).status == ReceivableRegistry.Status.Settled, "settled");
    }

    function testLenderClaimsFees() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
        vm.prank(LENDER_A);
        vault.claimFees();
        require(token.balanceOf(LENDER_A) == LENDER_FEE, "lender receives the discount fee");
        require(vault.lenderFees(LENDER_A) == 0, "fees cleared");
    }

    function testDilutedPaymentStillWaterfalls() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
        _repay(FP, 70900000); // V7: 709,000.00 paid
        require(token.balanceOf(LENDER_A) == LIMIT, "lender gets full principal first");
        require(token.balanceOf(SELLER) == 51670514 + 18470000, "seller takes the dilution shortfall");
    }

    function testCannotSettleTwice() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
        _repay(FP, 74900000);
        vm.expectRevert(bytes("AlreadySettled"));
        _repay(FP, 74900000);
    }

    function testSettleBeforeDrawReverts() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.expectRevert(bytes("NotDrawn"));
        _repay(FP, 74900000);
    }

    // ----- the security demo: each must be refused -----

    function testAprAboveMandateReverts() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.expectRevert(bytes("AprAboveMandate"));
        _draw(FP, LIMIT, 1950, LENDER_FEE, PLATFORM_FEE); // A3 / V5: 19.5% APR
    }

    function testAmountAboveLimitReverts() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.expectRevert(bytes("AmountAboveLimit"));
        _draw(FP, 60000000, 1095, LENDER_FEE, PLATFORM_FEE); // A4: 600,000.00 above the approved 524,300.00
    }

    function testAdvanceAboveMandateReverts() public {
        _register(FP, FACE, SELLER);
        _approve(FP, 59920000, 1095); // oracle approves 599,200.00
        vm.expectRevert(bytes("AdvanceAboveMandate"));
        _draw(FP, 59920000, 1095, LENDER_FEE, PLATFORM_FEE); // 80% of 749,000 is above the 70% mandate
    }

    function testAmountAboveTxCapReverts() public {
        _register(FP, 300000000, SELLER); // 3,000,000.00 face
        _approve(FP, 160000000, 1095); // 1,600,000.00 limit
        vm.expectRevert(bytes("AmountAboveTxCap"));
        _draw(FP, 160000000, 1095, 0, 0); // W20: above the 1.5m per-tx cap
    }

    function testDailyCapIsRolling() public {
        _register(FP, 300000000, SELLER);
        _register(FP2, 300000000, SELLER);
        _register(FP3, FACE, SELLER);
        _approve(FP, 150000000, 1095);
        _approve(FP2, 150000000, 1095);
        _approve(FP3, 1000000, 1095);
        _draw(FP, 150000000, 1095, 0, 0);
        _draw(FP2, 150000000, 1095, 0, 0); // 3m in the window, exactly the cap
        vm.expectRevert(bytes("DailyCapExceeded"));
        _draw(FP3, 1000000, 1095, 0, 0);
    }

    function testAlreadyDrawnReverts() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
        vm.expectRevert(bytes("AlreadyDrawn"));
        _draw(FP, 1000000, 1095, 0, 0); // W15: a second draw on the same invoice
    }

    function testNotRegisteredReverts() public {
        vm.expectRevert(bytes("NotRegistered"));
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE); // W22
    }

    function testNotApprovedReverts() public {
        _register(FP, FACE, SELLER);
        vm.expectRevert(bytes("NotApproved"));
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE); // W23: registered, no TX-2 approval
    }

    function testDuplicateRegistrationReverts() public {
        _register(FP, FACE, SELLER);
        vm.expectRevert(bytes("DuplicateReceivable"));
        _register(FP, FACE, SELLER); // A2: the same invoice fingerprint
    }

    function testUnallowlistedSellerReverts() public {
        vm.expectRevert(bytes("PayeeNotAllowed"));
        _register(FP, FACE, STRANGER); // W01: a payee outside the registry
    }

    function testMandateExpiryReverts() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.warp(EXPIRY + 1); // A6a
        vm.expectRevert(bytes("MandateExpired"));
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
    }

    function testPausedWalletRefusesAgent() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.prank(APPROVER);
        wallet.pause(); // A6b: the approver can pause
        vm.expectRevert(bytes("Paused"));
        _draw(FP, LIMIT, 1095, LENDER_FEE, PLATFORM_FEE);
    }

    function testOnlyOwnerUnpauses() public {
        vm.prank(APPROVER);
        wallet.pause();
        vm.prank(APPROVER);
        vm.expectRevert(bytes("NotOwner"));
        wallet.unpause();
    }

    function testTargetOutsideTheAllowlistReverts() public {
        vm.expectRevert(bytes("TargetNotAllowed"));
        _exec(address(0xBAD1), abi.encodeWithSelector(bytes4(0x12345678)), 0, 0, FP); // T4: a contract the agent may not call
    }

    function testOnlyTheAgentCanExecute() public {
        vm.expectRevert(bytes("NotAgent"));
        wallet.execute(address(vault), abi.encodeWithSelector(FinancingVault.repay.selector, FP, 1), 0, 0, FP, DH);
    }

    // ----- human approval -----

    function testLargeDrawWaitsForApproverThenExecutes() public {
        _register(FP, 140000000, SELLER); // 1,400,000.00
        _approve(FP, 98000000, 1095); // advance 980,000.00, above the 837,500.00 review threshold
        uint256 pendingId = _draw(FP, 98000000, 1095, 0, 0);
        require(pendingId == 1, "held, not sent");
        require(token.balanceOf(SELLER) == 0, "nothing moved while held");
        vm.prank(APPROVER);
        wallet.confirm(1, true);
        require(token.balanceOf(SELLER) == 98000000, "executed after approval");
    }

    function testOwnerCannotConfirmAPayment() public {
        _register(FP, 140000000, SELLER);
        _approve(FP, 98000000, 1095);
        _draw(FP, 98000000, 1095, 0, 0);
        vm.expectRevert(bytes("NotApprover"));
        wallet.confirm(1, true); // the rule-setter does not approve payments (CLAUDE.md 2.4)
    }

    function testDeclinedPaymentMovesNothing() public {
        _register(FP, 140000000, SELLER);
        _approve(FP, 98000000, 1095);
        _draw(FP, 98000000, 1095, 0, 0);
        vm.prank(APPROVER);
        wallet.confirm(1, false);
        require(token.balanceOf(SELLER) == 0, "declined: no transfer");
    }

    // ----- one test for each revert string the tests above do not reach (CLAUDE.md 11) -----

    function testAllowanceExceededReverts() public {
        vm.expectRevert(bytes("AllowanceExceeded"));
        vm.prank(STRANGER);
        token.transferFrom(BUYER, STRANGER, 1); // BUYER approved the vault only
    }

    function testInsufficientBalanceReverts() public {
        vm.expectRevert(bytes("InsufficientBalance"));
        vm.prank(STRANGER);
        token.transfer(BUYER, 1); // STRANGER holds nothing
    }

    function testOnlyTheWalletRecordsSpend() public {
        vm.expectRevert(bytes("NotWallet"));
        guard.record(1);
    }

    function testOnlyTheWalletRegistersReceivables() public {
        vm.expectRevert(bytes("NotWallet"));
        registry.register(FP, bytes32(uint256(1)), SELLER, FACE, uint64(START + 30 days));
    }

    function testOnlyTheWalletDraws() public {
        vm.expectRevert(bytes("NotWallet"));
        vault.draw(FP, LIMIT, 1095, LENDER_A, LENDER_FEE, PLATFORM_FEE);
    }

    function testOnlyTheWalletOrVaultChangesStatus() public {
        vm.expectRevert(bytes("NotWalletOrVault"));
        registry.setStatus(FP, ReceivableRegistry.Status.Settled);
    }

    function testEachContractIsWiredOnce() public {
        vm.expectRevert(bytes("AlreadyWired"));
        guard.wire(address(wallet));
        vm.expectRevert(bytes("AlreadyWired"));
        registry.wire(address(wallet), address(vault), guard);
        vm.expectRevert(bytes("AlreadyWired"));
        vault.wire(address(wallet), registry, guard);
    }

    function testMandateBoundsAreHard() public {
        vm.expectRevert(bytes("MandateOutOfBounds"));
        guard.setMandate(150000000, 300000000, 9001, 1200, 83750000, uint64(EXPIRY), keccak256("mandate-x"));
        vm.expectRevert(bytes("MandateOutOfBounds"));
        guard.setMandate(150000000, 300000000, 7000, 3001, 83750000, uint64(EXPIRY), keccak256("mandate-x"));
    }

    function testFeesCannotTakeTheWholeDraw() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.expectRevert(bytes("FeesExceedAmount"));
        _draw(FP, 10000, 1095, 10000, 0); // the lender's fee alone equals the draw
    }

    function testTheVaultCannotPayOutMoreThanItHolds() public {
        _register(FP, 1000000000, SELLER); // 10,000,000.00 face, so the advance rule is not the constraint
        _approve(FP, 600000000, 1095);
        vm.expectRevert(bytes("InsufficientLiquidity"));
        vm.prank(address(wallet));
        vault.draw(FP, 500000100, 1095, LENDER_A, 0, 0); // 5,000,001.00 against 5,000,000.00 held
    }

    function testOnlyTheRiskOracleApproves() public {
        _register(FP, FACE, SELLER);
        vm.expectRevert(bytes("NotRiskOracle"));
        vm.prank(STRANGER);
        registry.approve(FP, LIMIT, 1095, DH);
    }

    function testAnApprovalIsGivenOnce() public {
        _register(FP, FACE, SELLER);
        _approve(FP, LIMIT, 1095);
        vm.expectRevert(bytes("AlreadyApproved"));
        _approve(FP, LIMIT, 1095);
    }

    function testAStrangerCannotPause() public {
        vm.expectRevert(bytes("Unauthorized"));
        vm.prank(STRANGER);
        wallet.pause();
    }

    function testEmptyCallDataIsRefused() public {
        bytes memory empty = new bytes(0);
        vm.expectRevert(bytes("SchemaInvalid"));
        _exec(address(vault), empty, 0, 0, FP);
    }

    function testConfirmNeedsAPendingDraw() public {
        vm.expectRevert(bytes("NotPending"));
        vm.prank(APPROVER);
        wallet.confirm(99, true);
    }

    function testTimeScaleMustBePositive() public {
        vm.expectRevert(bytes("TimeScale"));
        new PolicyGuard(0);
    }

    function testNothingToClaimWithoutFees() public {
        vm.expectRevert(bytes("NothingToClaim"));
        vm.prank(LENDER_A);
        vault.claimFees();
    }
}
