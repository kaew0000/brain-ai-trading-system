"""tests/test_bundle_manager_cli.py — Bundle Manager

Covers tools/bundle_manager.py's argparse wiring and command dispatch
(cmd_import/cmd_sync/cmd_history), and tools/ui.py's presentation
functions (that they run without raising and mirror to the logger).
Everything below main.py's parse step is mocked — no real bundles, no
real git, no real terminal interaction (confirm() is always patched).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import bundle_manager, ui
from tools.github_actions import ImportResult
from tools.history import BundleRecord

pytestmark = pytest.mark.unit


class TestArgumentParsing:

    def test_import_requires_no_extra_args(self):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["import"])
        assert args.command == "import"
        assert args.repo == "."
        assert args.yes is False
        assert args.no_push is False

    def test_import_flags_parsed(self):
        parser = bundle_manager.build_parser()
        args = parser.parse_args([
            "import", "--repo", "/tmp/x", "--yes", "--no-push", "--force",
            "--base-branch", "develop", "--remote", "upstream",
        ])
        assert args.repo == "/tmp/x"
        assert args.yes is True
        assert args.no_push is True
        assert args.force is True
        assert args.base_branch == "develop"
        assert args.remote == "upstream"

    def test_sync_subcommand_parses(self):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["sync", "--no-prune"])
        assert args.command == "sync"
        assert args.no_prune is True

    def test_history_subcommand_default_limit(self):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["history"])
        assert args.limit == 20

    def test_no_subcommand_is_an_error(self):
        parser = bundle_manager.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestResolveDirs:

    def test_falls_back_to_settings_when_no_cli_override(self, tmp_path):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["import"])
        dirs = bundle_manager._resolve_dirs(tmp_path, args)
        assert dirs["incoming"] == tmp_path / "update" / "incoming"

    def test_cli_override_takes_precedence(self, tmp_path):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["import", "--incoming", "custom/in"])
        dirs = bundle_manager._resolve_dirs(tmp_path, args)
        assert dirs["incoming"] == tmp_path / "custom" / "in"

    def test_absolute_override_is_used_as_is(self, tmp_path):
        parser = bundle_manager.build_parser()
        abs_path = str(tmp_path / "elsewhere")
        args = parser.parse_args(["import", "--incoming", abs_path])
        dirs = bundle_manager._resolve_dirs(tmp_path, args)
        assert dirs["incoming"] == Path(abs_path)


class TestCmdImport:

    def _args(self, tmp_path, **overrides):
        parser = bundle_manager.build_parser()
        argv = ["import", "--repo", str(tmp_path), "--yes"]
        args = parser.parse_args(argv)
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def test_no_bundles_found_returns_zero(self, tmp_path):
        args = self._args(tmp_path)
        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles", return_value=[]):
            rc = bundle_manager.cmd_import(args)
        assert rc == 0

    def test_all_duplicates_or_invalid_skips_confirmation_and_returns_zero(self, tmp_path):
        args = self._args(tmp_path, yes=False)   # confirm() must NOT be reached
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")

        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "failed", "bad bundle")
        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   return_value=preview_result), \
             patch("tools.bundle_manager.ui.confirm") as confirm:
            rc = bundle_manager.cmd_import(args)

        confirm.assert_not_called()
        assert rc == 0

    def test_confirmation_declined_aborts_without_real_pass(self, tmp_path):
        args = self._args(tmp_path, yes=False)
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")
        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "dry_run", None)

        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   return_value=preview_result) as import_bundle, \
             patch("tools.bundle_manager.git_utils.get_dirty_files", return_value=[]), \
             patch("tools.bundle_manager.ui.confirm", return_value=False):
            rc = bundle_manager.cmd_import(args)

        assert rc == 1
        import_bundle.assert_called_once()   # only the dry-run preview call, no real pass

    def test_yes_flag_skips_confirmation_prompt(self, tmp_path):
        args = self._args(tmp_path, yes=True)
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")
        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "dry_run", None)
        real_result = ImportResult(bundle_path, "feature/x", "sha1", "applied", None)

        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   side_effect=[preview_result, real_result]), \
             patch("tools.bundle_manager.git_utils.get_dirty_files", return_value=[]), \
             patch("tools.bundle_manager.git_utils.get_current_branch", return_value="main"), \
             patch("tools.bundle_manager.git_utils.commit_paths") as commit_paths, \
             patch("tools.bundle_manager.ui.confirm") as confirm, \
             patch("tools.bundle_manager.BundleHistory") as history_cls:
            history_cls.return_value.save = MagicMock()
            rc = bundle_manager.cmd_import(args)

        confirm.assert_not_called()
        assert rc == 0
        commit_paths.assert_called_once()   # W14-2B: local commit follows history.save()

    def test_failed_imports_produce_nonzero_exit_code(self, tmp_path):
        args = self._args(tmp_path, yes=True)
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")
        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "dry_run", None)
        real_result = ImportResult(bundle_path, "feature/x", "sha1", "failed", "push rejected")

        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   side_effect=[preview_result, real_result]), \
             patch("tools.bundle_manager.git_utils.get_dirty_files", return_value=[]), \
             patch("tools.bundle_manager.git_utils.get_current_branch", return_value="main"), \
             patch("tools.bundle_manager.git_utils.commit_paths") as commit_paths, \
             patch("tools.bundle_manager.BundleHistory") as history_cls:
            history_cls.return_value.save = MagicMock()
            rc = bundle_manager.cmd_import(args)

        assert rc == 1
        # W14-2B: the failed-only real pass still saves (audit trail is
        # preserved, see history.py) and still gets locally committed —
        # this is the exact case that used to leave a dirty tree behind
        # and block the next invocation's preflight.
        commit_paths.assert_called_once()

    def test_dirty_tracked_files_abort_before_confirmation(self, tmp_path):
        args = self._args(tmp_path, yes=False)   # confirm() must NOT be reached
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")
        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "dry_run", None)

        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   return_value=preview_result) as import_bundle, \
             patch("tools.bundle_manager.git_utils.get_dirty_files",
                   return_value=["bundle_history.json"]), \
             patch("tools.bundle_manager.ui.confirm") as confirm, \
             patch("tools.bundle_manager.ui.error") as error:
            rc = bundle_manager.cmd_import(args)

        assert rc == 2
        confirm.assert_not_called()
        import_bundle.assert_called_once()   # only the dry-run preview call, no real pass
        assert "bundle_history.json" in error.call_args[0][0]

    def test_corrupt_history_file_returns_error_code_without_crashing(self, tmp_path):
        args = self._args(tmp_path, yes=True)
        with patch("tools.bundle_manager.BundleHistory", side_effect=RuntimeError("corrupt")):
            rc = bundle_manager.cmd_import(args)
        assert rc == 2


class TestCommitHistoryFileWiring:
    """W14-2B — cmd_import()'s call to _commit_history_file() after
    history.save(), and the BUNDLE_AUTO_COMMIT_HISTORY escape hatch.
    tools.git_utils.commit_paths() itself is covered by
    tests/test_bundle_manager_git_utils.py::TestCommitPaths; this class
    only covers bundle_manager.py's wiring around it.
    """

    def _args(self, tmp_path, **overrides):
        parser = bundle_manager.build_parser()
        argv = ["import", "--repo", str(tmp_path), "--yes"]
        args = parser.parse_args(argv)
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def _run_real_pass(self, tmp_path, args, real_status="applied", real_reason=None):
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")
        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "dry_run", None)
        real_result = ImportResult(bundle_path, "feature/x", "sha1", real_status, real_reason)
        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   side_effect=[preview_result, real_result]), \
             patch("tools.bundle_manager.git_utils.get_dirty_files", return_value=[]), \
             patch("tools.bundle_manager.git_utils.get_current_branch", return_value="main"), \
             patch("tools.bundle_manager.BundleHistory") as history_cls, \
             patch("tools.bundle_manager.git_utils.commit_paths") as commit_paths:
            history_cls.return_value.save = MagicMock()
            rc = bundle_manager.cmd_import(args)
        return rc, commit_paths

    def test_commit_history_file_calls_commit_paths_with_resolved_history_path(self, tmp_path):
        history_path = tmp_path / "bundle_history.json"
        history_path.write_text("{}")
        with patch("tools.bundle_manager.git_utils.commit_paths") as commit_paths:
            bundle_manager._commit_history_file(history_path, tmp_path)
        commit_paths.assert_called_once()
        called_paths, called_message, called_cwd = commit_paths.call_args[0]
        assert called_paths == [history_path.resolve().as_posix()]
        assert called_message == "sync bundle history"
        assert called_cwd == tmp_path

    def test_commit_failure_is_caught_and_warned_not_raised(self, tmp_path):
        history_path = tmp_path / "bundle_history.json"
        history_path.write_text("{}")
        from tools import git_utils
        with patch("tools.bundle_manager.git_utils.commit_paths",
                    side_effect=git_utils.GitCommandError(
                        ["commit"], 1, "", "fatal: unable to auto-detect email address")), \
             patch("tools.bundle_manager.ui.warn") as warn:
            bundle_manager._commit_history_file(history_path, tmp_path)   # must not raise
        warn.assert_called_once()
        assert "bundle_history.json" in warn.call_args[0][0]

    def test_real_pass_success_triggers_auto_commit(self, tmp_path):
        args = self._args(tmp_path)
        rc, commit_paths = self._run_real_pass(tmp_path, args, "applied", None)
        assert rc == 0
        commit_paths.assert_called_once()

    def test_real_pass_failure_still_triggers_auto_commit(self, tmp_path):
        """The exact scenario W14-2B fixes: a failed attempt's
        history.save() must not linger uncommitted and block the next
        invocation's preflight."""
        args = self._args(tmp_path)
        rc, commit_paths = self._run_real_pass(tmp_path, args, "failed", "push rejected")
        assert rc == 1
        commit_paths.assert_called_once()

    def test_auto_commit_disabled_via_setting_skips_commit_paths(self, tmp_path):
        args = self._args(tmp_path)
        bundle_path = tmp_path / "x.bundle"
        bundle_path.write_bytes(b"x")
        preview_result = ImportResult(bundle_path, "feature/x", "sha1", "dry_run", None)
        real_result = ImportResult(bundle_path, "feature/x", "sha1", "applied", None)
        with patch("tools.bundle_manager.bundle_utils.find_incoming_bundles",
                    return_value=[bundle_path]), \
             patch("tools.bundle_manager.github_actions.import_bundle",
                   side_effect=[preview_result, real_result]), \
             patch("tools.bundle_manager.git_utils.get_dirty_files", return_value=[]), \
             patch("tools.bundle_manager.BundleHistory") as history_cls, \
             patch("tools.bundle_manager.git_utils.commit_paths") as commit_paths, \
             patch("tools.bundle_manager.settings.BUNDLE_AUTO_COMMIT_HISTORY", False):
            history_cls.return_value.save = MagicMock()
            rc = bundle_manager.cmd_import(args)
        assert rc == 0
        commit_paths.assert_not_called()

    def test_commit_paths_no_op_result_logs_nothing_extra(self, tmp_path):
        """commit_paths() returning None (nothing staged) is a valid,
        silent no-op — not a failure — and must not warn."""
        history_path = tmp_path / "bundle_history.json"
        history_path.write_text("{}")
        with patch("tools.bundle_manager.git_utils.commit_paths", return_value=None), \
             patch("tools.bundle_manager.ui.warn") as warn:
            bundle_manager._commit_history_file(history_path, tmp_path)
        warn.assert_not_called()


