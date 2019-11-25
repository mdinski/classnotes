from scipy.interpolate import Rbf
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
from matplotlib import cm
from math import copysign
import numpy as np
import itertools, time
import numpy.linalg as lin
import scipy.linalg as slin
import scipy.sparse as sps
from scipy.linalg import get_blas_funcs
import scipy.sparse.linalg
from numpy.linalg import norm
from warnings import warn
from scipy.sparse import (bmat, csc_matrix, eye, issparse)
from scipy.optimize._numdiff import approx_derivative
from scipy.optimize import (Bounds,
                            NonlinearConstraint,
                            LinearConstraint, OptimizeResult)

from scipy.sparse.linalg import LinearOperator

TERMINATION_MESSAGES = {
    0: "The maximum number of function evaluations is exceeded.",
    1: "`gtol` termination condition is satisfied.",
    2: "`xtol` termination condition is satisfied.",
    3: "`callback` function requested termination"
}


class HessianUpdateStrategy(object):

    def initialize(self, n, approx_type):
        raise NotImplementedError("The method ``initialize(n, approx_type)``"
                                  " is not implemented.")

    def update(self, delta_x, delta_grad):
        raise NotImplementedError("The method ``update(delta_x, delta_grad)``"
                                  " is not implemented.")

    def dot(self, p):
        raise NotImplementedError("The method ``dot(p)``"
                                  " is not implemented.")

    def get_matrix(self):
        raise NotImplementedError("The method ``get_matrix(p)``"
                                  " is not implemented.")

    
class FullHessianUpdateStrategy(HessianUpdateStrategy):
    _syr = get_blas_funcs('syr', dtype='d')  # Symmetric rank 1 update
    _syr2 = get_blas_funcs('syr2', dtype='d')  # Symmetric rank 2 update
    _symv = get_blas_funcs('symv', dtype='d')

    def __init__(self, init_scale='auto'):
        self.init_scale = init_scale
        self.first_iteration = None
        self.approx_type = None
        self.B = None
        self.H = None

    def initialize(self, n, approx_type):
        self.first_iteration = True
        self.n = n
        self.approx_type = approx_type
        if approx_type not in ('hess', 'inv_hess'):
            raise ValueError("`approx_type` must be 'hess' or 'inv_hess'.")
        # Create matrix
        if self.approx_type == 'hess':
            self.B = np.eye(n, dtype=float)
        else:
            self.H = np.eye(n, dtype=float)

    def _auto_scale(self, delta_x, delta_grad):
        s_norm2 = np.dot(delta_x, delta_x)
        y_norm2 = np.dot(delta_grad, delta_grad)
        ys = np.abs(np.dot(delta_grad, delta_x))
        if ys == 0.0 or y_norm2 == 0 or s_norm2 == 0:
            return 1
        if self.approx_type == 'hess':
            return y_norm2 / ys
        else:
            return ys / y_norm2

    def _update_implementation(self, delta_x, delta_grad):
        raise NotImplementedError("The method ``_update_implementation``"
                                  " is not implemented.")

    def update(self, delta_x, delta_grad):
        if np.all(delta_x == 0.0):
            return
        if np.all(delta_grad == 0.0):
            warn('delta_grad == 0.0. Check if the approximated '
                 'function is linear. If the function is linear '
                 'better results can be obtained by defining the '
                 'Hessian as zero instead of using quasi-Newton '
                 'approximations.', UserWarning)
            return
        if self.first_iteration:
            # Get user specific scale
            if self.init_scale == "auto":
                scale = self._auto_scale(delta_x, delta_grad)
            else:
                scale = float(self.init_scale)
            # Scale initial matrix with ``scale * np.eye(n)``
            if self.approx_type == 'hess':
                self.B *= scale
            else:
                self.H *= scale
            self.first_iteration = False
        self._update_implementation(delta_x, delta_grad)

    def dot(self, p):
        if self.approx_type == 'hess':
            return self._symv(1, self.B, p)
        else:
            return self._symv(1, self.H, p)

    def get_matrix(self):
        if self.approx_type == 'hess':
            M = np.copy(self.B)
        else:
            M = np.copy(self.H)
        li = np.tril_indices_from(M, k=-1)
        M[li] = M.T[li]
        return M

class SR1(FullHessianUpdateStrategy):
    def __init__(self, min_denominator=1e-8, init_scale='auto'):
        self.min_denominator = min_denominator
        super(SR1, self).__init__(init_scale)

    def _update_implementation(self, delta_x, delta_grad):
        if self.approx_type == 'hess':
            w = delta_x
            z = delta_grad
        else:
            w = delta_grad
            z = delta_x
        Mw = self.dot(w)
        z_minus_Mw = z - Mw
        denominator = np.dot(w, z_minus_Mw)
        if np.abs(denominator) <= self.min_denominator*norm(w)*norm(z_minus_Mw):
            return
        if self.approx_type == 'hess':
            self.B = self._syr(1/denominator, z_minus_Mw, a=self.B)
        else:
            self.H = self._syr(1/denominator, z_minus_Mw, a=self.H)


