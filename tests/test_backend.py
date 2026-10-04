"""Run with python -m unittest test_backend (or pytest)."""
import unittest
from unittest.mock import patch
import numpy as np
from pcb_emu.backend import ArrayBackend, BackendUnavailableError, availability, benchmark


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.A = np.array([[0., 2., 1.], [4., 5., 6.], [7., 8., 10.]])
        self.B = np.arange(15., dtype=float).reshape(5, 3)

    def test_numpy_multiple_rhs_and_reuse(self):
        backend = ArrayBackend()
        factor = backend.factor(self.A)
        for B in (self.B, self.B * 2, self.B[:1], self.B[:, ::-1]):
            result = factor.solve(B)
            np.testing.assert_allclose(result @ self.A.T, B, atol=1e-12)
            self.assertEqual(result.shape, B.shape)
            self.assertEqual(result.dtype, np.float64)
        np.testing.assert_allclose(backend.solve(self.A, self.B), factor.solve(self.B))

    def test_no_input_mutation_and_factor_snapshot(self):
        A, B = self.A.copy(), self.B.copy()
        factor = ArrayBackend().factor(A)
        factor.solve(B)
        np.testing.assert_array_equal(A, self.A)
        np.testing.assert_array_equal(B, self.B)
        A[:] = 0
        np.testing.assert_allclose(factor.solve(B) @ self.A.T, B, atol=1e-12)

    def test_empty_batch(self):
        self.assertEqual(ArrayBackend().solve(self.A, np.empty((0, 3))).shape, (0, 3))

    def test_invalid_inputs(self):
        backend = ArrayBackend()
        for A in (np.ones((2, 3)), np.empty((0, 0)), [1, 2], [[np.nan]], [[1j]]):
            with self.assertRaises(ValueError):
                backend.factor(A)
        for B in (np.ones(3), np.ones((3, 4)), np.full((2, 3), np.inf)):
            with self.assertRaises(ValueError):
                backend.solve(self.A, B)
        with self.assertRaises(np.linalg.LinAlgError):
            backend.factor(np.ones((2, 2)))

    def test_cuda_missing_is_explicit_error(self):
        with self.assertRaises(BackendUnavailableError):
            ArrayBackend('numpy', 'cuda')
        with patch('importlib.import_module', side_effect=ImportError('deliberately missing')):
            for name in ('torch', 'cupy'):
                with self.assertRaises(BackendUnavailableError):
                    ArrayBackend(name, 'cuda')

    def test_auto_cpu(self):
        backend = ArrayBackend('auto', 'cpu')
        self.assertEqual(backend.name, 'numpy')
        self.assertEqual(backend.device, 'cpu')

    def test_metadata_does_not_import_optional_packages(self):
        with patch('importlib.import_module', side_effect=AssertionError('must not import')):
            self.assertIn('torch', availability())

    def test_optional_torch_cpu(self):
        if not availability()['torch']['installed']:
            self.skipTest('torch not installed')
        try:
            backend = ArrayBackend('torch', 'cpu')
        except BackendUnavailableError as exc:
            self.skipTest(str(exc))
        np.testing.assert_allclose(backend.solve(self.A, self.B) @ self.A.T, self.B, atol=1e-12)

    def test_auto_fallback_and_explicit_device(self):
        import importlib
        original = importlib.import_module
        def missing_optional(name):
            if name in ('torch', 'cupy'):
                raise ImportError('deliberately missing')
            return original(name)
        with patch('importlib.import_module', side_effect=missing_optional):
            backend = ArrayBackend('auto')
            self.assertEqual(backend.name, 'numpy')
            self.assertEqual(set(backend.auto_failures), {'torch', 'cupy'})
            with self.assertRaises(BackendUnavailableError):
                ArrayBackend('auto', 'cuda')

    def test_optional_cuda(self):
        tested = []
        for name in ('torch', 'cupy'):
            try:
                backend = ArrayBackend(name, 'cuda')
            except BackendUnavailableError:
                continue
            np.testing.assert_allclose(backend.solve(self.A, self.B) @ self.A.T, self.B, atol=1e-12)
            tested.append(name)
        if not tested:
            self.skipTest('No usable optional CUDA backend')

    def test_small_benchmark(self):
        report = benchmark(8, 12, 1, 0, ('numpy',))
        self.assertTrue(report['results'][0]['accuracy_pass'])
        self.assertIn('factor_and_solve', report['results'][0]['timings'])


if __name__ == '__main__':
    unittest.main()
