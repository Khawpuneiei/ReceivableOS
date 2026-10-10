// SPDX-License-Identifier: MIT
pragma solidity 0.8.11;

import "./MockStable.sol";
import "./PolicyGuard.sol";
import "./ReceivableRegistry.sol";

/// @notice Lender liquidity, draws and settlement waterfall (CLAUDE.md 5.6). Only AgentWallet can draw or repay.
/// The vault pays the seller bound at registration, so no payee is an input here.
contract FinancingVault {
    MockStable public immutable token;
    address public immutable owner;
    address public immutable platform;
    address public wallet;
    ReceivableRegistry public registry;
    PolicyGuard public guard;
    address public settlementPayer; // the buyer's account that pays the invoice (demo: one account)

    mapping(address => uint256) public deposits;
    mapping(address => uint256) public lenderFees; // discount fees earned, claimable by each lender
    mapping(bytes32 => uint256) public principal;
    mapping(bytes32 => address) public lenderOf;

    event Deposited(address indexed lender, uint256 amount);
    event Drawn(bytes32 indexed fingerprint, address lender, uint256 amount, uint256 lenderFee, uint256 platformFee);
    event Settled(bytes32 indexed fingerprint, uint256 toLender, uint256 toSeller);
    event FeesClaimed(address indexed lender, uint256 amount);

    constructor(MockStable token_, address platform_) {
        owner = msg.sender;
        token = token_;
        platform = platform_;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "NotOwner");
        _;
    }

    modifier onlyWallet() {
        require(msg.sender == wallet, "NotWallet");
        _;
    }

    /// @notice Set once, after the other contracts exist.
    function wire(address wallet_, ReceivableRegistry registry_, PolicyGuard guard_) external onlyOwner {
        require(wallet == address(0), "AlreadyWired");
        wallet = wallet_;
        registry = registry_;
        guard = guard_;
    }

    function setSettlementPayer(address payer) external onlyOwner {
        settlementPayer = payer;
    }

    /// @notice TX-3 (setup): a lender deposits liquidity. Needs an allowance on the token.
    function deposit(uint256 amount) external {
        require(token.transferFrom(msg.sender, address(this), amount), "TransferFailed");
        deposits[msg.sender] += amount;
        emit Deposited(msg.sender, amount);
    }

    /// @notice TX-4: draws against an approved receivable. Checks follow the mock's order.
    function draw(
        bytes32 fingerprint,
        uint256 amount,
        uint16 aprBps,
        address lender,
        uint256 lenderFee,
        uint256 platformFee
    ) external onlyWallet {
        ReceivableRegistry.Receivable memory r = registry.get(fingerprint);
        require(r.status != ReceivableRegistry.Status.None, "NotRegistered");
        require(
            r.status != ReceivableRegistry.Status.Drawn && r.status != ReceivableRegistry.Status.Settled,
            "AlreadyDrawn"
        );
        require(r.status == ReceivableRegistry.Status.Approved, "NotApproved");
        require(aprBps <= r.maxAprBps, "AprAboveMandate");
        require(amount <= r.limit, "AmountAboveLimit");
        require(amount * 10000 <= r.faceValue * guard.maxAdvanceBps(), "AdvanceAboveMandate");
        require(lenderFee + platformFee < amount, "FeesExceedAmount");
        require(token.balanceOf(address(this)) >= amount, "InsufficientLiquidity");

        // Effects first, then the transfers.
        registry.setStatus(fingerprint, ReceivableRegistry.Status.Drawn);
        principal[fingerprint] = amount;
        lenderOf[fingerprint] = lender;
        lenderFees[lender] += lenderFee;

        require(token.transfer(r.seller, amount - lenderFee - platformFee), "TransferFailed");
        require(token.transfer(platform, platformFee), "TransferFailed");
        emit Drawn(fingerprint, lender, amount, lenderFee, platformFee);
    }

    /// @notice TX-5: settlement waterfall. The lender's principal comes first, then the seller's reserve.
    function repay(bytes32 fingerprint, uint256 amountPaid) external onlyWallet {
        ReceivableRegistry.Receivable memory r = registry.get(fingerprint);
        require(r.status != ReceivableRegistry.Status.Settled, "AlreadySettled");
        require(r.status == ReceivableRegistry.Status.Drawn, "NotDrawn");

        uint256 owed = principal[fingerprint];
        uint256 toLender = amountPaid < owed ? amountPaid : owed;
        uint256 toSeller = amountPaid - toLender;

        registry.setStatus(fingerprint, ReceivableRegistry.Status.Settled);
        require(token.transferFrom(settlementPayer, address(this), amountPaid), "TransferFailed");
        if (toLender > 0) {
            require(token.transfer(lenderOf[fingerprint], toLender), "TransferFailed");
        }
        if (toSeller > 0) {
            require(token.transfer(r.seller, toSeller), "TransferFailed");
        }
        emit Settled(fingerprint, toLender, toSeller);
    }

    /// @notice A lender withdraws the discount fees earned on their draws.
    function claimFees() external {
        uint256 amount = lenderFees[msg.sender];
        require(amount > 0, "NothingToClaim");
        lenderFees[msg.sender] = 0;
        require(token.transfer(msg.sender, amount), "TransferFailed");
        emit FeesClaimed(msg.sender, amount);
    }
}