class CanonicalConstraint(object):

    def __init__(self, n_eq, n_ineq, fun, jac, hess, keep_feasible):
        self.n_eq = n_eq
        self.n_ineq = n_ineq
        self.fun = fun
        self.jac = jac
        self.hess = hess
        self.keep_feasible = keep_feasible

    @classmethod
    def from_PreparedConstraint(cls, constraint):
        """Create an instance from `PreparedConstrained` object."""
        lb, ub = constraint.bounds
        cfun = constraint.fun
        keep_feasible = constraint.keep_feasible

        if np.all(lb == -np.inf) and np.all(ub == np.inf):
            return cls.empty(cfun.n)

        if np.all(lb == -np.inf) and np.all(ub == np.inf):
            return cls.empty(cfun.n)
        elif np.all(lb == ub):
            return cls._equal_to_canonical(cfun, lb)
        elif np.all(lb == -np.inf):
            return cls._less_to_canonical(cfun, ub, keep_feasible)
        elif np.all(ub == np.inf):
            return cls._greater_to_canonical(cfun, lb, keep_feasible)
        else:
            return cls._interval_to_canonical(cfun, lb, ub, keep_feasible)

    @classmethod
    def empty(cls, n):
        empty_fun = np.empty(0)
        empty_jac = np.empty((0, n))
        empty_hess = sps.csr_matrix((n, n))

        def fun(x):
            return empty_fun, empty_fun

        def jac(x):
            return empty_jac, empty_jac

        def hess(x, v_eq, v_ineq):
            return empty_hess

        return cls(0, 0, fun, jac, hess, np.empty(0, dtype=np.bool))

    @classmethod
    def concatenate(cls, canonical_constraints, sparse_jacobian):

        def fun(x):
            if canonical_constraints:
                eq_all, ineq_all = zip(
                        *[c.fun(x) for c in canonical_constraints])
            else:
                eq_all, ineq_all = [], []

            return np.hstack(eq_all), np.hstack(ineq_all)

        if sparse_jacobian:
            vstack = sps.vstack
        else:
            vstack = np.vstack

        def jac(x):
            if canonical_constraints:
                eq_all, ineq_all = zip(
                        *[c.jac(x) for c in canonical_constraints])
            else:
                eq_all, ineq_all = [], []

            return vstack(eq_all), vstack(ineq_all)

        def hess(x, v_eq, v_ineq):
            hess_all = []
            index_eq = 0
            index_ineq = 0
            for c in canonical_constraints:
                vc_eq = v_eq[index_eq:index_eq + c.n_eq]
                vc_ineq = v_ineq[index_ineq:index_ineq + c.n_ineq]
                hess_all.append(c.hess(x, vc_eq, vc_ineq))
                index_eq += c.n_eq
                index_ineq += c.n_ineq

            def matvec(p):
                result = np.zeros_like(p)
                for h in hess_all:
                    result += h.dot(p)
                return result

            n = x.shape[0]
            return sps.linalg.LinearOperator((n, n), matvec, dtype=float)

        n_eq = sum(c.n_eq for c in canonical_constraints)
        n_ineq = sum(c.n_ineq for c in canonical_constraints)
        keep_feasible = np.hstack([c.keep_feasible for c in
                                   canonical_constraints])

        return cls(n_eq, n_ineq, fun, jac, hess, keep_feasible)

    @classmethod
    def _equal_to_canonical(cls, cfun, value):
        empty_fun = np.empty(0)
        n = cfun.n

        n_eq = value.shape[0]
        n_ineq = 0
        keep_feasible = np.empty(0, dtype=bool)

        if cfun.sparse_jacobian:
            empty_jac = sps.csr_matrix((0, n))
        else:
            empty_jac = np.empty((0, n))

        def fun(x):
            return cfun.fun(x) - value, empty_fun

        def jac(x):
            return cfun.jac(x), empty_jac

        def hess(x, v_eq, v_ineq):
            return cfun.hess(x, v_eq)

        empty_fun = np.empty(0)
        n = cfun.n
        if cfun.sparse_jacobian:
            empty_jac = sps.csr_matrix((0, n))
        else:
            empty_jac = np.empty((0, n))

        return cls(n_eq, n_ineq, fun, jac, hess, keep_feasible)

    @classmethod
    def _less_to_canonical(cls, cfun, ub, keep_feasible):
        empty_fun = np.empty(0)
        n = cfun.n
        if cfun.sparse_jacobian:
            empty_jac = sps.csr_matrix((0, n))
        else:
            empty_jac = np.empty((0, n))

        finite_ub = ub < np.inf
        n_eq = 0
        n_ineq = np.sum(finite_ub)

        if np.all(finite_ub):
            def fun(x):
                return empty_fun, cfun.fun(x) - ub

            def jac(x):
                return empty_jac, cfun.jac(x)

            def hess(x, v_eq, v_ineq):
                return cfun.hess(x, v_ineq)
        else:
            finite_ub = np.nonzero(finite_ub)[0]
            keep_feasible = keep_feasible[finite_ub]
            ub = ub[finite_ub]

            def fun(x):
                return empty_fun, cfun.fun(x)[finite_ub] - ub

            def jac(x):
                return empty_jac, cfun.jac(x)[finite_ub]

            def hess(x, v_eq, v_ineq):
                v = np.zeros(cfun.m)
                v[finite_ub] = v_ineq
                return cfun.hess(x, v)

        return cls(n_eq, n_ineq, fun, jac, hess, keep_feasible)

    @classmethod
    def _greater_to_canonical(cls, cfun, lb, keep_feasible):
        empty_fun = np.empty(0)
        n = cfun.n
        if cfun.sparse_jacobian:
            empty_jac = sps.csr_matrix((0, n))
        else:
            empty_jac = np.empty((0, n))

        finite_lb = lb > -np.inf
        n_eq = 0
        n_ineq = np.sum(finite_lb)

        if np.all(finite_lb):
            def fun(x):
                return empty_fun, lb - cfun.fun(x)

            def jac(x):
                return empty_jac, -cfun.jac(x)

            def hess(x, v_eq, v_ineq):
                return cfun.hess(x, -v_ineq)
        else:
            finite_lb = np.nonzero(finite_lb)[0]
            keep_feasible = keep_feasible[finite_lb]
            lb = lb[finite_lb]

            def fun(x):
                return empty_fun, lb - cfun.fun(x)[finite_lb]

            def jac(x):
                return empty_jac, -cfun.jac(x)[finite_lb]

            def hess(x, v_eq, v_ineq):
                v = np.zeros(cfun.m)
                v[finite_lb] = -v_ineq
                return cfun.hess(x, v)

        return cls(n_eq, n_ineq, fun, jac, hess, keep_feasible)

    @classmethod
    def _interval_to_canonical(cls, cfun, lb, ub, keep_feasible):
        lb_inf = lb == -np.inf
        ub_inf = ub == np.inf
        equal = lb == ub
        less = lb_inf & ~ub_inf
        greater = ub_inf & ~lb_inf
        interval = ~equal & ~lb_inf & ~ub_inf

        equal = np.nonzero(equal)[0]
        less = np.nonzero(less)[0]
        greater = np.nonzero(greater)[0]
        interval = np.nonzero(interval)[0]
        n_less = less.shape[0]
        n_greater = greater.shape[0]
        n_interval = interval.shape[0]
        n_ineq = n_less + n_greater + 2 * n_interval
        n_eq = equal.shape[0]

        keep_feasible = np.hstack((keep_feasible[less],
                                   keep_feasible[greater],
                                   keep_feasible[interval],
                                   keep_feasible[interval]))

        def fun(x):
            f = cfun.fun(x)
            eq = f[equal] - lb[equal]
            le = f[less] - ub[less]
            ge = lb[greater] - f[greater]
            il = f[interval] - ub[interval]
            ig = lb[interval] - f[interval]
            return eq, np.hstack((le, ge, il, ig))

        def jac(x):
            J = cfun.jac(x)
            eq = J[equal]
            le = J[less]
            ge = -J[greater]
            il = J[interval]
            ig = -il
            if sps.issparse(J):
                ineq = sps.vstack((le, ge, il, ig))
            else:
                ineq = np.vstack((le, ge, il, ig))
            return eq, ineq

        def hess(x, v_eq, v_ineq):
            n_start = 0
            v_l = v_ineq[n_start:n_start + n_less]
            n_start += n_less
            v_g = v_ineq[n_start:n_start + n_greater]
            n_start += n_greater
            v_il = v_ineq[n_start:n_start + n_interval]
            n_start += n_interval
            v_ig = v_ineq[n_start:n_start + n_interval]

            v = np.zeros_like(lb)
            v[equal] = v_eq
            v[less] = v_l
            v[greater] = -v_g
            v[interval] = v_il - v_ig

            return cfun.hess(x, v)

        return cls(n_eq, n_ineq, fun, jac, hess, keep_feasible)


class LagrangianHessian(object):
    def __init__(self, n, objective_hess, constraints_hess):
        self.n = n
        self.objective_hess = objective_hess
        self.constraints_hess = constraints_hess

    def __call__(self, x, v_eq=np.empty(0), v_ineq=np.empty(0)):
        H_objective = self.objective_hess(x)
        H_constraints = self.constraints_hess(x, v_eq, v_ineq)

        def matvec(p):
            return H_objective.dot(p) + H_constraints.dot(p)

        return LinearOperator((self.n, self.n), matvec)


