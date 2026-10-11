// SPDX-License-Identifier: MIT
pragma solidity 0.8.11;

import "./PolicyGuard.sol";

/// @notice The agent's on-chain wallet (CLAUDE.md 5.6). Every agent action passes PolicyGuard first.
/// The agent key can call execute() only. Approving, unpausing and changing roles are separate keys.
/// LLM output never reaches this contract directly: the Python service validates it before a call is built.
contract AgentWallet {
    address public immutable owner;
    address public agent;
    address public approver; // the Finance approver: confirms large payments and can pause
    PolicyGuard public immutable guard;
    bool public paused;

    struct Pending {
        address target;
        bytes4 selector;
        bytes data;
        uint256 amount;
        uint16 aprBps;
        bytes32 fingerprint;
        bytes32 decisionHash;
    }
    mapping(uint256 => Pending) public pending;
    uint256 public nextPendingId = 1;

    event DecisionExecuted(bytes32 indexed fingerprint, bytes32 decisionHash, address target, uint256 amount);
    event ApprovalRequired(uint256 indexed pendingId, bytes32 indexed fingerprint, uint256 amount);
    event ApprovalConfirmed(uint256 indexed pendingId);
    event ApprovalDeclined(uint256 indexed pendingId);
    event Paused(address by);
    event Unpaused(address by);
    event AgentSet(address agent);
    event ApproverSet(address approver);
    event AuditAnchored(bytes32 root, uint256 entries);

    constructor(address agent_, address approver_, PolicyGuard guard_) {
        owner = msg.sender;
        agent = agent_;
        approver = approver_;
        guard = guard_;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "NotOwner");
        _;
    }

    modifier onlyAgent() {
        require(msg.sender == agent, "NotAgent");
        _;
    }

    modifier onlyApprover() {
        require(msg.sender == approver, "NotApprover");
        _;
    }

    function setAgent(address agent_) external onlyOwner {
        agent = agent_;
        emit AgentSet(agent_);
    }

    function setApprover(address approver_) external onlyOwner {
        approver = approver_;
        emit ApproverSet(approver_);
    }

    /// @notice The owner or the approver can pause. Only the owner can unpause.
    function pause() external {
        require(msg.sender == owner || msg.sender == approver, "Unauthorized");
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyOwner {
        paused = false;
        emit Unpaused(msg.sender);
    }

    /// @notice The only entry point for the agent. Runs the guard, then either calls the target or holds the call
    /// for an approver. A failed target call reverts the whole transaction with the target's reason.
    function execute(
        address target,
        bytes calldata data,
        uint256 amount,
        uint16 aprBps,
        bytes32 fingerprint,
        bytes32 decisionHash
    ) external onlyAgent returns (uint256 pendingId) {
        require(!paused, "Paused");
        require(data.length >= 4, "SchemaInvalid");
        bytes4 selector = bytes4(data[:4]);

        bool needsApproval = guard.check(target, selector, amount, aprBps);
        guard.record(amount); // effects before the external call

        if (needsApproval) {
            pendingId = nextPendingId++;
            Pending storage p = pending[pendingId];
            p.target = target;
            p.selector = selector;
            p.data = data;
            p.amount = amount;
            p.aprBps = aprBps;
            p.fingerprint = fingerprint;
            p.decisionHash = decisionHash;
            emit ApprovalRequired(pendingId, fingerprint, amount);
            return pendingId;
        }

        emit DecisionExecuted(fingerprint, decisionHash, target, amount); // before the call: a revert rolls it back
        _call(target, data);
    }

    /// @notice The approver releases or declines a held action. The approver is not the rule-setter (owner).
    function confirm(uint256 pendingId, bool approve) external onlyApprover {
        require(!paused, "Paused");
        Pending storage p = pending[pendingId];
        require(p.target != address(0), "NotPending");

        address target = p.target;
        bytes4 selector = p.selector;
        uint256 amount = p.amount;
        uint16 aprBps = p.aprBps;
        bytes32 fingerprint = p.fingerprint;
        bytes32 decisionHash = p.decisionHash;
        bytes memory data = p.data;
        delete pending[pendingId];

        if (!approve) {
            emit ApprovalDeclined(pendingId);
            return;
        }
        guard.revalidate(target, selector, amount, aprBps);
        emit ApprovalConfirmed(pendingId);
        emit DecisionExecuted(fingerprint, decisionHash, target, amount);
        _call(target, data);
    }

    /// @notice Anchors the audit log head on chain (CLAUDE.md 5.8).
    function anchorAudit(bytes32 root, uint256 entries) external onlyAgent {
        emit AuditAnchored(root, entries);
    }

    function _call(address target, bytes memory data) internal {
        (bool ok, bytes memory ret) = target.call(data);
        if (!ok) {
            // Bubble up the target's revert reason unchanged, so the string code reaches the caller.
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
    }
}
