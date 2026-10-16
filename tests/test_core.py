import tempfile
import unittest
from pathlib import Path
from iqtree_core import AnalysisConfig, build_command
from unittest.mock import patch
from tree_viewer import Parser, tree_layout, segments, export_svg

class ArgumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = Path(self.temp.name)
        self.alignment = self.p / 'Korean file name.fasta'
        self.alignment.write_text('>a\nACGT\n>b\nACGA\n', encoding='utf-8')
        self.base = AnalysisConfig(alignment=str(self.alignment), output_dir=str(self.p / 'result files'), prefix='COI_1249')

    def tearDown(self): self.temp.cleanup()

    def test_default_flags(self):
        arr = self.base.args()
        self.assertEqual(arr[arr.index('-m') + 1], 'MFP')
        self.assertEqual(arr[arr.index('-B') + 1], '1000')
        self.assertEqual(arr[arr.index('--alrt') + 1], '1000')
        self.assertEqual(arr[arr.index('-T') + 1], 'AUTO')
        self.assertIn('Korean file name.fasta', arr[1])
        self.assertIn('COI_1249', arr[-1])

    def test_bnni_redo_and_extras(self):
        self.base.bnni = True
        self.base.redo = True
        self.base.extra = '--safe --keep-ident'
        self.assertEqual(self.base.args().count('--bnni'), 1)
        self.assertIn('--redo', self.base.args())
        self.assertEqual(self.base.args()[-2:], ['--safe', '--keep-ident'])

    def test_mf_no_support(self):
        self.base.model_mode = 'MF'
        with self.assertRaises(ValueError): self.base.validate()
        self.base.support_mode = 'None'
        self.base.alrt = False
        self.assertNotIn('-B', self.base.args())
        self.assertNotIn('--alrt', self.base.args())

    def test_partition_modes(self):
        part = self.p / 'partition.nex'
        part.write_text('DNA, a = 1-3\nDNA, b = 4-6\n')
        self.base.partitions = str(part)
        for scheme, flag in [('proportional', '-p'), ('equal', '-q'), ('unlinked', '-Q')]:
            self.base.partition_scheme = scheme
            self.assertIn(flag, self.base.args())
        self.base.merge_partitions = True
        self.assertIn('MFP+MERGE', self.base.args())

    def test_codons(self):
        self.base.seq_type = 'CODON5'
        self.assertEqual(self.base.args()[self.base.args().index('-st')+1], 'CODON5')

    def test_invalid_support(self):
        self.base.bootstrap_reps = 999
        with self.assertRaises(ValueError): self.base.validate()
        self.base.bootstrap_reps = 1000
        self.base.alrt_reps = 1
        with self.assertRaises(ValueError): self.base.validate()

    def test_windows_command(self):
        cmd, text = build_command(self.base, 'Windows', 'C:\\Program Files\\iqtree2.exe')
        self.assertEqual(cmd[0], 'C:\\Program Files\\iqtree2.exe')
        self.assertTrue(text)

    def test_wsl_command_keeps_paths_as_single_arguments(self):
        with patch('iqtree_core.to_wsl_path', side_effect=lambda value, distro: '/mnt/d/' + Path(value).name):
            cmd, shown = build_command(self.base, 'WSL', 'iqtree2', 'Ubuntu-22.04')
        self.assertEqual(cmd[:4], ['wsl.exe', '-d', 'Ubuntu-22.04', '-e'])
        self.assertEqual(cmd[4:6], ['bash', '-lc'])
        self.assertIn('exec "$@"', cmd[6])
        self.assertEqual(cmd[cmd.index('-s') + 1], '/mnt/d/Korean file name.fasta')
        self.assertIn('/mnt/d/COI_1249', cmd)

    def test_no_shell_injection(self):
        self.base.extra = '--safe; touch attack.txt'
        args = self.base.args()
        self.assertIn('touch', args)
        self.assertNotIn('/bin/sh', args)

class TreeTests(unittest.TestCase):
    def test_tree(self):
        root = Parser("((A:0.1,B:0.2)97/95:0.3,('C species':0.2,D:0.4)80:0.6);").parse()
        width, height, leaves = tree_layout(root)
        self.assertEqual(leaves, 4)
        self.assertGreater(width, 800)
        self.assertTrue(any(s[0] == 'support' and s[3] == '97/95' for s in segments(root)))
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 'a.svg'
            export_svg(root, f)
            self.assertIn('C species', f.read_text(encoding='utf-8'))

    def test_comments_and_quotes(self):
        root = Parser("(('O''Connor':0.1)[&x=y],N:0.2);").parse()
        self.assertEqual(root.children[0].children[0].name, "O'Connor")

    def test_malformed(self):
        for value in ('(A,B', '(A:cat,B);', '(A,B));junk'):
            with self.assertRaises(ValueError): Parser(value).parse()

if __name__ == '__main__': unittest.main()
