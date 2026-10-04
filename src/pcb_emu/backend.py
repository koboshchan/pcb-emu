"""Float64 shared-matrix LU solves, with lazy optional CUDA backends.

B and returned X have shape (batch, N); internally RHS columns are used.
No accelerator package is imported until ArrayBackend is constructed.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
from importlib import metadata
import json
import platform
import time
import warnings
import numpy as np


class BackendUnavailableError(RuntimeError):
    """An explicitly requested backend/device cannot be used."""


def availability():
    """Package presence/versions only; does not initialize CUDA."""
    result = {}
    for name in ('numpy', 'scipy', 'torch', 'cupy'):
        installed = importlib.util.find_spec(name) is not None
        version = None
        distributions = ('cupy', 'cupy-cuda12x', 'cupy-cuda13x', 'cupy-cuda11x') if name == 'cupy' else (name,)
        for distribution in distributions:
            try:
                version = metadata.version(distribution)
                break
            except metadata.PackageNotFoundError:
                pass
        result[name] = {'installed': installed, 'version': version}
    return result


def _array(value):
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ValueError('Only real-valued float64 circuits are supported')
    value = np.asarray(raw, dtype=np.float64)
    if not np.isfinite(value).all():
        raise ValueError('Inputs must be finite')
    return value


class ArrayBackend:
    """NumPy/SciPy by default; auto prefers working CUDA, then NumPy.

    Explicit CUDA never silently falls back. Torch accepts cpu or cuda[:index];
    CuPy accepts cuda[:index]. Auto with device='cpu' selects NumPy.
    """
    def __init__(self, name='numpy', device=None):
        if name not in ('numpy', 'torch', 'cupy', 'auto'):
            raise ValueError('Unknown backend: ' + str(name))
        self.auto_failures = {}
        if name == 'auto':
            if device != 'cpu':
                for candidate in ('torch', 'cupy'):
                    try:
                        chosen = ArrayBackend(candidate, device or 'cuda')
                        failures = self.auto_failures.copy()
                        self.__dict__.update(chosen.__dict__)
                        self.auto_failures = failures
                        return
                    except BackendUnavailableError as exc:
                        self.auto_failures[candidate] = str(exc)
                if device is not None:
                    raise BackendUnavailableError('Requested device unavailable: ' + str(self.auto_failures))
            failures = self.auto_failures.copy()
            chosen = ArrayBackend('numpy', 'cpu')
            self.__dict__.update(chosen.__dict__)
            self.auto_failures = failures
            return
        self.name = name
        try:
            if name == 'numpy':
                if device not in (None, 'cpu'):
                    raise BackendUnavailableError('NumPy backend supports CPU only')
                self.device = 'cpu'
                self.lib = importlib.import_module('scipy.linalg')
            elif name == 'torch':
                self.lib = importlib.import_module('torch')
                self.device = str(device or ('cuda' if self.lib.cuda.is_available() else 'cpu'))
                dev = self.lib.device(self.device)
                if dev.type not in ('cpu', 'cuda'):
                    raise BackendUnavailableError('Only CPU and CUDA support this float64 backend')
                if dev.type == 'cuda' and not self.lib.cuda.is_available():
                    raise BackendUnavailableError('Torch CUDA is unavailable')
                self.lib.empty(1, dtype=self.lib.float64, device=dev)
            else:
                self.lib = importlib.import_module('cupy')
                self.linalg = importlib.import_module('cupyx.scipy.linalg')
                self.device = str(device or 'cuda')
                if self.device != 'cuda' and not self.device.startswith('cuda:'):
                    raise BackendUnavailableError('CuPy requires CUDA')
                self.device_index = int(self.device.split(':')[1]) if ':' in self.device else 0
                with self.lib.cuda.Device(self.device_index):
                    self.lib.empty(1, dtype=self.lib.float64)
                if not all(hasattr(self.linalg, method) for method in ('lu_factor', 'lu_solve')):
                    raise BackendUnavailableError('CuPy version lacks LU factor/solve')
        except BackendUnavailableError:
            raise
        except Exception as exc:
            raise BackendUnavailableError(f'{name} on {device or "default"} unavailable: {exc}') from exc

    def metadata(self):
        info = {'backend': self.name, 'device': self.device, 'dtype': 'float64', 'packages': availability()}
        if self.name == 'torch' and self.device.startswith('cuda'):
            info['gpu'] = self.lib.cuda.get_device_name(self.lib.device(self.device))
        elif self.name == 'cupy':
            props = self.lib.cuda.runtime.getDeviceProperties(self.device_index)
            name = props['name']
            info['gpu'] = name.decode() if isinstance(name, bytes) else name
        return info

    def synchronize(self):
        if self.name == 'torch' and self.device.startswith('cuda'):
            self.lib.cuda.synchronize(self.device)
        elif self.name == 'cupy':
            with self.lib.cuda.Device(self.device_index):
                self.lib.cuda.get_current_stream().synchronize()

    def factor(self, A):
        return _Factor(self, A)

    def solve(self, A, B):
        return self.factor(A).solve(B)


class _Factor:
    def __init__(self, backend, A):
        self.backend = backend
        A = _array(A)
        if A.ndim != 2 or A.shape[0] != A.shape[1] or A.shape[0] == 0:
            raise ValueError('A must be a nonempty square (N,N) matrix')
        self.n = A.shape[0]
        if backend.name == 'numpy':
            with warnings.catch_warnings():
                warnings.simplefilter('error', backend.lib.LinAlgWarning)
                try:
                    self.lu = backend.lib.lu_factor(A.copy())
                except backend.lib.LinAlgWarning as exc:
                    raise np.linalg.LinAlgError('Singular matrix') from exc
        elif backend.name == 'torch':
            t = backend.lib
            with t.no_grad():
                self.lu = t.linalg.lu_factor(t.tensor(A, dtype=t.float64, device=backend.device))
        else:
            c = backend.lib
            with c.cuda.Device(backend.device_index):
                with c.errstate(linalg='raise'):
                    self.lu = backend.linalg.lu_factor(c.asarray(A, dtype=c.float64))

    def solve(self, B):
        B = _array(B)
        if B.ndim != 2 or B.shape[1] != self.n:
            raise ValueError(f'B must have shape (batch,{self.n})')
        if B.shape[0] == 0:
            return np.empty(B.shape, dtype=np.float64)
        backend = self.backend
        if backend.name == 'numpy':
            X = backend.lib.lu_solve(self.lu, B.T).T
        elif backend.name == 'torch':
            t = backend.lib
            with t.no_grad():
                rhs = t.tensor(B.T.copy(), dtype=t.float64, device=backend.device)
                X = t.linalg.lu_solve(*self.lu, rhs).T.cpu().numpy()
        else:
            c = backend.lib
            with c.cuda.Device(backend.device_index):
                with c.errstate(linalg='raise'):
                    X = c.asnumpy(backend.linalg.lu_solve(self.lu, c.asarray(B.T))).T
        if not np.isfinite(X).all():
            raise np.linalg.LinAlgError('Solve produced non-finite results')
        return np.asarray(X, dtype=np.float64)


def benchmark(n=400, batch=1000, repeats=5, warmup=2, backends=('numpy', 'torch', 'cupy')):
    """Synthetic diagonally dominant shared matrix, not a circuit/MNIST claim.

    Timings include transfers, finite checks and NumPy output. Factor-only,
    cached-factor solve and factor+solve are separately measured.
    """
    if min(n, batch, repeats) < 1 or warmup < 0:
        raise ValueError('n, batch, repeats must be positive; warmup nonnegative')
    rng = np.random.default_rng(42)
    A = rng.normal(size=(n, n))
    A[np.diag_indices(n)] += np.abs(A).sum(axis=1) + 1
    B = rng.normal(size=(batch, n))
    reference = ArrayBackend().solve(A, B)
    report = {'synthetic': True, 'n': n, 'batch': batch, 'warmup': warmup,
              'repeats': repeats, 'platform': platform.platform(), 'results': []}
    for name in backends:
        try:
            backend = ArrayBackend(name, 'cuda' if name in ('torch', 'cupy') else None)
        except BackendUnavailableError as exc:
            report['results'].append({'backend': name, 'status': 'unavailable', 'reason': str(exc)})
            continue
        factor = backend.factor(A)
        operations = {'factor': lambda: backend.factor(A), 'cached_solve': lambda: factor.solve(B),
                      'factor_and_solve': lambda: backend.solve(A, B)}
        timings = {}
        for label, operation in operations.items():
            for _ in range(warmup):
                operation()
            samples = []
            for _ in range(repeats):
                backend.synchronize()
                start = time.perf_counter()
                operation()
                backend.synchronize()
                samples.append(time.perf_counter() - start)
            timings[label] = {'seconds': samples, 'median_seconds': float(np.median(samples))}
        X = factor.solve(B)
        residual = np.linalg.norm(X @ A.T - B) / np.linalg.norm(B)
        difference = np.linalg.norm(X - reference) / np.linalg.norm(reference)
        report['results'].append({**backend.metadata(), 'status': 'ok', 'timings': timings,
                                  'relative_residual': float(residual),
                                  'relative_difference_cpu': float(difference),
                                  'accuracy_pass': bool(residual < 1e-10 and difference < 1e-10)})
    cpu = next((r for r in report['results'] if r['backend'] == 'numpy' and r['status'] == 'ok'), None)
    if cpu:
        for row in report['results']:
            if row['status'] == 'ok':
                row['cached_solve_speedup_vs_cpu'] = cpu['timings']['cached_solve']['median_seconds'] / row['timings']['cached_solve']['median_seconds']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=400)
    parser.add_argument('--batch', type=int, default=1000)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=2)
    parser.add_argument('--backends', nargs='+', default=['numpy', 'torch', 'cupy'])
    args = parser.parse_args()
    print(json.dumps(benchmark(args.n, args.batch, args.repeats, args.warmup, args.backends), indent=2))