class VectorFunction(object):

    def __init__(self, fun, x0, jac, hess,
                 finite_diff_rel_step, finite_diff_jac_sparsity,
                 finite_diff_bounds, sparse_jacobian):
        if not callable(jac) and jac not in FD_METHODS:
            raise ValueError("`jac` must be either callable or one of {}."
                             .format(FD_METHODS))

        if not (callable(hess) or hess in FD_METHODS
                or isinstance(hess, HessianUpdateStrategy)):
            raise ValueError("`hess` must be either callable,"
                             "HessianUpdateStrategy or one of {}."
                             .format(FD_METHODS))

        if jac in FD_METHODS and hess in FD_METHODS:
            raise ValueError("Whenever the Jacobian is estimated via "
                             "finite-differences, we require the Hessian to "
                             "be estimated using one of the quasi-Newton "
                             "strategies.")

        self.x = np.atleast_1d(x0).astype(float)
        self.n = self.x.size
        self.nfev = 0
        self.njev = 0
        self.nhev = 0
        self.f_updated = False
        self.J_updated = False
        self.H_updated = False

        finite_diff_options = {}
        if jac in FD_METHODS:
            finite_diff_options["method"] = jac
            finite_diff_options["rel_step"] = finite_diff_rel_step
            if finite_diff_jac_sparsity is not None:
                sparsity_groups = group_columns(finite_diff_jac_sparsity)
                finite_diff_options["sparsity"] = (finite_diff_jac_sparsity,
                                                   sparsity_groups)
            finite_diff_options["bounds"] = finite_diff_bounds
            self.x_diff = np.copy(self.x)
        if hess in FD_METHODS:
            finite_diff_options["method"] = hess
            finite_diff_options["rel_step"] = finite_diff_rel_step
            finite_diff_options["as_linear_operator"] = True
            self.x_diff = np.copy(self.x)
        if jac in FD_METHODS and hess in FD_METHODS:
            raise ValueError("Whenever the Jacobian is estimated via "
                             "finite-differences, we require the Hessian to "
                             "be estimated using one of the quasi-Newton "
                             "strategies.")

        # Function evaluation
        def fun_wrapped(x):
            self.nfev += 1
            return np.atleast_1d(fun(x))

        def update_fun():
            self.f = fun_wrapped(self.x)

        self._update_fun_impl = update_fun
        update_fun()

        self.v = np.zeros_like(self.f)
        self.m = self.v.size

        self._update_jac_impl = update_jac

        # Define Hessian
        if callable(hess):
            self.H = hess(self.x, self.v)
            self.H_updated = True
            self.nhev += 1

            if sps.issparse(self.H):
                def hess_wrapped(x, v):
                    self.nhev += 1
                    return sps.csr_matrix(hess(x, v))
                self.H = sps.csr_matrix(self.H)

            elif isinstance(self.H, LinearOperator):
                def hess_wrapped(x, v):
                    self.nhev += 1
                    return hess(x, v)

            else:
                def hess_wrapped(x, v):
                    self.nhev += 1
                    return np.atleast_2d(np.asarray(hess(x, v)))
                self.H = np.atleast_2d(np.asarray(self.H))

            def update_hess():
                self.H = hess_wrapped(self.x, self.v)
        elif hess in FD_METHODS:
            def jac_dot_v(x, v):
                return jac_wrapped(x).T.dot(v)

            def update_hess():
                self._update_jac()
                self.H = approx_derivative(jac_dot_v, self.x,
                                           f0=self.J.T.dot(self.v),
                                           args=(self.v,),
                                           **finite_diff_options)
            update_hess()
            self.H_updated = True
        elif isinstance(hess, HessianUpdateStrategy):
            self.H = hess
            self.H.initialize(self.n, 'hess')
            self.H_updated = True
            self.x_prev = None
            self.J_prev = None

            def update_hess():
                self._update_jac()
                if self.x_prev is not None and self.J_prev is not None:
                    delta_x = self.x - self.x_prev
                    delta_g = self.J.T.dot(self.v) - self.J_prev.T.dot(self.v)
                    self.H.update(delta_x, delta_g)

        self._update_hess_impl = update_hess

        if isinstance(hess, HessianUpdateStrategy):
            def update_x(x):
                self._update_jac()
                self.x_prev = self.x
                self.J_prev = self.J
                self.x = np.atleast_1d(x).astype(float)
                self.f_updated = False
                self.J_updated = False
                self.H_updated = False
                self._update_hess()
        else:
            def update_x(x):
                self.x = np.atleast_1d(x).astype(float)
                self.f_updated = False
                self.J_updated = False
                self.H_updated = False

        self._update_x_impl = update_x

    def _update_v(self, v):
        if not np.array_equal(v, self.v):
            self.v = v
            self.H_updated = False

    def _update_x(self, x):
        if not np.array_equal(x, self.x):
            self._update_x_impl(x)

    def _update_fun(self):
        if not self.f_updated:
            self._update_fun_impl()
            self.f_updated = True

    def _update_jac(self):
        if not self.J_updated:
            self._update_jac_impl()
            self.J_updated = True

    def _update_hess(self):
        if not self.H_updated:
            self._update_hess_impl()
            self.H_updated = True

    def fun(self, x):
        self._update_x(x)
        self._update_fun()
        return self.f

    def jac(self, x):
        self._update_x(x)
        self._update_jac()
        return self.J

    def hess(self, x, v):
        # v should be updated before x.
        self._update_v(v)
        self._update_x(x)
        self._update_hess()
        return self.H


class LinearVectorFunction(object):
    def __init__(self, A, x0, sparse_jacobian):
        if sparse_jacobian or sparse_jacobian is None and sps.issparse(A):
            self.J = sps.csr_matrix(A)
            self.sparse_jacobian = True
        elif sps.issparse(A):
            self.J = A.toarray()
            self.sparse_jacobian = False
        else:
            self.J = np.atleast_2d(A)
            self.sparse_jacobian = False

        self.m, self.n = self.J.shape

        self.x = np.atleast_1d(x0).astype(float)
        self.f = self.J.dot(self.x)
        self.f_updated = True

        self.v = np.zeros(self.m, dtype=float)
        self.H = sps.csr_matrix((self.n, self.n))

    def _update_x(self, x):
        if not np.array_equal(x, self.x):
            self.x = np.atleast_1d(x).astype(float)
            self.f_updated = False

    def fun(self, x):
        self._update_x(x)
        if not self.f_updated:
            self.f = self.J.dot(x)
            self.f_updated = True
        return self.f

    def jac(self, x):
        self._update_x(x)
        return self.J

    def hess(self, x, v):
        self._update_x(x)
        self.v = v
        return self.H


class IdentityVectorFunction(LinearVectorFunction):
    def __init__(self, x0, sparse_jacobian):
        n = len(x0)
        if sparse_jacobian or sparse_jacobian is None:
            A = sps.eye(n, format='csr')
            sparse_jacobian = True
        else:
            A = np.eye(n)
            sparse_jacobian = False
        super(IdentityVectorFunction, self).__init__(A, x0, sparse_jacobian)


        
class PreparedConstraint(object):

    def __init__(self, constraint, x0, sparse_jacobian=None,
                 finite_diff_bounds=(-np.inf, np.inf)):
        if isinstance(constraint, NonlinearConstraint):
            fun = VectorFunction(constraint.fun, x0,
                                 constraint.jac, constraint.hess,
                                 constraint.finite_diff_rel_step,
                                 constraint.finite_diff_jac_sparsity,
                                 finite_diff_bounds, sparse_jacobian)
        elif isinstance(constraint, LinearConstraint):
            fun = LinearVectorFunction(constraint.A, x0, sparse_jacobian)
        elif isinstance(constraint, Bounds):
            fun = IdentityVectorFunction(x0, sparse_jacobian)
        else:
            raise ValueError("`constraint` of an unknown type is passed.")

        m = fun.m
        lb = np.asarray(constraint.lb, dtype=float)
        ub = np.asarray(constraint.ub, dtype=float)
        if lb.ndim == 0:
            lb = np.resize(lb, m)
        if ub.ndim == 0:
            ub = np.resize(ub, m)

        keep_feasible = np.asarray(constraint.keep_feasible, dtype=bool)
        if keep_feasible.ndim == 0:
            keep_feasible = np.resize(keep_feasible, m)
        if keep_feasible.shape != (m,):
            raise ValueError("`keep_feasible` has a wrong shape.")

        mask = keep_feasible & (lb != ub)
        f0 = fun.f
        if np.any(f0[mask] < lb[mask]) or np.any(f0[mask] > ub[mask]):
            raise ValueError("`x0` is infeasible with respect to some "
                             "inequality constraint with `keep_feasible` "
                             "set to True.")

        self.fun = fun
        self.bounds = (lb, ub)
        self.keep_feasible = keep_feasible

    def violation(self, x):
        with suppress_warnings() as sup:
            sup.filter(UserWarning)
            ev = self.fun.fun(np.asarray(x))

        excess_lb = np.maximum(self.bounds[0] - ev, 0)
        excess_ub = np.maximum(ev - self.bounds[1], 0)

        return excess_lb + excess_ub

FD_METHODS = ('2-point', '3-point', 'cs')

