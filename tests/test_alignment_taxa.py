import tempfile
import unittest
from pathlib import Path
from alignment_taxa import read_alignment_taxa, join_outgroups
from iqtree_core import AnalysisConfig


class AlignmentTaxaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def alignment(self, name, data):
        path = self.folder / name
        path.write_text(data, encoding='utf-8')
        return path

    def test_fasta_uses_ids_and_preserves_order(self):
        p = self.alignment('taxa with spaces.fas', '>A_species description\nACTG\n>B_species something\nAAAA\n>A_species\nACGT\n')
        self.assertEqual(read_alignment_taxa(p), ['A_species', 'B_species'])

    def test_nexus_quoted_taxon_and_comments(self):
        p = self.alignment('dna.nex', "#NEXUS\nBEGIN DATA;\nDIMENSIONS NTAX=3 NCHAR=4;\nFORMAT DATATYPE=DNA;\nMATRIX\n 'A species' ACTG\n [comment]\n 'B species' ACTT\n  C_species ACGT\n;\nEND;\n")
        self.assertEqual(read_alignment_taxa(p), ['A species', 'B species', 'C_species'])

    def test_relaxed_phylip(self):
        p = self.alignment('dna.phy', '3 4\nSample_1   ACTG\nSample_2 ACGT\nSample_3  ACGC\n')
        self.assertEqual(read_alignment_taxa(p), ['Sample_1', 'Sample_2', 'Sample_3'])

    def test_bad_format(self):
        p = self.alignment('not_an_alignment.txt', 'just plain text\n')
        with self.assertRaises(ValueError): read_alignment_taxa(p)

    def test_empty_fasta_header(self):
        p = self.alignment('bad.fa', '>\nACGT\n')
        with self.assertRaises(ValueError): read_alignment_taxa(p)

    def test_join_outgroup_args(self):
        p = self.alignment('a.fa', '>A\nAAAA\n>B\nAAAA\n>C\nAAAA\n')
        outgroup = join_outgroups(['A','C','A'])
        cfg = AnalysisConfig(alignment=str(p), output_dir=str(self.folder), prefix='test', outgroup=outgroup)
        arr = cfg.args()
        self.assertEqual(arr[arr.index('-o')+1], 'A,C')


if __name__ == '__main__':
    unittest.main()
