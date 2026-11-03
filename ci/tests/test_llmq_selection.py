"""Exercise CI selection against real Git history, including renamed files."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('selector', Path(__file__).parents[1] / 'select-llmq-tests.py')
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


class LlmqSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git(['init', '-q'])
        self.git(['config', 'user.email', 'ci@example.invalid'])
        self.git(['config', 'user.name', 'CI test'])
        self.base = self.commit('src/validation.cpp')

    def git(self, args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE)

    def commit(self, path):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('fixture\n')
        self.git(['add', '-A'])
        self.git(['commit', '-qm', 'fixture'])
        return self.git(['rev-parse', 'HEAD']).decode().strip()

    def push(self, head):
        return SELECTOR.select('push', {'before': self.base, 'after': head}, self.git)[0]

    def test_ui_and_ai_changes_skip(self):
        self.commit('src/qt/yerbasaipage.cpp')
        self.assertFalse(self.push(self.commit('contrib/yerbas-ai/owner-agent/wallet_agent.py')))

    def test_ai_test_orchestration_and_manifest_skip(self):
        self.commit('ci/test-ai.py')
        self.commit('ci/check-ai-source.py')
        head = self.commit('contrib/yerbas-ai/SOURCE.json')
        self.assertFalse(self.push(head))
        event = {'pull_request': {'base': {'sha': self.base}, 'head': {'sha': head}}}
        self.assertFalse(SELECTOR.select('pull_request', event, self.git)[0])

    def test_ai_scripts_do_not_hide_consensus_changes(self):
        self.commit('ci/test-ai.py')
        self.assertTrue(self.push(self.commit('src/llmq/quorums.cpp')))

    def test_ai_exemptions_are_exact(self):
        for path in ('ci/test-ai.py.bak', 'ci/check-ai-source.py/new.py',
                     'ci/test-consensus.py', 'ci/tests/test_llmq_selection.py'):
            with self.subTest(path=path):
                self.assertTrue(SELECTOR.relevant(path))

    def test_core_in_multi_commit_push_runs(self):
        self.commit('src/llmq/quorums.cpp')
        self.assertTrue(self.push(self.commit('doc/readme.md')))

    def test_rename_core_into_ui_runs(self):
        (self.root / 'src/qt').mkdir()
        self.git(['mv', 'src/validation.cpp', 'src/qt/moved.cpp'])
        self.assertTrue(self.push(self.commit('doc/readme.md')))

    def test_pr_uses_merge_base(self):
        head = self.commit('src/qt/page.cpp')
        self.git(['checkout', '-q', self.base])
        base_tip = self.commit('src/llmq/base-only.cpp')
        event = {'pull_request': {'base': {'sha': base_tip}, 'head': {'sha': head}}}
        self.assertFalse(SELECTOR.select('pull_request', event, self.git)[0])

    def test_tags_manual_and_missing_history_run(self):
        for event_name, event in [('workflow_dispatch', {}), ('push', {'ref': 'refs/tags/v5'}),
                                  ('push', {'before': '0' * 40, 'after': self.base}),
                                  ('push', {'before': 'f' * 40, 'after': self.base}), ('unknown', {})]:
            with self.subTest(event=event):
                self.assertTrue(SELECTOR.select(event_name, event, self.git)[0])

    def test_build_tests_and_unknown_paths_run(self):
        for path in ('src/qt/Makefile.am', 'configure.ac', 'depends/packages/boost.mk',
                     '.github/workflows/build.yaml', 'ci/select-llmq-tests.py',
                     'test/functional/feature_llmq_manual_recovery.py', 'contrib/llmq/tool.py',
                     'src/wallet/wallet.cpp', 'new-directory/new-file'):
            with self.subTest(path=path):
                self.assertTrue(SELECTOR.relevant(path))


if __name__ == '__main__':
    unittest.main()
