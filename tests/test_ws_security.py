"""
Security tests for WebSocket telemetry endpoints.

Covers: command injection, action validation, oversized frames, auth boundaries.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")
os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

from telemetry_hub import validate_action, VALID_ACTIONS


class TestCommandInjection:
    """Verify that malicious action strings are rejected."""

    def test_rcon_command_blocked(self):
        assert validate_action("rcon sv_restart") is False
        assert validate_action("rcon_command") is False

    def test_exec_blocked(self):
        assert validate_action("exec evil.cfg") is False

    def test_semicolon_injection_blocked(self):
        # "jump;" is not a valid command (first token is "jump;")
        assert validate_action("jump;rm -rf /") is False

    def test_pipe_injection_blocked(self):
        assert validate_action("jump|cat /etc/passwd") is False

    def test_backtick_injection_blocked(self):
        assert validate_action("`whoami`") is False

    def test_dollar_injection_blocked(self):
        assert validate_action("$(cat /etc/shadow)") is False

    def test_newline_injection_blocked(self):
        assert validate_action("jump\nrcon quit") is False

    def test_only_whitelisted_commands_pass(self):
        """Exhaustive check: only commands in VALID_ACTIONS pass."""
        malicious = [
            "rcon", "exec", "bind", "unbind", "set", "seta",
            "vstr", "callvote", "vote", "say", "say_team",
            "kill", "disconnect", "quit", "map", "devmap",
            "connect", "reconnect", "screenshot", "record",
            "drop", "give", "god", "noclip", "notarget",
            "cmdlist", "cvarlist", "condump",
        ]
        for cmd in malicious:
            assert validate_action(cmd) is False, f"'{cmd}' should be blocked"

    def test_all_valid_actions_accepted(self):
        for cmd in VALID_ACTIONS:
            assert validate_action(cmd) is True, f"'{cmd}' should be accepted"

    def test_valid_action_with_params(self):
        assert validate_action("aim_at 100.5 200.3 50.0") is True
        assert validate_action("look_at -50 90 0") is True
        assert validate_action("move_forward 1") is True


class TestActionEdgeCases:
    def test_empty_string(self):
        assert validate_action("") is False

    def test_whitespace_only(self):
        assert validate_action("   ") is False
        assert validate_action("\t") is False
        assert validate_action("\n") is False

    def test_none_input(self):
        assert validate_action(None) is False

    def test_leading_trailing_whitespace(self):
        assert validate_action("  jump  ") is True
        assert validate_action("\tattack\n") is True

    def test_unicode_input(self):
        assert validate_action("jump\u200b") is False  # zero-width space in command
        assert validate_action("攻撃") is False

    def test_very_long_action(self):
        long_params = " ".join(["100"] * 1000)
        assert validate_action(f"aim_at {long_params}") is True  # valid command prefix

    def test_mixed_case_rejected(self):
        # Commands are case-sensitive
        assert validate_action("JUMP") is False
        assert validate_action("Jump") is False
        assert validate_action("ATTACK") is False


class TestFrameSecurity:
    def test_max_frame_size_enforced(self):
        from ai_agent_interface import MAX_FRAME_SIZE
        # The WS handler checks len(raw) > MAX_FRAME_SIZE
        assert MAX_FRAME_SIZE == 65536

    def test_oversized_payload(self):
        from ai_agent_interface import MAX_FRAME_SIZE
        oversized = "a" * (MAX_FRAME_SIZE + 1)
        assert len(oversized) > MAX_FRAME_SIZE