class ScalarFunction(object):

    def __init__(self, fun, x0, args, grad, hess, finite_diff_rel_step,
                 finite_diff_bounds):
        if not callable(grad) and grad not in FD_METHODS:
            raise ValueError("`grad` must be either callable or one of {}."
                             .format(FD_METHODS))

        if not (callable(hess) or hess in FD_METHODS
                or isinstance(hess, HessianUpdateStrategy)):
            raise ValueError("`hess` must be either callable,"
                             "HessianUpdateStrategy or one of {}."
                             .format(FD_METHODS))

        if grad in FD_METHODS and hess in FD_METHODS:
            raise ValueError("Whenever the gradient is estimated via "
                             "finite-differences, we require the Hessian "
                             "to be estimated using one of the "
                             "quasi-Newton strategies.")

        self.x = np.atleast_1d(x0).astype(float)
        self.n = self.x.size
        self.nfev = 0
        self.ngev = 0
        self.nhev = 0
        self.f_updated = False
        self.g_updated = False
        self.H_updated = False

        finite_diff_options = {}
        if grad in FD_METHODS:
            finite_diff_options["method"] = grad
            finite_diff_options["rel_step"] = finite_diff_rel_step
            finite_diff_options["bounds"] = finite_diff_bounds
        if hess in FD_METHODS:
            finite_diff_options["method"] = hess
            finite_diff_options["rel_step"] = finite_diff_rel_step
            finite_diff_options["as_linear_operator"] = True

        # Function evaluation
        def fun_wrapped(x):
            self.nfev += 1
            return fun(x, *args)

        def update_fun():
            self.f = fun_wrapped(self.x)

        self._update_fun_impl = update_fun
        self._update_fun()

        if callable(grad):
            def grad_wrapped(x):
                self.ngev += 1
                return np.atleast_1d(grad(x, *args))

            def update_grad():
                self.g = grad_wrapped(self.x)

        elif grad in FD_METHODS:
            def update_grad():
                self._update_fun()
                self.g = approx_derivative(fun_wrapped, self.x, f0=self.f,
                                           **finite_diff_options)

        self._update_grad_impl = update_grad
        self._update_grad()

        # Hessian Evaluation
        if callable(hess):
            self.H = hess(x0, *args)
            self.H_updated = True
            self.nhev += 1

            if sps.issparse(self.H):
                def hess_wrapped(x):
                    self.nhev += 1
                    return sps.csr_matrix(hess(x, *args))
                self.H = sps.csr_matrix(self.H)

            elif isinstance(self.H, LinearOperator):
                def hess_wrapped(x):
                    self.nhev += 1
                    return hess(x, *args)

            else:
                def hess_wrapped(x):
                    self.nhev += 1
                    return np.atleast_2d(np.asarray(hess(x, *args)))
                self.H = np.atleast_2d(np.asarray(self.H))

            def update_hess():
                self.H = hess_wrapped(self.x)

        elif hess in FD_METHODS:
            def update_hess():
                self._update_grad()
                self.H = approx_derivative(grad_wrapped, self.x, f0=self.g,
                                           **finite_diff_options)
                return self.H

            update_hess()
            self.H_updated = True
        elif isinstance(hess, HessianUpdateStrategy):
            self.H = hess
            self.H.initialize(self.n, 'hess')
            self.H_updated = True
            self.x_prev = None
            self.g_prev = None

            def update_hess():
                self._update_grad()
                self.H.update(self.x - self.x_prev, self.g - self.g_prev)

        self._update_hess_impl = update_hess

        if isinstance(hess, HessianUpdateStrategy):
            def update_x(x):
                self._update_grad()
                self.x_prev = self.x
                self.g_prev = self.g

                self.x = np.atleast_1d(x).astype(float)
                self.f_updated = False
                self.g_updated = False
                self.H_updated = False
                self._update_hess()
        else:
            def update_x(x):
                self.x = np.atleast_1d(x).astype(float)
                self.f_updated = False
                self.g_updated = False
                self.H_updated = False
        self._update_x_impl = update_x

    def _update_fun(self):
        if not self.f_updated:
            self._update_fun_impl()
            self.f_updated = True

    def _update_grad(self):
        if not self.g_updated:
            self._update_grad_impl()
            self.g_updated = True

    def _update_hess(self):
        if not self.H_updated:
            self._update_hess_impl()
            self.H_updated = True

    def fun(self, x):
        if not np.array_equal(x, self.x):
            self._update_x_impl(x)
        self._update_fun()
        return self.f

    def grad(self, x):
        if not np.array_equal(x, self.x):
            self._update_x_impl(x)
        self._update_grad()
        return self.g

    def hess(self, x):
        if not np.array_equal(x, self.x):
            self._update_x_impl(x)
        self._update_hess()
        return self.H



class BarrierSubproblem:
    def __init__(self, x0, s0, fun, grad, lagr_hess, n_vars, n_ineq, n_eq,
                 constr, jac, barrier_parameter, tolerance,
                 enforce_feasibility, global_stop_criteria,
                 xtol, fun0, grad0, constr_ineq0, jac_ineq0, constr_eq0,
                 jac_eq0):
        # Store parameters
        self.n_vars = n_vars
        self.x0 = x0
        self.s0 = s0
        self.fun = fun
        self.grad = grad
        self.lagr_hess = lagr_hess
        self.constr = constr
        self.jac = jac
        self.barrier_parameter = barrier_parameter
        self.tolerance = tolerance
        self.n_eq = n_eq
        self.n_ineq = n_ineq
        self.enforce_feasibility = enforce_feasibility
        self.global_stop_criteria = global_stop_criteria
        self.xtol = xtol
        self.fun0 = self._compute_function(fun0, constr_ineq0, s0)
        self.grad0 = self._compute_gradient(grad0)
        self.constr0 = self._compute_constr(constr_ineq0, constr_eq0, s0)
        self.jac0 = self._compute_jacobian(jac_eq0, jac_ineq0, s0)
        self.terminate = False

    def update(self, barrier_parameter, tolerance):
        self.barrier_parameter = barrier_parameter
        self.tolerance = tolerance

    def get_slack(self, z):
        return z[self.n_vars:self.n_vars+self.n_ineq]

    def get_variables(self, z):
        return z[:self.n_vars]

    def function_and_constraints(self, z):
        x = self.get_variables(z)
        s = self.get_slack(z)
        f = self.fun(x)
        c_eq, c_ineq = self.constr(x)
        return (self._compute_function(f, c_ineq, s),
                self._compute_constr(c_ineq, c_eq, s))

    def _compute_function(self, f, c_ineq, s):
        s[self.enforce_feasibility] = -c_ineq[self.enforce_feasibility]
        log_s = [np.log(s_i) if s_i > 0 else -np.inf for s_i in s]
        return f - self.barrier_parameter*np.sum(log_s)

    def _compute_constr(self, c_ineq, c_eq, s):
        return np.hstack((c_eq,
                          c_ineq + s))

    def scaling(self, z):
        s = self.get_slack(z)
        diag_elements = np.hstack((np.ones(self.n_vars), s))

        # Diagonal Matrix
        def matvec(vec):
            return diag_elements*vec
        return LinearOperator((self.n_vars+self.n_ineq,
                               self.n_vars+self.n_ineq),
                              matvec)

    def gradient_and_jacobian(self, z):
        x = self.get_variables(z)
        s = self.get_slack(z)
        g = self.grad(x)
        J_eq, J_ineq = self.jac(x)
        return (self._compute_gradient(g),
                self._compute_jacobian(J_eq, J_ineq, s))

    def _compute_gradient(self, g):
        return np.hstack((g, -self.barrier_parameter*np.ones(self.n_ineq)))

    def _compute_jacobian(self, J_eq, J_ineq, s):
        if self.n_ineq == 0:
            return J_eq
        else:
            if sps.issparse(J_eq) or sps.issparse(J_ineq):
                J_eq = sps.csr_matrix(J_eq)
                J_ineq = sps.csr_matrix(J_ineq)
                return self._assemble_sparse_jacobian(J_eq, J_ineq, s)
            else:
                S = np.diag(s)
                zeros = np.zeros((self.n_eq, self.n_ineq))
                if sps.issparse(J_ineq):
                    J_ineq = J_ineq.toarray()
                if sps.issparse(J_eq):
                    J_eq = J_eq.toarray()
                return np.block([[J_eq, zeros],
                                 [J_ineq, S]])

    def _assemble_sparse_jacobian(self, J_eq, J_ineq, s):

        n_vars, n_ineq, n_eq = self.n_vars, self.n_ineq, self.n_eq
        J_aux = sps.vstack([J_eq, J_ineq], "csr")
        indptr, indices, data = J_aux.indptr, J_aux.indices, J_aux.data
        new_indptr = indptr + np.hstack((np.zeros(n_eq, dtype=int),
                                         np.arange(n_ineq+1, dtype=int)))
        size = indices.size+n_ineq
        new_indices = np.empty(size)
        new_data = np.empty(size)
        mask = np.full(size, False, bool)
        mask[new_indptr[-n_ineq:]-1] = True
        new_indices[mask] = n_vars+np.arange(n_ineq)
        new_indices[~mask] = indices
        new_data[mask] = s
        new_data[~mask] = data
        J = sps.csr_matrix((new_data, new_indices, new_indptr),
                           (n_eq + n_ineq, n_vars + n_ineq))
        return J

    def lagrangian_hessian_x(self, z, v):
        x = self.get_variables(z)
        v_eq = v[:self.n_eq]
        v_ineq = v[self.n_eq:self.n_eq+self.n_ineq]
        lagr_hess = self.lagr_hess
        return lagr_hess(x, v_eq, v_ineq)

    def lagrangian_hessian_s(self, z, v):
        s = self.get_slack(z)
        primal = self.barrier_parameter
        primal_dual = v[-self.n_ineq:]*s
        return np.where(v[-self.n_ineq:] > 0, primal_dual, primal)

    def lagrangian_hessian(self, z, v):
        Hx = self.lagrangian_hessian_x(z, v)
        if self.n_ineq > 0:
            S_Hs_S = self.lagrangian_hessian_s(z, v)
            
        def matvec(vec):
            vec_x = self.get_variables(vec)
            vec_s = self.get_slack(vec)
            if self.n_ineq > 0:
                return np.hstack((Hx.dot(vec_x), S_Hs_S*vec_s))
            else:
                return Hx.dot(vec_x)
        return LinearOperator((self.n_vars+self.n_ineq,
                               self.n_vars+self.n_ineq),
                              matvec)

    def stop_criteria(self, state, z, last_iteration_failed,
                      optimality, constr_violation,
                      trust_radius, penalty, cg_info):

        x = self.get_variables(z)
        if self.global_stop_criteria(state, x,
                                     last_iteration_failed,
                                     trust_radius, penalty,
                                     cg_info,
                                     self.barrier_parameter,
                                     self.tolerance):
            self.terminate = True
            return True
        else:
            g_cond = (optimality < self.tolerance and
                      constr_violation < self.tolerance)
            x_cond = trust_radius < self.xtol
            return g_cond or x_cond
        
