// SPDX-License-Identifier: MIT
pragma solidity 0.8.11;

import "./PolicyGuard.sol";

/// @notice Receivable registry (CLAUDE.md 5.6). Keyed by the keyed invoice fingerprint from OCR, so a re-saved PDF
/// cannot register twice. The seller is bound here at registration, which is why no payee can come from invoice text.
contract ReceivableRegistry {
    enum Status {
        None,
        Registered,
        Approved,
        Drawn,
        Settled
    }

    struct Receivable {
        bytes32 docHash;
        address seller;
        uint256 faceValue; // tTHB units, 2 decimals
        uint64 dueDate;
        Status status;
        uint256 limit; // set by the risk oracle at approval
        uint16 maxAprBps; // set by the risk oracle at approval
        bytes32 decisionHash; // the policy decision the oracle approved
    }

    address public immutable owner;
    address public immutable riskOracle;
    address public wallet;
    address public vault;
    PolicyGuard public guard;

    mapping(bytes32 => Receivable) private receivables;

    event ReceivableRegistered(bytes32 indexed fingerprint, address seller, uint256 faceValue);
    event ReceivableApproved(bytes32 indexed fingerprint, uint256 limit, uint16 maxAprBps, bytes32 decisionHash);
    event StatusChanged(bytes32 indexed fingerprint, Status status);

    constructor(address riskOracle_) {
        owner = msg.sender;
        riskOracle = riskOracle_;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "NotOwner");
        _;
    }

    modifier onlyWallet() {
        require(msg.sender == wallet, "NotWallet");
        _;
    }

    modifier onlyRiskOracle() {
        require(msg.sender == riskOracle, "NotRiskOracle");
        _;
    }

    /// @notice Set once, after the other contracts exist.
    function wire(address wallet_, address vault_, PolicyGuard guard_) external onlyOwner {
        require(wallet == address(0), "AlreadyWired");
        wallet = wallet_;
        vault = vault_;
        guard = guard_;
    }

    /// @notice Registers a receivable and binds its seller. Payee check first, then duplicates, as in the mock.
    function register(bytes32 fingerprint, bytes32 docHash, address seller, uint256 faceValue, uint64 dueDate)
        external
        onlyWallet
    {
        require(guard.payeeAllowed(seller), "PayeeNotAllowed");
        require(receivables[fingerprint].status == Status.None, "DuplicateReceivable");
        receivables[fingerprint] =
            Receivable(docHash, seller, faceValue, dueDate, Status.Registered, 0, 0, bytes32(0));
        emit ReceivableRegistered(fingerprint, seller, faceValue);
    }

    /// @notice The risk oracle's credit approval (TX-2). Only the oracle key can call it.
    function approve(bytes32 fingerprint, uint256 limit, uint16 maxAprBps, bytes32 decisionHash)
        external
        onlyRiskOracle
    {
        Receivable storage r = receivables[fingerprint];
        require(r.status != Status.None, "NotRegistered");
        require(r.status == Status.Registered, "AlreadyApproved");
        r.status = Status.Approved;
        r.limit = limit;
        r.maxAprBps = maxAprBps;
        r.decisionHash = decisionHash;
        emit ReceivableApproved(fingerprint, limit, maxAprBps, decisionHash);
    }

    /// @notice Lifecycle status, moved only by the wallet or the vault.
    function setStatus(bytes32 fingerprint, Status status) external {
        require(msg.sender == wallet || msg.sender == vault, "NotWalletOrVault");
        receivables[fingerprint].status = status;
        emit StatusChanged(fingerprint, status);
    }

    function get(bytes32 fingerprint) external view returns (Receivable memory) {
        return receivables[fingerprint];
    }
}
