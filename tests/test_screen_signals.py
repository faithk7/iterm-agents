"""Tests for composer-anchored activity signals."""

from __future__ import annotations

from iterm_agents.models import AgentType
from iterm_agents.screen_signals import (
    cursor_activity_signature,
    cursor_turn_is_live,
    screen_shows_active_turn,
)


class TestScreenShowsActiveTurn:
    def test_cursor_running_footer(self) -> None:
        screen = "\n".join(
            [
                "  some command output",
                "  ⠠⠜ Running  8.98k tokens",
                "  → Add a follow-up                                       ctrl+c to stop",
                "  Grok 4.7 256K High                                      Run Everything",
            ]
        )
        assert screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_cursor_idle_follow_up_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  → Add a follow-up",
                "  Grok 4.7 256K High · 35.1%                              Run Everything",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_running_mention_above_the_footer_is_ignored(self) -> None:
        older = [f"  Running {index} tokens in the transcript" for index in range(20)]
        screen = "\n".join(
            [
                *older,
                "  → Add a follow-up",
                "  Grok 4.7 256K High                                      Run Everything",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_other_agents_ignore_the_cursor_footer(self) -> None:
        screen = "  ⠠⠜ Running  8.98k tokens\n  ctrl+c to stop"
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_leftover_running_line_above_an_idle_composer_is_ignored(self) -> None:
        screen = "\n".join(
            [
                "  ⠰⠳ Running  2.79k tokens",
                "  ▄▄▄▄▄▄▄▄",
                "  → Add a follow-up",
                "  ▀▀▀▀▀▀▀▀",
                "  Grok 4.7 256K High · 88.5% · 14 files edited            Run Everything",
                "  ~",
            ]
        )
        assert cursor_activity_signature(screen) is None
        assert not screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_signature_tracks_the_spinner_and_a_tool_timer(self) -> None:
        first = "\n".join(
            [
                "    import asyncio 2.6s in code/iterm-agents",
                "  ⠰⠳ Running  2.79k tokens",
                "  ▄▄▄▄▄▄▄▄",
                "  → Add a follow-up                                       ctrl+c to stop",
                "  ▀▀▀▀▀▀▀▀",
                "  3 tasks",
                "  ~",
            ]
        )
        spun = first.replace("⠰⠳", "⠠⠜")
        later = first.replace("2.6s", "7.6s")
        signature = cursor_activity_signature(first)
        assert signature is not None
        # The spinner ticks while the turn lives, so it counts as motion.
        assert cursor_activity_signature(spun) != signature
        assert cursor_activity_signature(later) != signature
        # A frame redrawn with the same spinner glyph is not motion.
        assert cursor_activity_signature(first) == signature

    def test_frozen_footer_is_not_a_live_turn(self) -> None:
        signature = "Running 2.79k tokens"
        assert cursor_turn_is_live(signature, None, 0)
        assert cursor_turn_is_live(signature, signature, 29)
        assert not cursor_turn_is_live(signature, signature, 30)
        assert cursor_turn_is_live("Running 2.80k tokens", signature, 40)


class TestDevinScreenShowsActiveTurn:
    def test_running_status_line_above_the_input_box(self) -> None:
        screen = "\n".join(
            [
                "  │ some tool output",
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Guide Devin while it works",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_esc_again_variant_is_running(self) -> None:
        screen = "\n".join(
            [
                "  ⠀⠸ Thinking · 12s (esc again to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Guide Devin while it works",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_idle_composer_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  Report updated.",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 High                      Context: 98k / 262k tokens (37%)",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_transcript_echo_without_box_border_is_ignored(self) -> None:
        screen = "\n".join(
            [
                '  │ print("(esc twice to interrupt)")',
                "  │ Exited with code 0",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_hint_above_the_footer_window_is_ignored(self) -> None:
        older = [f"  transcript line {index}" for index in range(15)]
        screen = "\n".join(
            [
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                *older,
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_other_agents_ignore_the_devin_hint(self) -> None:
        screen = "\n".join(
            [
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)


class TestCodexScreenShowsActiveTurn:
    def test_working_status_line_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  • Explored",
                "  └ Read index.tsx",
                "  • Working (4m 34s • esc to interrupt)",
                "    └ Tip: Press ⌃r to search previously entered prompts.",
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ? for shortcuts     ⚠ 1 warning · f2 to view",
            ]
        )
        assert screen_shows_active_turn(AgentType.CODEX, screen)

    def test_shortcuts_footer_anchors_composerless_variant(self) -> None:
        screen = "\n".join(
            [
                "  • Working (8s • esc to interrupt)",
                "  Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ← for agents · ? for shortcuts",
            ]
        )
        assert screen_shows_active_turn(AgentType.CODEX, screen)

    def test_draft_in_the_composer_still_counts(self) -> None:
        screen = "\n".join(
            [
                "  • Working (12s • esc to interrupt)",
                "  \u203a follow up on this later",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        assert screen_shows_active_turn(AgentType.CODEX, screen)

    def test_idle_composer_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  • Explored",
                "  └ Read index.tsx",
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ? for shortcuts",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)

    def test_transcript_echo_without_composer_is_ignored(self) -> None:
        screen = "\n".join(
            [
                '  • print("esc to interrupt)")',
                "  • Explored",
                "  └ Read index.tsx",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)

    def test_hint_above_the_footer_window_is_ignored(self) -> None:
        older = [f"  transcript line {index}" for index in range(15)]
        screen = "\n".join(
            [
                "  • Working (4m 34s • esc to interrupt)",
                "    └ Tip: Press ⌃r to search previously entered prompts.",
                *older,
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)

    def test_other_agents_ignore_the_codex_hint(self) -> None:
        screen = "\n".join(
            [
                "  • Working (4m 34s • esc to interrupt)",
                "  \u203a Ask Codex to do anything",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)


class TestKimiScreenShowsActiveTurn:
    def test_working_status_line_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  001 [⣿⣦⣀⣀⣀⣀⣀⣀] Let me write the first reque…",
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "   ──────────────────────────────────────────────",
                "    Todo",
                "    ● 写 43 条回复 —— 6 …",
                "    … +1 more (1 done) · ctrl+t to expand",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed swarm  K2.8 Preview thinking:…",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_orchestrating_and_rate_limited_variants(self) -> None:
        for label in (
            "Orchestrating",
            "Prompting",
            "Queued",
            "Rate limited",
            "Thinking",
        ):
            screen = "\n".join(
                [
                    f"  🌖 {label}…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    "  ╭────────────────────────────────────────────╮",
                    "  │ >                                          │",
                    "  ╰────────────────────────────────────────────╯",
                ]
            )
            assert screen_shows_active_turn(AgentType.KIMI, screen), label

    def test_plan_mode_thinking_status_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  ✨ list the files in this directory",
                "  ⠋ thinking…",
                "    The user asked a simple question…",
                "   ⠋ Thinking… · Tip: ask Kimi to schedule tasks",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  plan  K2.8 Preview thinking: max",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_lowercase_thinking_transcript_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  ⠋ thinking…",
                "    The user asked a simple question…",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  plan  K2.8 Preview thinking: max",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_label_free_spinner_tip_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  ● Running a command · $ curl -s -X POST …",
                '  ·· {"ok":true,"data":{}}',
                "  🌑 · Tip: @: mention files",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed K2.8 Preview thinking: max",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_ascii_ellipsis_variant(self) -> None:
        screen = "\n".join(
            [
                "  🌗 Working...  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_idle_composer_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  Report done.",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed K3 thinking: max",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_terminal_labels_are_not_running(self) -> None:
        for label in ("Completed.", "Failed.", "Aborted.", "Cancelled."):
            screen = "\n".join(
                [
                    f"  🌕 {label}",
                    "  ╭────────────────────────────────────────────╮",
                    "  │ >                                          │",
                    "  ╰────────────────────────────────────────────╯",
                ]
            )
            assert not screen_shows_active_turn(AgentType.KIMI, screen), label

    def test_transcript_echo_without_composer_is_ignored(self) -> None:
        screen = "\n".join(
            [
                '  • print("Working…")',
                "  transcript line",
                "  Ask When Needed K3 thinking: max",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_label_above_the_footer_window_is_ignored(self) -> None:
        older = [f"  transcript line {index}" for index in range(30)]
        screen = "\n".join(
            [
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                *older,
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_other_agents_ignore_the_kimi_label(self) -> None:
        screen = "\n".join(
            [
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)