class TestReturnToBaseBranch:
    """W14-2B — _return_to_base_branch(): bundle_history.json's tracking
    commit must land on base_branch, not whichever feature branch the
    last bundle in the batch happened to leave checked out (see
    _commit_history_file()'s call site in cmd_import for why: a commit
    left on a feature branch that later gets deleted would make that
    history record unreachable from base_branch again)."""

    def test_checks_out_base_branch_when_on_a_different_branch(self, tmp_path):
        with patch("tools.bundle_manager.git_utils.get_current_branch",
                    return_value="feature/x") as get_branch, \
             patch("tools.bundle_manager.git_utils.checkout_branch") as checkout:
            bundle_manager._return_to_base_branch("main", tmp_path, 60)
        get_branch.assert_called_once_with(tmp_path)
        checkout.assert_called_once_with("main", tmp_path, timeout=60)

    def test_no_op_when_already_on_base_branch(self, tmp_path):
        with patch("tools.bundle_manager.git_utils.get_current_branch",
                    return_value="main"), \
             patch("tools.bundle_manager.git_utils.checkout_branch") as checkout:
            bundle_manager._return_to_base_branch("main", tmp_path, 60)
        checkout.assert_not_called()

    def test_checkout_failure_is_caught_and_warned_not_raised(self, tmp_path):
        from tools import git_utils
        with patch("tools.bundle_manager.git_utils.get_current_branch",
                    return_value="feature/x"), \
             patch("tools.bundle_manager.git_utils.checkout_branch",
                   side_effect=git_utils.GitCommandError(
                       ["checkout", "main"], 1, "", "error: your local changes...")), \
             patch("tools.bundle_manager.ui.warn") as warn:
            bundle_manager._return_to_base_branch("main", tmp_path, 60)   # must not raise
        warn.assert_called_once()
        assert "main" in warn.call_args[0][0]


