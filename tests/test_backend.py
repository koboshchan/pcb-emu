import unittest
import numpy as np
from pcb_emu.backend import ArrayBackend


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.A=np.array([[0.,2.,1.],[4.,5.,6.],[7.,8.,10.]])
        self.B=np.arange(15.,dtype=float).reshape(5,3)

    def test_multiple_rhs_and_reuse(self):
        backend=ArrayBackend();factor=backend.factor(self.A)
        for B in (self.B,self.B*2,self.B[:1],self.B[:,::-1]):
            result=factor.solve(B)
            np.testing.assert_allclose(result@self.A.T,B,atol=1e-12)
            self.assertEqual(result.shape,B.shape)
            self.assertEqual(result.dtype,np.float64)
        np.testing.assert_allclose(backend.solve(self.A,self.B),factor.solve(self.B))

    def test_no_input_mutation_and_factor_snapshot(self):
        A,B=self.A.copy(),self.B.copy();factor=ArrayBackend().factor(A);factor.solve(B)
        np.testing.assert_array_equal(A,self.A);np.testing.assert_array_equal(B,self.B)
        A[:]=0
        np.testing.assert_allclose(factor.solve(B)@self.A.T,B,atol=1e-12)

    def test_empty_rhs(self):
        self.assertEqual(ArrayBackend().solve(self.A,np.empty((0,3))).shape,(0,3))

    def test_invalid_inputs(self):
        backend=ArrayBackend()
        for A in (np.ones((2,3)),np.empty((0,0)),[1,2],[[np.nan]],[[1j]]):
            with self.assertRaises(ValueError):backend.factor(A)
        for B in (np.ones(3),np.ones((3,4)),np.full((2,3),np.inf)):
            with self.assertRaises(ValueError):backend.solve(self.A,B)
        with self.assertRaises(np.linalg.LinAlgError):backend.factor(np.ones((2,2)))

    def test_cpu_only(self):
        self.assertEqual(ArrayBackend('numpy','cpu').device,'cpu')
        for name,device in [('other',None),('numpy','other')]:
            with self.assertRaises(ValueError):ArrayBackend(name,device)
