// SPDX-License-Identifier: MIT
pragma solidity 0.8.11;

/// @notice On-chain mandate (CLAUDE.md 5.6). Checks what the agent may do before AgentWallet calls a target.
/// The check order matches the Python mock: target, expiry, per-tx cap, rolling 24h cap, mandate APR.
/// A compromised agent key can call only the allowlisted (target, selector) pairs, and only within these limits.
contract PolicyGuard {
    uint256 private constant DAY = 1 days;
    uint16 private constant MAX_ADVANCE_BOUND = 9000; // 0.90, the hard bound from CLAUDE.md 5.2
    uint16 private constant MAX_APR_BOUND = 3000; // 0.30, the hard bound from CLAUDE.md 5.2

    address public immutable owner;
    address public wallet;

    uint256 public maxPerTx;
    uint256 public dailyCap;
    uint16 public maxAdvanceBps;
    uint16 public maxAprBps;
    uint256 public humanReviewAbove; // inclusive: amount >= this needs a human approval
    uint64 public expiresAt; // 0 means no expiry
    bytes32 public mandateHash;
    /// @notice Clock unit of block.timestamp: 1 on the EVM (seconds), 1000 on FISCO BCOS (milliseconds).
    /// Time in this contract is always seconds, so expiresAt and the 24h window mean the same on both chains.
    uint256 public immutable timeScale;

    mapping(address => mapping(bytes4 => bool)) public allowedCall;
    mapping(address => bool) public payeeAllowed;

    struct Spend {
        uint64 at;
        uint256 amount;
    }
    Spend[] private spends;
    uint256 private firstLive;

    event MandateSet(bytes32 mandateHash);
    event CallSet(address target, bytes4 selector, bool allowed);
    event PayeeSet(address payee, bool allowed);

    constructor(uint256 timeScale_) {
        require(timeScale_ > 0, "TimeScale");
        timeScale = timeScale_;
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "NotOwner");
        _;
    }

    modifier onlyWallet() {
        require(msg.sender == wallet, "NotWallet");
        _;
    }

    /// @notice Set once, after the wallet exists.
    function wire(address wallet_) external onlyOwner {
        require(wallet == address(0), "AlreadyWired");
        wallet = wallet_;
    }

    function setMandate(
        uint256 maxPerTx_,
        uint256 dailyCap_,
        uint16 maxAdvanceBps_,
        uint16 maxAprBps_,
        uint256 humanReviewAbove_,
        uint64 expiresAt_,
        bytes32 mandateHash_
    ) external onlyOwner {
        require(maxAdvanceBps_ > 0 && maxAdvanceBps_ <= MAX_ADVANCE_BOUND, "MandateOutOfBounds");
        require(maxAprBps_ > 0 && maxAprBps_ <= MAX_APR_BOUND, "MandateOutOfBounds");
        maxPerTx = maxPerTx_;
        dailyCap = dailyCap_;
        maxAdvanceBps = maxAdvanceBps_;
        maxAprBps = maxAprBps_;
        humanReviewAbove = humanReviewAbove_;
        expiresAt = expiresAt_;
        mandateHash = mandateHash_;
        emit MandateSet(mandateHash_);
    }

    function setCall(address target, bytes4 selector, bool allowed) external onlyOwner {
        allowedCall[target][selector] = allowed;
        emit CallSet(target, selector, allowed);
    }

    function setPayee(address payee, bool allowed) external onlyOwner {
        payeeAllowed[payee] = allowed;
        emit PayeeSet(payee, allowed);
    }

    /// @notice Full check for a new action. Returns true when a human must approve it first.
    function check(address target, bytes4 selector, uint256 amount, uint16 aprBps)
        external
        view
        returns (bool needsApproval)
    {
        _validate(target, selector, amount, aprBps, true);
        return amount >= humanReviewAbove;
    }

    /// @notice Re-check of an approved action at confirm time. The daily cap was already charged when it was
    /// proposed, so it is not counted again here.
    function revalidate(address target, bytes4 selector, uint256 amount, uint16 aprBps) external view onlyWallet {
        _validate(target, selector, amount, aprBps, false);
    }

    /// @notice Charges an action to the rolling 24h window. Called before the wallet acts, including pending ones.
    function record(uint256 amount) external onlyWallet {
        uint256 cutoff = _now() > DAY ? _now() - DAY : 0;
        while (firstLive < spends.length && spends[firstLive].at < cutoff) {
            firstLive++;
        }
        spends.push(Spend(uint64(_now()), amount));
    }

    /// @notice Amount charged in the last 24 hours. Matches the mock: entries at or after now minus one day.
    function rollingSpend() public view returns (uint256 total) {
        uint256 cutoff = _now() > DAY ? _now() - DAY : 0;
        for (uint256 i = firstLive; i < spends.length; i++) {
            if (spends[i].at >= cutoff) {
                total += spends[i].amount;
            }
        }
    }

    /// @dev Seconds since the epoch, whatever unit the chain's block.timestamp uses.
    function _now() internal view returns (uint256) {
        return block.timestamp / timeScale;
    }

    function _validate(address target, bytes4 selector, uint256 amount, uint16 aprBps, bool dailyCheck)
        internal
        view
    {
        require(allowedCall[target][selector], "TargetNotAllowed");
        require(expiresAt == 0 || _now() < expiresAt, "MandateExpired");
        require(amount <= maxPerTx, "AmountAboveTxCap");
        if (dailyCheck) {
            require(rollingSpend() + amount <= dailyCap, "DailyCapExceeded");
        }
        require(aprBps <= maxAprBps, "AprAboveMandate");
    }
}
