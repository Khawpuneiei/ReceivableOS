// SPDX-License-Identifier: MIT
pragma solidity 0.8.11;

import "../src/PolicyGuard.sol";

interface VmTime {
    function warp(uint256) external;
    function expectRevert(bytes calldata) external;
}

/// @dev FISCO BCOS reports block.timestamp in milliseconds; the EVM reports seconds. A PolicyGuard built with
/// timeScale 1000 must read the clock in seconds, so expiresAt and the 24h window mean the same moment on both.
contract TimeScaleTest {
    VmTime private constant vm = VmTime(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    address constant TARGET = address(0xBEEF);
    bytes4 constant SELECTOR = bytes4(keccak256("draw(uint256)"));
    uint256 constant EXPIRY = 1800000000; // seconds
    uint256 constant START = 1700000000; // seconds

    function _guard() internal returns (PolicyGuard guard) {
        guard = new PolicyGuard(1000);
        guard.wire(address(this));
        guard.setMandate(100000000, 300000000, 7000, 1200, 1000000000, uint64(EXPIRY), keccak256("time-scale"));
        guard.setCall(TARGET, SELECTOR, true);
    }

    function testMandateExpiryIsReadInSecondsOnAMillisecondChain() public {
        PolicyGuard guard = _guard();
        vm.warp((EXPIRY - 1) * 1000); // one second before expiry, in milliseconds
        guard.check(TARGET, SELECTOR, 100, 1000);
        vm.warp(EXPIRY * 1000); // at expiry
        vm.expectRevert(bytes("MandateExpired"));
        guard.check(TARGET, SELECTOR, 100, 1000);
    }

    function testRollingWindowIsOneDayOfSecondsOnAMillisecondChain() public {
        PolicyGuard guard = _guard();
        vm.warp(START * 1000);
        guard.record(100);
        assert(guard.rollingSpend() == 100);
        vm.warp((START + 86400 - 1) * 1000); // still inside the window
        assert(guard.rollingSpend() == 100);
        vm.warp((START + 86400 + 1) * 1000); // a day and a second later: the spend has rolled out
        assert(guard.rollingSpend() == 0);
    }
}