def inside_box_boundaries(x, lb, ub):
    return (lb <= x).all() and (x <= ub).all()

def box_sphere_intersections(z, d, lb, ub, trust_radius,
                             entire_line=False,
                             extra_info=False):

    ta_b, tb_b, intersect_b = box_intersections(z, d, lb, ub,
                                                entire_line)
    ta_s, tb_s, intersect_s = sphere_intersections(z, d,
                                                   trust_radius,
                                                   entire_line)
    ta = np.maximum(ta_b, ta_s)
    tb = np.minimum(tb_b, tb_s)
    if intersect_b and intersect_s and ta <= tb:
        intersect = True
    else:
        intersect = False

    if extra_info:
        sphere_info = {'ta': ta_s, 'tb': tb_s, 'intersect': intersect_s}
        box_info = {'ta': ta_b, 'tb': tb_b, 'intersect': intersect_b}
        return ta, tb, intersect, sphere_info, box_info
    else:
        return ta, tb, intersect

def box_intersections(z, d, lb, ub,
                      entire_line=False):

    # Make sure it is a numpy array
    z = np.asarray(z)
    d = np.asarray(d)
    lb = np.asarray(lb)
    ub = np.asarray(ub)
    # Special case when d=0
    if norm(d) == 0:
        return 0, 0, False

    zero_d = (d == 0)
    if (z[zero_d] < lb[zero_d]).any() or (z[zero_d] > ub[zero_d]).any():
        intersect = False
        return 0, 0, intersect
    not_zero_d = np.logical_not(zero_d)
    z = z[not_zero_d]
    d = d[not_zero_d]
    lb = lb[not_zero_d]
    ub = ub[not_zero_d]

    t_lb = (lb-z) / d
    t_ub = (ub-z) / d
    ta = max(np.minimum(t_lb, t_ub))
    tb = min(np.maximum(t_lb, t_ub))

    if ta <= tb:
        intersect = True
    else:
        intersect = False

    if not entire_line:
        if tb < 0 or ta > 1:
            intersect = False
            ta = 0
            tb = 0
        else:
            ta = max(0, ta)
            tb = min(1, tb)

    return ta, tb, intersect

def sphere_intersections(z, d, trust_radius,
                         entire_line=False):

    if norm(d) == 0:
        return 0, 0, False
    if np.isinf(trust_radius):
        if entire_line:
            ta = -np.inf
            tb = np.inf
        else:
            ta = 0
            tb = 1
        intersect = True
        return ta, tb, intersect

    a = np.dot(d, d)
    b = 2 * np.dot(z, d)
    c = np.dot(z, z) - trust_radius**2
    discriminant = b*b - 4*a*c
    if discriminant < 0:
        intersect = False
        return 0, 0, intersect
    sqrt_discriminant = np.sqrt(discriminant)

    aux = b + copysign(sqrt_discriminant, b)
    ta = -aux / (2*a)
    tb = -2*c / aux
    ta, tb = sorted([ta, tb])

    if entire_line:
        intersect = True
    else:
        if tb < 0 or ta > 1:
            intersect = False
            ta = 0
            tb = 0
        else:
            intersect = True
            ta = max(0, ta)
            tb = min(1, tb)

    return ta, tb, intersect


def strict_bounds(lb, ub, keep_feasible, n_vars):
    strict_lb = np.resize(lb, n_vars).astype(float)
    strict_ub = np.resize(ub, n_vars).astype(float)
    keep_feasible = np.resize(keep_feasible, n_vars)
    strict_lb[~keep_feasible] = -np.inf
    strict_ub[~keep_feasible] = np.inf
    return strict_lb, strict_ub

def orthogonality(A, g):
    norm_g = np.linalg.norm(g)
    if issparse(A):
        norm_A = scipy.sparse.linalg.norm(A, ord='fro')
    else:
        norm_A = np.linalg.norm(A, ord='fro')

    if norm_g == 0 or norm_A == 0:
        return 0

    norm_A_g = np.linalg.norm(A.dot(g))
    orth = norm_A_g / (norm_A*norm_g)
    return orth


        
def augmented_system_projections(A, m, n, orth_tol, max_refin, tol):

    K = csc_matrix(bmat([[eye(n), A.T], [A, None]]))
    try:
        solve = scipy.sparse.linalg.factorized(K)
    except RuntimeError:
        warn("Singular Jacobian matrix. Using dense SVD decomposition to "
             "perform the factorizations.")
        return svd_factorization_projections(A.toarray(),
                                             m, n, orth_tol,
                                             max_refin, tol)

    def null_space(x):
        v = np.hstack([x, np.zeros(m)])
        lu_sol = solve(v)
        z = lu_sol[:n]

        k = 0
        while orthogonality(A, z) > orth_tol:
            if k >= max_refin:
                break
            new_v = v - K.dot(lu_sol)

            lu_update = solve(new_v)

            lu_sol += lu_update
            z = lu_sol[:n]
            k += 1
        return z

    def least_squares(x):
        v = np.hstack([x, np.zeros(m)])
        lu_sol = solve(v)
        return lu_sol[n:m+n]

    def row_space(x):
        v = np.hstack([np.zeros(n), x])
        lu_sol = solve(v)
        # return z = A.T inv(A A.T) x
        return lu_sol[:n]

    return null_space, least_squares, row_space

        
def default_scaling(x):
    n, = np.shape(x)
    return speye(n)

def projections(A, method=None, orth_tol=1e-12, max_refin=3, tol=1e-15):

    m, n = np.shape(A)

    if m*n == 0:
        A = csc_matrix(A)

    if issparse(A):
        if method is None:
            method = "AugmentedSystem"
        if method not in ("NormalEquation", "AugmentedSystem"):
            raise ValueError("Method not allowed for sparse matrix.")
        if method == "NormalEquation" and not sksparse_available:
            warnings.warn(("Only accepts 'NormalEquation' option when"
                           " scikit-sparse is available. Using "
                           "'AugmentedSystem' option instead."),
                          ImportWarning)
            method = 'AugmentedSystem'
    else:
        if method is None:
            method = "QRFactorization"
        if method not in ("QRFactorization", "SVDFactorization"):
            raise ValueError("Method not allowed for dense array.")

    null_space, least_squares, row_space \
        = augmented_system_projections(A, m, n, orth_tol, max_refin, tol)

    Z = LinearOperator((n, n), null_space)
    LS = LinearOperator((m, n), least_squares)
    Y = LinearOperator((n, m), row_space)

    return Z, LS, Y