class TestCmdSync:

    def test_success_returns_zero(self, tmp_path):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["sync", "--repo", str(tmp_path)])
        fake_result = MagicMock(fast_forwarded=True, before_sha="a" * 40, after_sha="b" * 40,
                                 newly_merged_shas=[])
        with patch("tools.bundle_manager.BundleHistory"), \
             patch("tools.bundle_manager.sync_module.sync_main", return_value=fake_result):
            rc = bundle_manager.cmd_sync(args)
        assert rc == 0

    def test_exception_reports_error_and_returns_nonzero(self, tmp_path):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["sync", "--repo", str(tmp_path)])
        with patch("tools.bundle_manager.BundleHistory"), \
             patch("tools.bundle_manager.sync_module.sync_main", side_effect=RuntimeError("boom")):
            rc = bundle_manager.cmd_sync(args)
        assert rc == 2


class TestCmdHistory:

    def test_empty_history_returns_zero(self, tmp_path):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["history", "--repo", str(tmp_path)])
        with patch("tools.bundle_manager.BundleHistory") as history_cls:
            history_cls.return_value.all_records.return_value = []
            rc = bundle_manager.cmd_history(args)
        assert rc == 0

    def test_populated_history_returns_zero(self, tmp_path):
        parser = bundle_manager.build_parser()
        args = parser.parse_args(["history", "--repo", str(tmp_path)])
        record = BundleRecord(sha="s", branch="b", bundle_filename="f",
                               status="applied", imported_at="2026-01-01T00:00:00Z")
        with patch("tools.bundle_manager.BundleHistory") as history_cls:
            history_cls.return_value.all_records.return_value = [record]
            rc = bundle_manager.cmd_history(args)
        assert rc == 0


