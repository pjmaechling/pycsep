import unittest
from csep.utils.calc import bin1d_vec

class TestBin1d(unittest.TestCase):

    def test_bin1d_vec(self):
        data = [0.34, 0.35]
        bin_edges = [0.33, 0.34, 0.35, 0.36]
        test = bin1d_vec(data, bin_edges).tolist()
        expected = [1, 2]
        self.assertListEqual(test, expected)

    def test_bin1d_vec2(self):
        data = [0.9999999]
        bin_edges = [0.8, 0.9, 1.0]
        test = bin1d_vec(data, bin_edges)
        expected = [1]
        self.assertListEqual(test.tolist(), expected)

    def test_bin1d_vec_int(self):
        data = [1, 3, 5, 10, 20]
        bin_edges = [0, 10, 20, 30]
        test = bin1d_vec(data, bin_edges)
        expected = [0, 0, 0, 1, 2]
        self.assertListEqual(test.tolist(), expected)