def modified_dogleg(A, Y, b, trust_radius, lb, ub):

    newton_point = -Y.dot(b)
    if inside_box_boundaries(newton_point, lb, ub)  \
       and norm(newton_point) <= trust_radius:
        x = newton_point
        return x

    g = A.T.dot(b)
    A_g = A.dot(g)
    cauchy_point = -np.dot(g, g) / np.dot(A_g, A_g) * g
    origin_point = np.zeros_like(cauchy_point)
    z = cauchy_point
    p = newton_point - cauchy_point
    _, alpha, intersect = box_sphere_intersections(z, p, lb, ub,
                                                   trust_radius)
    if intersect:
        x1 = z + alpha*p
    else:
        z = origin_point
        p = cauchy_point
        _, alpha, _ = box_sphere_intersections(z, p, lb, ub,
                                               trust_radius)
        x1 = z + alpha*p

    z = origin_point
    p = newton_point
    _, alpha, _ = box_sphere_intersections(z, p, lb, ub,
                                           trust_radius)
    x2 = z + alpha*p

    if norm(A.dot(x1) + b) < norm(A.dot(x2) + b):
        return x1
    else:
        return x2

def projected_cg(H, c, Z, Y, b, trust_radius=np.inf,
                 lb=None, ub=None, tol=None,
                 max_iter=None, max_infeasible_iter=None,
                 return_all=False):

    CLOSE_TO_ZERO = 1e-25

    n, = np.shape(c)  # Number of parameters
    m, = np.shape(b)  # Number of constraints

    x = Y.dot(-b)
    r = Z.dot(H.dot(x) + c)
    g = Z.dot(r)
    p = -g

    if return_all:
        allvecs = [x]
    H_p = H.dot(p)
    rt_g = norm(g)**2  # g.T g = r.T Z g = r.T g (ref [1]_ p.1389)

    tr_distance = trust_radius - norm(x)
    if tr_distance < 0:
        raise ValueError("Trust region problem does not have a solution.")
    elif tr_distance < CLOSE_TO_ZERO:
        info = {'niter': 0, 'stop_cond': 2, 'hits_boundary': True}
        if return_all:
            allvecs.append(x)
            info['allvecs'] = allvecs
        return x, info

    if tol is None:
        tol = max(min(0.01 * np.sqrt(rt_g), 0.1 * rt_g), CLOSE_TO_ZERO)
    if lb is None:
        lb = np.full(n, -np.inf)
    if ub is None:
        ub = np.full(n, np.inf)
    if max_iter is None:
        max_iter = n-m
    max_iter = min(max_iter, n-m)
    if max_infeasible_iter is None:
        max_infeasible_iter = n-m

    hits_boundary = False
    stop_cond = 1
    counter = 0
    last_feasible_x = np.zeros_like(x)
    k = 0
    for i in range(max_iter):
        if rt_g < tol:
            stop_cond = 4
            break
        k += 1
        pt_H_p = H_p.dot(p)
        if pt_H_p <= 0:
            if np.isinf(trust_radius):
                raise ValueError("Negative curvature not allowed "
                                 "for unrestricted problems.")
            else:
                _, alpha, intersect = box_sphere_intersections(
                    x, p, lb, ub, trust_radius, entire_line=True)
                if intersect:
                    x = x + alpha*p
                x = reinforce_box_boundaries(x, lb, ub)
                stop_cond = 3
                hits_boundary = True
                break

        alpha = rt_g / pt_H_p
        x_next = x + alpha*p

        if np.linalg.norm(x_next) >= trust_radius:
            _, theta, intersect = box_sphere_intersections(x, alpha*p, lb, ub,
                                                           trust_radius)
            if intersect:
                x = x + theta*alpha*p
            x = reinforce_box_boundaries(x, lb, ub)
            stop_cond = 2
            hits_boundary = True
            break

        if inside_box_boundaries(x_next, lb, ub):
            counter = 0
        else:
            counter += 1
        if counter > 0:
            _, theta, intersect = box_sphere_intersections(x, alpha*p, lb, ub,
                                                           trust_radius)
            if intersect:
                last_feasible_x = x + theta*alpha*p
                last_feasible_x = reinforce_box_boundaries(last_feasible_x,
                                                           lb, ub)
                counter = 0

        if counter > max_infeasible_iter:
            break

        if return_all:
            allvecs.append(x_next)

        r_next = r + alpha*H_p
        g_next = Z.dot(r_next)
        rt_g_next = norm(g_next)**2 
        beta = rt_g_next / rt_g
        p = - g_next + beta*p
        x = x_next
        g = g_next
        r = g_next
        rt_g = norm(g)**2
        H_p = H.dot(p)

    if not inside_box_boundaries(x, lb, ub):
        x = last_feasible_x
        hits_boundary = True
    info = {'niter': k, 'stop_cond': stop_cond,
            'hits_boundary': hits_boundary}
    if return_all:
        info['allvecs'] = allvecs
    return x, info

def reinforce_box_boundaries(x, lb, ub):
    """Return clipped value of x"""
    return np.minimum(np.maximum(x, lb), ub)


def equality_constrained_sqp(fun_and_constr, grad_and_jac, lagr_hess,
                             x0, fun0, grad0, constr0,
                             jac0, stop_criteria,
                             state,
                             initial_penalty,
                             initial_trust_radius,
                             factorization_method,
                             trust_lb=None,
                             trust_ub=None,
                             scaling=default_scaling):

    PENALTY_FACTOR = 0.3 
    LARGE_REDUCTION_RATIO = 0.9
    INTERMEDIARY_REDUCTION_RATIO = 0.3
    SUFFICIENT_REDUCTION_RATIO = 1e-8 
    TRUST_ENLARGEMENT_FACTOR_L = 7.0
    TRUST_ENLARGEMENT_FACTOR_S = 2.0
    MAX_TRUST_REDUCTION = 0.5
    MIN_TRUST_REDUCTION = 0.1
    SOC_THRESHOLD = 0.1
    TR_FACTOR = 0.8  # Zeta from formula (3.21), reference [2]_, p.885.
    BOX_FACTOR = 0.5

    print ('constr0',constr0)
    
    n, = np.shape(x0)  # Number of parameters

    print ('trust_lb',trust_lb)
    print (trust_ub)
    if trust_lb is None:
        trust_lb = np.full(n, -np.inf)
    if trust_ub is None:
        trust_ub = np.full(n, np.inf)

    x = np.copy(x0)
    trust_radius = initial_trust_radius
    penalty = initial_penalty
    f = fun0
    c = grad0
    b = constr0
    A = jac0
    S = scaling(x)
    Z, LS, Y = projections(A, factorization_method)
    v = -LS.dot(c)
    H = lagr_hess(x, v)

    optimality = norm(c + A.T.dot(v), np.inf)
    constr_violation = norm(b, np.inf) if len(b) > 0 else 0
    cg_info = {'niter': 0, 'stop_cond': 0,
               'hits_boundary': False}

    last_iteration_failed = False
    while not stop_criteria(state, x, last_iteration_failed,
                            optimality, constr_violation,
                            trust_radius, penalty, cg_info):
        dn = modified_dogleg(A, Y, b,
                             TR_FACTOR*trust_radius,
                             BOX_FACTOR*trust_lb,
                             BOX_FACTOR*trust_ub)

        c_t = H.dot(dn) + c
        b_t = np.zeros_like(b)
        trust_radius_t = np.sqrt(trust_radius**2 - np.linalg.norm(dn)**2)
        lb_t = trust_lb - dn
        ub_t = trust_ub - dn
        dt, cg_info = projected_cg(H, c_t, Z, Y, b_t,
                                   trust_radius_t,
                                   lb_t, ub_t)

        d = dn + dt
        quadratic_model = 1/2*(H.dot(d)).dot(d) + c.T.dot(d)
        linearized_constr = A.dot(d)+b
        vpred = norm(b) - norm(linearized_constr)
        vpred = max(1e-16, vpred)
        previous_penalty = penalty
        if quadratic_model > 0:
            new_penalty = quadratic_model / ((1-PENALTY_FACTOR)*vpred)
            penalty = max(penalty, new_penalty)
        predicted_reduction = -quadratic_model + penalty*vpred

        merit_function = f + penalty*norm(b)
        x_next = x + S.dot(d)
        f_next, b_next = fun_and_constr(x_next)
        merit_function_next = f_next + penalty*norm(b_next)
        actual_reduction = merit_function - merit_function_next
        reduction_ratio = actual_reduction / predicted_reduction

        if reduction_ratio < SUFFICIENT_REDUCTION_RATIO and \
           norm(dn) <= SOC_THRESHOLD * norm(dt):
            y = -Y.dot(b_next)
            _, t, intersect = box_intersections(d, y, trust_lb, trust_ub)
            x_soc = x + S.dot(d + t*y)
            f_soc, b_soc = fun_and_constr(x_soc)
            merit_function_soc = f_soc + penalty*norm(b_soc)
            actual_reduction_soc = merit_function - merit_function_soc
            reduction_ratio_soc = actual_reduction_soc / predicted_reduction
            if intersect and reduction_ratio_soc >= SUFFICIENT_REDUCTION_RATIO:
                x_next = x_soc
                f_next = f_soc
                b_next = b_soc
                reduction_ratio = reduction_ratio_soc

        if reduction_ratio >= LARGE_REDUCTION_RATIO:
            trust_radius = max(TRUST_ENLARGEMENT_FACTOR_L * norm(d),
                               trust_radius)
        elif reduction_ratio >= INTERMEDIARY_REDUCTION_RATIO:
            trust_radius = max(TRUST_ENLARGEMENT_FACTOR_S * norm(d),
                               trust_radius)
        elif reduction_ratio < SUFFICIENT_REDUCTION_RATIO:
            trust_reduction = ((1-SUFFICIENT_REDUCTION_RATIO) /
                               (1-reduction_ratio))
            new_trust_radius = trust_reduction * norm(d)
            if new_trust_radius >= MAX_TRUST_REDUCTION * trust_radius:
                trust_radius *= MAX_TRUST_REDUCTION
            elif new_trust_radius >= MIN_TRUST_REDUCTION * trust_radius:
                trust_radius = new_trust_radius
            else:
                trust_radius *= MIN_TRUST_REDUCTION

        if reduction_ratio >= SUFFICIENT_REDUCTION_RATIO:
            x = x_next
            f, b = f_next, b_next
            c, A = grad_and_jac(x)
            S = scaling(x)
            Z, LS, Y = projections(A, factorization_method)
            v = -LS.dot(c)
            H = lagr_hess(x, v)
            last_iteration_failed = False
            optimality = norm(c + A.T.dot(v), np.inf)
            constr_violation = norm(b, np.inf) if len(b) > 0 else 0
        else:
            penalty = previous_penalty
            last_iteration_failed = True

    return x, state
        