class TestMainDispatch:

    def test_main_calls_the_right_subcommand_function(self, tmp_path):
        with patch("tools.bundle_manager.cmd_import", return_value=0) as cmd_import:
            rc = bundle_manager.main(["import", "--repo", str(tmp_path), "--yes"])
        cmd_import.assert_called_once()
        assert rc == 0

    def test_keyboard_interrupt_returns_130(self):
        with patch("tools.bundle_manager.cmd_import", side_effect=KeyboardInterrupt):
            rc = bundle_manager.main(["import"])
        assert rc == 130


class TestUi:

    def test_status_functions_do_not_raise(self):
        ui.banner("test")
        ui.info("test")
        ui.success("test")
        ui.warn("test")
        ui.error("test")

    def test_results_table_handles_empty_list(self):
        ui.results_table([])   # must not raise

    def test_results_table_renders_mixed_statuses(self):
        results = [
            ImportResult(Path("a.bundle"), "feature/a", "sha1", "applied", None),
            ImportResult(Path("b.bundle"), None, None, "failed", "verify failed"),
        ]
        ui.results_table(results)   # must not raise

    def test_history_table_handles_empty_and_limit(self):
        ui.history_table([], limit=5)   # must not raise
        records = [
            BundleRecord(sha=f"s{i}", branch="b", bundle_filename="f",
                         status="applied", imported_at=f"2026-01-0{i}T00:00:00Z")
            for i in range(1, 4)
        ]
        ui.history_table(records, limit=2)   # must not raise even when truncating