def tr_interior_point(fun, grad, lagr_hess, n_vars, n_ineq, n_eq,
                      constr, jac, x0, fun0, grad0,
                      constr_ineq0, jac_ineq0, constr_eq0,
                      jac_eq0, stop_criteria,
                      enforce_feasibility, xtol, state,
                      initial_barrier_parameter,
                      initial_tolerance,
                      initial_penalty,
                      initial_trust_radius,
                      factorization_method):
    print ('inside tr_interior_point impl')    
    print ('constr_ineq0',constr_ineq0)
    print ('constr_eq0',constr_eq0)
    
    BOUNDARY_PARAMETER = 0.995
    BARRIER_DECAY_RATIO = 0.2
    TRUST_ENLARGEMENT = 5

    if enforce_feasibility is None:
        enforce_feasibility = np.zeros(n_ineq, bool)
    barrier_parameter = initial_barrier_parameter
    tolerance = initial_tolerance
    trust_radius = initial_trust_radius
    s0 = np.maximum(-1.5*constr_ineq0, np.ones(n_ineq))
    subprob = BarrierSubproblem(
        x0, s0, fun, grad, lagr_hess, n_vars, n_ineq, n_eq, constr, jac,
        barrier_parameter, tolerance, enforce_feasibility,
        stop_criteria, xtol, fun0, grad0, constr_ineq0, jac_ineq0,
        constr_eq0, jac_eq0)
    z = np.hstack((x0, s0))
    fun0_subprob, constr0_subprob = subprob.fun0, subprob.constr0
    grad0_subprob, jac0_subprob = subprob.grad0, subprob.jac0
    trust_lb = np.hstack((np.full(subprob.n_vars, -np.inf),
                          np.full(subprob.n_ineq, -BOUNDARY_PARAMETER)))
    trust_ub = np.full(subprob.n_vars+subprob.n_ineq, np.inf)

    while True:
        z, state = equality_constrained_sqp(
            subprob.function_and_constraints,
            subprob.gradient_and_jacobian,
            subprob.lagrangian_hessian,
            z, fun0_subprob, grad0_subprob,
            constr0_subprob, jac0_subprob, subprob.stop_criteria,
            state, initial_penalty, trust_radius,
            factorization_method, trust_lb, trust_ub, subprob.scaling)
        if subprob.terminate:
            break

        trust_radius = max(initial_trust_radius,
                           TRUST_ENLARGEMENT*state.tr_radius)
        barrier_parameter *= BARRIER_DECAY_RATIO
        tolerance *= BARRIER_DECAY_RATIO

        subprob.update(barrier_parameter, tolerance)

        fun0_subprob, constr0_subprob = subprob.function_and_constraints(z)
        grad0_subprob, jac0_subprob = subprob.gradient_and_jacobian(z)

    x = subprob.get_variables(z)
    return x, state


def update_state_sqp(state, x, last_iteration_failed, objective, prepared_constraints,
                     start_time, tr_radius, constr_penalty, cg_info):
    state.nit += 1
    state.nfev = objective.nfev
    state.njev = objective.ngev
    state.nhev = objective.nhev
    state.constr_nfev = [c.fun.nfev if isinstance(c.fun, VectorFunction) else 0
                         for c in prepared_constraints]
    state.constr_njev = [c.fun.njev if isinstance(c.fun, VectorFunction) else 0
                         for c in prepared_constraints]
    state.constr_nhev = [c.fun.nhev if isinstance(c.fun, VectorFunction) else 0
                         for c in prepared_constraints]

    if not last_iteration_failed:
        state.x = x
        state.fun = objective.f
        state.grad = objective.g
        state.v = [c.fun.v for c in prepared_constraints]
        state.constr = [c.fun.f for c in prepared_constraints]
        state.jac = [c.fun.J for c in prepared_constraints]

        state.lagrangian_grad = np.copy(state.grad)
        for c in prepared_constraints:
            state.lagrangian_grad += c.fun.J.T.dot(c.fun.v)
        state.optimality = np.linalg.norm(state.lagrangian_grad, np.inf)

        state.constr_violation = 0
        for i in range(len(prepared_constraints)):
            lb, ub = prepared_constraints[i].bounds
            c = state.constr[i]
            state.constr_violation = np.max([state.constr_violation,
                                             np.max(lb - c),
                                             np.max(c - ub)])

    state.execution_time = time.time() - start_time
    state.tr_radius = tr_radius
    state.constr_penalty = constr_penalty
    state.cg_niter += cg_info["niter"]
    state.cg_stop_cond = cg_info["stop_cond"]

    return state

def update_state_ip(state, x, last_iteration_failed, objective,
                    prepared_constraints, start_time,
                    tr_radius, constr_penalty, cg_info,
                    barrier_parameter, barrier_tolerance):
    state = update_state_sqp(state, x, last_iteration_failed, objective,
                             prepared_constraints, start_time, tr_radius,
                             constr_penalty, cg_info)
    state.barrier_parameter = barrier_parameter
    state.barrier_tolerance = barrier_tolerance
    return state


def _minimize_trustregion_constr(fun, x0, args, grad,
                                 hess, hessp, bounds, constraints,
                                 xtol=1e-8, gtol=1e-8,
                                 barrier_tol=1e-8,
                                 sparse_jacobian=None,
                                 callback=None, maxiter=1000,
                                 verbose=0, finite_diff_rel_step=None,
                                 initial_constr_penalty=1.0, initial_tr_radius=1.0,
                                 initial_barrier_parameter=0.1,
                                 initial_barrier_tolerance=0.1,
                                 factorization_method=None,
                                 disp=False):

    x0 = np.atleast_1d(x0).astype(float)
    n_vars = np.size(x0)
    if hess is None:
        if callable(hessp):
            hess = HessianLinearOperator(hessp, n_vars)
        else:
            hess = BFGS()
    if disp and verbose == 0:
        verbose = 1

    if bounds is not None:        
        finite_diff_bounds = strict_bounds(bounds.lb, bounds.ub,
                                           bounds.keep_feasible, n_vars)
        print ('n_vars',n_vars)
        print ('finite_diff_bounds',finite_diff_bounds)
    else:
        finite_diff_bounds = (-np.inf, np.inf)

    # Define Objective Function
    print ('args',args)
    print ('grad',grad)
    print ('hess',hess)  
    print ('finite_diff_rel_step',finite_diff_rel_step)
    print ('finite_diff_bounds',finite_diff_bounds)
    print ('fun',fun)
    objective = ScalarFunction(fun, x0, args, grad, hess,
                               finite_diff_rel_step, finite_diff_bounds)

    # Put constraints in list format when needed
    if isinstance(constraints, (NonlinearConstraint, LinearConstraint)):
        constraints = [constraints]

    # Prepare constraints.
    prepared_constraints = [
        PreparedConstraint(c, x0, sparse_jacobian, finite_diff_bounds)
        for c in constraints]

    n_sparse = sum(c.fun.sparse_jacobian for c in prepared_constraints)
    if 0 < n_sparse < len(prepared_constraints):
        raise ValueError("All constraints must have the same kind of the "
                         "Jacobian --- either all sparse or all dense. "
                         "You can set the sparsity globally by setting "
                         "`sparse_jacobian` to either True of False.")
    if prepared_constraints:
        sparse_jacobian = n_sparse > 0

    if bounds is not None:
        if sparse_jacobian is None:
            sparse_jacobian = True
        prepared_constraints.append(PreparedConstraint(bounds, x0,
                                                       sparse_jacobian))

    c_eq0, c_ineq0, J_eq0, J_ineq0 = initial_constraints_as_canonical(
        n_vars, prepared_constraints, sparse_jacobian)

    canonical_all = [CanonicalConstraint.from_PreparedConstraint(c)
                     for c in prepared_constraints]

    if len(canonical_all) == 0:
        canonical = CanonicalConstraint.empty(n_vars)
    elif len(canonical_all) == 1:
        canonical = canonical_all[0]
    else:
        canonical = CanonicalConstraint.concatenate(canonical_all,
                                                    sparse_jacobian)

    lagrangian_hess = LagrangianHessian(n_vars, objective.hess, canonical.hess)

    method = 'tr_interior_point'

    print ('method in minimize_trustregion_constr',method)

    state = OptimizeResult(
        nit=0, nfev=0, njev=0, nhev=0,
        cg_niter=0, cg_stop_cond=0,
        fun=objective.f, grad=objective.g,
        lagrangian_grad=np.copy(objective.g),
        constr=[c.fun.f for c in prepared_constraints],
        jac=[c.fun.J for c in prepared_constraints],
        constr_nfev=[0 for c in prepared_constraints],
        constr_njev=[0 for c in prepared_constraints],
        constr_nhev=[0 for c in prepared_constraints],
        v=[c.fun.v for c in prepared_constraints],
        method=method)

    start_time = time.time()
    
    def stop_criteria(state, x, last_iteration_failed, tr_radius,
                      constr_penalty, cg_info, barrier_parameter,
                      barrier_tolerance):
        state = update_state_ip(state, x, last_iteration_failed,
                                objective, prepared_constraints,
                                start_time, tr_radius, constr_penalty,
                                cg_info, barrier_parameter, barrier_tolerance)
        state.status = None
        state.niter = state.nit  # Alias for callback (backward-compatibility)
        if callback is not None and callback(np.copy(state.x), state):
            state.status = 3
        elif state.optimality < gtol and state.constr_violation < gtol:
            state.status = 1
        elif (state.tr_radius < xtol
              and state.barrier_parameter < barrier_tol):
            state.status = 2
        elif state.nit > maxiter:
            state.status = 0
        return state.status in (0, 1, 2, 3)

    print ('min TR constr elif tr_interior_point')
    _, result = tr_interior_point(
        objective.fun, objective.grad, lagrangian_hess,
        n_vars, canonical.n_ineq, canonical.n_eq,
        canonical.fun, canonical.jac,
        x0, objective.f, objective.g,
        c_ineq0, J_ineq0, c_eq0, J_eq0,
        stop_criteria,
        canonical.keep_feasible,
        xtol, state, initial_barrier_parameter,
        initial_barrier_tolerance,
        initial_constr_penalty, initial_tr_radius,
        factorization_method)

    result.success = True if result.status in (1, 2) else False
    result.message = TERMINATION_MESSAGES[result.status]
    result.niter = result.nit

    return result


def minimize(fun, x0, args=(), method=None, jac=None, hess=None,
             hessp=None, bounds=None, constraints=(), tol=None,
             callback=None, options=None):
    meth = 'trust-constr'
    x0 = np.asarray(x0)
    if x0.dtype.kind in np.typecodes["AllInteger"]:
        x0 = np.asarray(x0, dtype=float)
    if not isinstance(args, tuple):
        args = (args,)

    if tol is not None:
        options = dict(options)
        options.setdefault('xtol', tol)
        options.setdefault('gtol', tol)
        options.setdefault('barrier_tol', tol)

    if constraints is not None:
        constraints = standardize_constraints(constraints, x0, meth)

    return _minimize_trustregion_constr(fun, x0, args, jac, hess, hessp,
                                        bounds, constraints,
                                        callback=callback, **options)

def standardize_constraints(constraints, x0, meth):
    """Converts constraints to the form required by the solver."""
    all_constraint_types = (NonlinearConstraint, LinearConstraint, dict)
    new_constraint_types = all_constraint_types[:-1]
    if isinstance(constraints, all_constraint_types):
        constraints = [constraints]
    constraints = list(constraints)  

    if meth == 'trust-constr':
        for i, con in enumerate(constraints):
            if not isinstance(con, new_constraint_types):
                constraints[i] = old_constraint_to_new(i, con)
    else:
        for i, con in enumerate(list(constraints)):
            if isinstance(con, new_constraint_types):
                old_constraints = new_constraint_to_old(con, x0)
                constraints[i] = old_constraints[0]
                constraints.extend(old_constraints[1:])  # appends 1 if present

    return constraints

def initial_constraints_as_canonical(n, prepared_constraints, sparse_jacobian):
    c_eq = []
    c_ineq = []
    J_eq = []
    J_ineq = []

    for c in prepared_constraints:
        f = c.fun.f
        J = c.fun.J
        lb, ub = c.bounds
        if np.all(lb == ub):
            c_eq.append(f - lb)
            J_eq.append(J)
        elif np.all(lb == -np.inf):
            finite_ub = ub < np.inf
            c_ineq.append(f[finite_ub] - ub[finite_ub])
            J_ineq.append(J[finite_ub])
        elif np.all(ub == np.inf):
            finite_lb = lb > -np.inf
            c_ineq.append(lb[finite_lb] - f[finite_lb])
            J_ineq.append(-J[finite_lb])
        else:
            lb_inf = lb == -np.inf
            ub_inf = ub == np.inf
            equal = lb == ub
            less = lb_inf & ~ub_inf
            greater = ub_inf & ~lb_inf
            interval = ~equal & ~lb_inf & ~ub_inf

            c_eq.append(f[equal] - lb[equal])
            c_ineq.append(f[less] - ub[less])
            c_ineq.append(lb[greater] - f[greater])
            c_ineq.append(f[interval] - ub[interval])
            c_ineq.append(lb[interval] - f[interval])

            J_eq.append(J[equal])
            J_ineq.append(J[less])
            J_ineq.append(-J[greater])
            J_ineq.append(J[interval])
            J_ineq.append(-J[interval])

    c_eq = np.hstack(c_eq) if c_eq else np.empty(0)
    c_ineq = np.hstack(c_ineq) if c_ineq else np.empty(0)

    if sparse_jacobian:
        vstack = sps.vstack
        empty = sps.csr_matrix((0, n))
    else:
        vstack = np.vstack
        empty = np.empty((0, n))

    J_eq = vstack(J_eq) if J_eq else empty
    J_ineq = vstack(J_ineq) if J_ineq else empty

    return c_eq, c_ineq, J_eq, J_ineq


        
def rosenbrock(x):
    return (1 - x[0])**2 + 100*(x[1] - x[0]**2)**2

x0 = [-1.0,0]

opts = {'maxiter': 1000, 'verbose': 2}

res = minimize (fun=rosenbrock,
                x0=x0,
                method = 'trust-constr',
                jac = "2-point",
                hess = SR1 (),
#                bounds=Bounds([0.3, 0.5], [0.0, 2.0]),
                bounds=Bounds([0.0, 0.0], [3.0, 3.0]),
                options=opts)

print (res)