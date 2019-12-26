from __future__ import division, print_function, absolute_import
#################################################################3
# all this came from ip-nonlinear-solver
# for only non-constrained problems.
from math import copysign
import numpy as np
from numpy.linalg import norm
from scipy.sparse.linalg import LinearOperator
from scipy.sparse import eye, bmat, issparse, csc_matrix, csr_matrix, coo_matrix, find
from scipy.optimize._group_columns import group_dense, group_sparse
import numpy as np
import scipy.sparse as spc
import numpy as np
from warnings import warn
from copy import deepcopy
from scipy.sparse.linalg import LinearOperator
import scipy.sparse as spc
import time
from scipy.optimize import OptimizeResult
sksparse_available = False
import scipy.sparse.linalg

EPS = np.finfo(np.float64).eps

relative_step = {"2-point": EPS**0.5,
                 "3-point": EPS**(1/3),
                 "cs": EPS**0.5}

class Rosenbrock:
    def __init__(self, n=2, random_state=0):
        rng = np.random.RandomState(random_state)
        self.x0 = rng.uniform(-1, 1, n)
        self.x_opt = np.ones(n)

    def fun(self, x):
        x = np.asarray(x)
        r = np.sum(100.0 * (x[1:] - x[:-1]**2.0)**2.0 + (1 - x[:-1])**2.0,
                   axis=0)
        return r

    def grad(self, x):
        x = np.asarray(x)
        xm = x[1:-1]
        xm_m1 = x[:-2]
        xm_p1 = x[2:]
        der = np.zeros_like(x)
        der[1:-1] = (200 * (xm - xm_m1**2) -
                     400 * (xm_p1 - xm**2) * xm - 2 * (1 - xm))
        der[0] = -400 * x[0] * (x[1] - x[0]**2) - 2 * (1 - x[0])
        der[-1] = 200 * (x[-1] - x[-2]**2)
        return der

    def hess(self, x):
        x = np.atleast_1d(x)
        H = np.diag(-400 * x[:-1], 1) - np.diag(400 * x[:-1], -1)
        diagonal = np.zeros(len(x), dtype=x.dtype)
        diagonal[0] = 1200 * x[0]**2 - 400 * x[1] + 2
        diagonal[-1] = 200
        diagonal[1:-1] = 202 + 1200 * x[1:-1]**2 - 400 * x[2:]
        H = H + np.diag(diagonal)
        return H

    @property
    def constr(self):
        return ()

def _compute_absolute_step(rel_step, x0, method):
    if rel_step is None:
        rel_step = relative_step[method]
    sign_x0 = (x0 >= 0).astype(float) * 2 - 1
    return rel_step * sign_x0 * np.maximum(1.0, np.abs(x0))



def group_columns(A, order=0):
    if issparse(A):
        A = csc_matrix(A)
    else:
        A = np.atleast_2d(A)
        A = (A != 0).astype(np.int32)

    if A.ndim != 2:
        raise ValueError("`A` must be 2-dimensional.")

    m, n = A.shape

    if order is None or np.isscalar(order):
        rng = np.random.RandomState(order)
        order = rng.permutation(n)
    else:
        order = np.asarray(order)
        if order.shape != (n,):
            raise ValueError("`order` has incorrect shape.")

    A = A[:, order]

    if issparse(A):
        groups = group_sparse(m, n, A.indices, A.indptr)
    else:
        groups = group_dense(m, n, A)

    groups[order] = groups.copy()

    return groups


TERMINATION_MESSAGES = {
    0: "The maximum number of function evaluations is exceeded.",
    1: "`gtol` termination condition is satisfied.",
    2: "`xtol` termination condition is satisfied.",
    3: "`callback` function requested termination"
}



def minimize_constrained(fun, x0, grad, hess='2-point', constraints=(),
                         method=None, xtol=1e-8, gtol=1e-8,
                         sparse_jacobian=None, options={},
                         callback=None, max_iter=1000,
                         verbose=0):
    # Initial value
    x0 = np.atleast_1d(x0).astype(float)
    n_vars = np.size(x0)

    # Evaluate initial point
    f0 = fun(x0)
    g0 = np.atleast_1d(grad(x0))

    # Define Gradient
    if hess in ('2-point', '3-point', 'cs'):
        # Need to memoize gradient wrapper in order
        # to avoid repeated calls that occur
        # when using finite differences.
        def grad_wrapped(x):
            return np.atleast_1d(grad(x))

    else:
        def grad_wrapped(x):
            return np.atleast_1d(grad(x))

    H0 = hess(x0)
    H0 = np.atleast_2d(np.asarray(H0))
    def hess_wrapped(x):
        return np.atleast_2d(np.asarray(hess(x)))


    # Put constraints in list format when needed
    # Copy, evaluate and initialize constraints
    copied_constraints = [deepcopy(constr) for constr in constraints]
    # Concatenate constraints
    if len(copied_constraints) == 0:
        constr = empty_canonical_constraint(x0, n_vars, sparse_jacobian)

    # Generate Lagrangian hess function
    lagr_hess = lagrangian_hessian(constr, hess_wrapped)

    # Construct OptimizeResult
    state = OptimizeResult(niter=0, nfev=1, ngev=1,
                           ncev=1, njev=1, nhev=0,
                           cg_niter=0, cg_info={})
    # Store values
    return_all = options.get("return_all", False)
    if return_all:
        state.allvecs = []
        state.allmult = []
        
    def stop_criteria(state):
        state.status = None
        if (callback is not None) and callback(state):
            state.status = 3
        elif state.optimality < gtol and state.constr_violation < gtol:
            state.status = 1
        elif state.trust_radius < xtol:
            state.status = 2
        elif state.niter > max_iter:
            state.status = 0
        return state.status in (0, 1, 2, 3)

    start_time = time.time()
    # Call inferior function to do the optimization
    if constr.n_ineq > 0:
        raise ValueError("'equality_constrained_sqp' does not "
                         "support inequality constraints.")

    def fun_and_constr(x):
        f = fun(x)
        _, c_eq = constr.constr(x)
        return f, c_eq

    def grad_and_jac(x):
        g = grad_wrapped(x)
        _, J_eq = constr.jac(x)
        return g, J_eq

    result = equality_constrained_sqp(
        fun_and_constr, grad_and_jac, lagr_hess,
        x0, f0, g0, constr.c_eq0, constr.J_eq0,
        stop_criteria, state, **options)


    result.execution_time = time.time() - start_time
    result.method = method
    result.message = TERMINATION_MESSAGES[result.status]

    return result
    
    
class CanonicalConstraint:
    def __init__(self, n_vars, n_ineq, n_eq,
                 constr, jac, hess, sparse_jacobian,
                 enforce_feasibility,
                 x0, c_ineq0, c_eq0, J_ineq0, J_eq0):
        # Dimensions
        self.n_vars = n_vars
        self.n_ineq = n_ineq
        self.n_eq = n_eq
        # Objective function and constraints
        self.constr = constr
        self.jac = jac
        self.hess = hess
        # Use sparse jacobian flag
        self.sparse_jacobian = sparse_jacobian
        # Enforce feasibility for CanonicalConstraint. Should
        # be a list of booleans (and never a single boolean value,
        # as it is allowed for Box, Linear and Nonlinear constraints).
        self.enforce_feasibility = enforce_feasibility
        # Initial Values
        self.x0 = x0
        self.c_ineq0 = c_ineq0
        self.c_eq0 = c_eq0
        self.J_ineq0 = J_ineq0
        self.J_eq0 = J_eq0



def lagrangian_hessian(constraint, hess):

    # Concatenate Hessians
    def lagr_hess(x, v_eq=np.empty(0), v_ineq=np.empty(0)):
        n = len(x)
        hess_list = []
        if hess is not None:
            hess_list += [hess(x)]
        if constraint.hess is not None:
            hess_list += [constraint.hess(x, v_eq, v_ineq)]

        def matvec(p):
            result = np.zeros_like(p)
            for h in hess_list:
                result += h.dot(p)
            return result

        return spc.linalg.LinearOperator((n, n), matvec)

    return lagr_hess


def empty_canonical_constraint(x0, n_vars, sparse_jacobian=None):
    n_eq = 0
    n_ineq = 0
    empty_c = np.empty(0)
    if sparse_jacobian or (sparse_jacobian is None):
        empty_J = spc.csr_matrix(np.empty((0, n_vars)))
    else:
        empty_J = np.empty((0, n_vars))

    def constr(x):
        return empty_c, empty_c

    def jac(x):
        return empty_J, empty_J

    enforce_feasibility = np.empty(0, dtype=bool)
    return CanonicalConstraint(n_vars, n_ineq, n_eq,
                               constr, jac, None,
                               True, enforce_feasibility,
                               x0, empty_c, empty_c,
                               empty_J, empty_J)



def _linear_to_canonical(linear):
    return _nonlinear_to_canonical(linear.to_nonlinear())


def _box_to_canonical(box):
    return _linear_to_canonical(box.to_linear())



def default_scaling(x):
    n, = np.shape(x)
    return spc.eye(n)

def equality_constrained_sqp(fun_and_constr, grad_and_jac, lagr_hess,
                             x0, fun0, grad0, constr0,
                             jac0, stop_criteria, state,
                             trust_lb=None,
                             trust_ub=None,
                             initial_penalty=1.0,
                             initial_trust_radius=1.0,
                             scaling=default_scaling,
                             return_all=False,
                             factorization_method=None):

    PENALTY_FACTOR = 0.3  # Rho from formula (3.51), reference [2]_, p.891.
    LARGE_REDUCTION_RATIO = 0.9
    INTERMEDIARY_REDUCTION_RATIO = 0.3
    SUFFICIENT_REDUCTION_RATIO = 1e-8  # Eta from reference [2]_, p.892.
    TRUST_ENLARGEMENT_FACTOR_L = 7.0
    TRUST_ENLARGEMENT_FACTOR_S = 2.0
    MAX_TRUST_REDUCTION = 0.5
    MIN_TRUST_REDUCTION = 0.1
    SOC_THRESHOLD = 0.1
    TR_FACTOR = 0.8  # Zeta from formula (3.21), reference [2]_, p.885.
    BOX_FACTOR = 0.5

    n, = np.shape(x0)  # Number of parameters

    # Set default lower and upper bounds.
    if trust_lb is None:
        trust_lb = np.full(n, -np.inf)
    if trust_ub is None:
        trust_ub = np.full(n, np.inf)

    # Initial values
    x = np.copy(x0)
    trust_radius = initial_trust_radius
    penalty = initial_penalty
    # Compute Values
    f = fun0
    c = grad0
    b = constr0
    A = jac0
    S = scaling(x)
    # Get projections
    Z, LS, Y = projections(A, factorization_method)
    # Compute least-square lagrange multipliers
    v = -LS.dot(c)

    # Update state parameters
    state.optimality = norm(c + A.T.dot(v), np.inf)
    state.constr_violation = norm(b, np.inf) if len(b) > 0 else 0
    state.niter += 1
    state.x = x
    state.v = v
    state.fun = f
    state.grad = c
    state.constr = b
    state.jac = A
    state.trust_radius = trust_radius
    state.penalty = penalty
    if return_all:
        state.allvecs += [np.copy(x)]
        state.allmult += [np.copy(v)]

    compute_hess = True
    while not stop_criteria(state):
        # Compute Lagrangian Hessian
        if compute_hess:
            H = lagr_hess(x, v)
            state.nhev += 1

        # Normal Step - `dn`
        # minimize 1/2*||A dn + b||^2
        # subject to:
        # ||dn|| <= TR_FACTOR * trust_radius
        # BOX_FACTOR * lb <= dn <= BOX_FACTOR * ub.
        dn = modified_dogleg(A, Y, b,
                             TR_FACTOR*trust_radius,
                             BOX_FACTOR*trust_lb,
                             BOX_FACTOR*trust_ub)

        # Tangential Step - `dn`
        # Solve the QP problem:
        # minimize 1/2 dt.T H dt + dt.T (H dn + c)
        # subject to:
        # A dt = 0
        # ||dt|| <= sqrt(trust_radius**2 - ||dn||**2)
        # lb - dn <= dt <= ub - dn
        c_t = H.dot(dn) + c
        b_t = np.zeros_like(b)
        trust_radius_t = np.sqrt(trust_radius**2 - np.linalg.norm(dn)**2)
        lb_t = trust_lb - dn
        ub_t = trust_ub - dn
        dt, info_cg = projected_cg(H, c_t, Z, Y, b_t,
                                   trust_radius_t,
                                   lb_t, ub_t)

        # Compute update (normal + tangential steps).
        d = dn + dt

        # Compute second order model: 1/2 d H d + c.T d + f.
        quadratic_model = 1/2*(H.dot(d)).dot(d) + c.T.dot(d)
        # Compute linearized constraint: l = A d + b.
        linearized_constr = A.dot(d)+b
        # Compute new penalty parameter according to formula (3.52),
        # reference [2]_, p.891.
        vpred = norm(b) - norm(linearized_constr)
        # Guarantee `vpred` always positive,
        # regardless of roundoff errors.
        vpred = max(1e-16, vpred)
        previous_penalty = penalty
        if quadratic_model > 0:
            new_penalty = quadratic_model / ((1-PENALTY_FACTOR)*vpred)
            penalty = max(penalty, new_penalty)
        # Compute predicted reduction according to formula (3.52),
        # reference [2]_, p.891.
        predicted_reduction = -quadratic_model + penalty*vpred

        # Compute merit function at current point
        merit_function = f + penalty*norm(b)
        # Evaluate function and constraints at trial point
        x_next = x + S.dot(d)
        f_next, b_next = fun_and_constr(x_next)
        # Increment funcion evaluation counter
        state.nfev += 1
        state.ncev += 1
        # Compute merit function at trial point
        merit_function_next = f_next + penalty*norm(b_next)
        # Compute actual reduction according to formula (3.54),
        # reference [2]_, p.892.
        actual_reduction = merit_function - merit_function_next
        # Compute reduction ratio
        reduction_ratio = actual_reduction / predicted_reduction

        # Second order correction (SOC), reference [2]_, p.892.
        if reduction_ratio < SUFFICIENT_REDUCTION_RATIO and \
           norm(dn) <= SOC_THRESHOLD * norm(dt):
            # Compute second order correction
            y = -Y.dot(b_next)
            # Make sure increment is inside box constraints
            _, t, intersect = box_intersections(d, y, trust_lb, trust_ub)
            # Compute tentative point
            x_soc = x + S.dot(d + t*y)
            f_soc, b_soc = fun_and_constr(x_soc)
            # Increment funcion evaluation counter
            state.nfev += 1
            state.ncev += 1
            # Recompute actual reduction
            merit_function_soc = f_soc + penalty*norm(b_soc)
            actual_reduction_soc = merit_function - merit_function_soc
            # Recompute reduction ratio
            reduction_ratio_soc = actual_reduction_soc / predicted_reduction
            if intersect and reduction_ratio_soc >= SUFFICIENT_REDUCTION_RATIO:
                x_next = x_soc
                f_next = f_soc
                b_next = b_soc
                reduction_ratio = reduction_ratio_soc

        # Readjust trust region step, formula (3.55), reference [2]_, p.892.
        if reduction_ratio >= LARGE_REDUCTION_RATIO:
            trust_radius = max(TRUST_ENLARGEMENT_FACTOR_L * norm(d),
                               trust_radius)
        elif reduction_ratio >= INTERMEDIARY_REDUCTION_RATIO:
            trust_radius = max(TRUST_ENLARGEMENT_FACTOR_S * norm(d),
                               trust_radius)
        # Reduce trust region step, according to reference [3]_, p.696.
        elif reduction_ratio < SUFFICIENT_REDUCTION_RATIO:
                trust_reduction \
                    = (1-SUFFICIENT_REDUCTION_RATIO)/(1-reduction_ratio)
                new_trust_radius = trust_reduction * norm(d)
                if new_trust_radius >= MAX_TRUST_REDUCTION * trust_radius:
                    trust_radius *= MAX_TRUST_REDUCTION
                elif new_trust_radius >= MIN_TRUST_REDUCTION * trust_radius:
                    trust_radius = new_trust_radius
                else:
                    trust_radius *= MIN_TRUST_REDUCTION

        # Update iteration
        state.niter += 1
        if reduction_ratio >= SUFFICIENT_REDUCTION_RATIO:
            x = x_next
            f, b = f_next, b_next
            c, A = grad_and_jac(x)
            S = scaling(x)
            # Increment funcion evaluation counter
            state.ngev += 1
            state.njev += 1
            # Get projections
            Z, LS, Y = projections(A)
            # Compute least-square lagrange multipliers
            v = -LS.dot(c)
            # Set Flag
            compute_hess = True
            # Store state
            state.x = x
            state.v = v
            state.fun = f
            state.grad = c
            state.constr = b
            state.jac = A
            # Otimality values
            state.optimality = norm(c + A.T.dot(v), np.inf)
            state.constr_violation = norm(b, np.inf) if len(b) > 0 else 0
        else:
            penalty = previous_penalty
            compute_hess = False
        # Store values
        state.trust_radius = trust_radius
        state.penalty = penalty
        state.cg_niter += info_cg["niter"]
        state.cg_info = info_cg
        if return_all:
            state.allvecs.append(np.copy(x))
            state.allmult.append(np.copy(v))

    return state
    
def orthogonality(A, g):
    # Compute vector norms
    norm_g = np.linalg.norm(g)
    # Compute Frobenius norm of the matrix A
    if issparse(A):
        norm_A = scipy.sparse.linalg.norm(A, ord='fro')
    else:
        norm_A = np.linalg.norm(A, ord='fro')

    # Check if norms are zero
    if norm_g == 0 or norm_A == 0:
        return 0

    norm_A_g = np.linalg.norm(A.dot(g))
    # Orthogonality measure
    orth = norm_A_g / (norm_A*norm_g)
    return orth

    # z = inv(A A.T) A x
    def least_squares(x):
        return factor(A.dot(x))

    # z = A.T inv(A A.T) x
    def row_space(x):
        return A.T.dot(factor(x))

    return null_space, least_squares, row_space


def augmented_system_projections(A, m, n, orth_tol, max_refin, tol):
    """Return linear operators for matrix A - ``AugmentedSystem``."""
    # Form augmented system
    K = csc_matrix(bmat([[eye(n), A.T], [A, None]]))
    # LU factorization
    # TODO: Use a symmetric indefinite factorization
    #       to solve the system twice as fast (because
    #       of the symmetry).
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
        # return z = inv(A A.T) A x
        return lu_sol[n:m+n]

    def row_space(x):
        v = np.hstack([np.zeros(n), x])
        lu_sol = solve(v)
        return lu_sol[:n]

    return null_space, least_squares, row_space



def projections(A, method=None, orth_tol=1e-12, max_refin=3, tol=1e-15):
    m, n = np.shape(A)

    # The factorization of an empty matrix
    # only works for the sparse representation.
    if m*n == 0:
        A = csc_matrix(A)

    # Check Argument
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

    null_space, least_squares, row_space \
        = augmented_system_projections(A, m, n, orth_tol, max_refin, tol)

    Z = LinearOperator((n, n), null_space)
    LS = LinearOperator((m, n), least_squares)
    Y = LinearOperator((n, m), row_space)

    return Z, LS, Y


def sphere_intersections(z, d, trust_radius,
                         entire_line=False):

    # Special case when d=0
    if norm(d) == 0:
        return 0, 0, False
    # Check for inf trust_radius
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

    # The following calculation is mathematically
    # equivalent to:
    # ta = (-b - sqrt_discriminant) / (2*a)
    # tb = (-b + sqrt_discriminant) / (2*a)
    # but produce smaller round off errors.
    # Look at Matrix Computation p.97
    # for a better justification.
    aux = b + copysign(sqrt_discriminant, b)
    ta = -aux / (2*a)
    tb = -2*c / aux
    ta, tb = sorted([ta, tb])

    if entire_line:
        intersect = True
    else:
        # Checks to see if intersection happens
        # within vectors length.
        if tb < 0 or ta > 1:
            intersect = False
            ta = 0
            tb = 0
        else:
            intersect = True
            # Restrict intersection interval
            # between 0 and 1.
            ta = max(0, ta)
            tb = min(1, tb)

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

    # Get values for which d==0
    zero_d = (d == 0)
    # If the boundaries are not satisfied for some coordinate
    # for which "d" is zero, there is no box-line intersection.
    if (z[zero_d] < lb[zero_d]).any() or (z[zero_d] > ub[zero_d]).any():
        intersect = False
        return 0, 0, intersect
    # Remove values for which d is zero
    not_zero_d = np.logical_not(zero_d)
    z = z[not_zero_d]
    d = d[not_zero_d]
    lb = lb[not_zero_d]
    ub = ub[not_zero_d]

    # Find a series of intervals (t_lb[i], t_ub[i]).
    t_lb = (lb-z) / d
    t_ub = (ub-z) / d
    # Get the intersection of all those intervals.
    ta = max(np.minimum(t_lb, t_ub))
    tb = min(np.maximum(t_lb, t_ub))

    # Check if intersection is feasible
    if ta <= tb:
        intersect = True
    else:
        intersect = False
    # Checks to see if intersection happens within vectors length.
    if not entire_line:
        if tb < 0 or ta > 1:
            intersect = False
            ta = 0
            tb = 0
        else:
            # Restrict intersection interval between 0 and 1.
            ta = max(0, ta)
            tb = min(1, tb)

    return ta, tb, intersect


def box_sphere_intersections(z, d, lb, ub, trust_radius,
                             entire_line=False,
                             extra_info=False):

    ta_b, tb_b, intersect_b = box_intersections(z, d, lb, ub, # 
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


def inside_box_boundaries(x, lb, ub):
    """Check if lb <= x <= ub."""
    return (lb <= x).all() and (x <= ub).all()

def reinforce_box_boundaries(x, lb, ub):
    """Return clipped value of x"""
    return np.minimum(np.maximum(x, lb), ub)


def reinforce_box_boundaries(x, lb, ub):
    """Return clipped value of x"""
    return np.minimum(np.maximum(x, lb), ub)


def modified_dogleg(A, Y, b, trust_radius, lb, ub):
    # Compute minimum norm minimizer of 1/2*|| A x + b ||^2.
    newton_point = -Y.dot(b)
    # Check for interior point
    if inside_box_boundaries(newton_point, lb, ub)  \
       and norm(newton_point) <= trust_radius:
        x = newton_point
        return x

    # Compute gradient vector ``g = A.T b``
    g = A.T.dot(b)
    # Compute cauchy point
    # `cauchy_point = g.T g / (g.T A.T A g)``.
    A_g = A.dot(g)
    cauchy_point = -np.dot(g, g) / np.dot(A_g, A_g) * g
    # Origin
    origin_point = np.zeros_like(cauchy_point)

    # Check the segment between cauchy_point and newton_point
    # for a possible solution.
    z = cauchy_point
    p = newton_point - cauchy_point
    _, alpha, intersect = box_sphere_intersections(z, p, lb, ub,
                                                   trust_radius)
    if intersect:
        x1 = z + alpha*p
    else:
        # Check the segment between the origin and cauchy_point
        # for a possible solution.
        z = origin_point
        p = cauchy_point
        _, alpha, _ = box_sphere_intersections(z, p, lb, ub,
                                               trust_radius)
        x1 = z + alpha*p

    # Check the segment between origin and newton_point
    # for a possible solution.
    z = origin_point
    p = newton_point
    _, alpha, _ = box_sphere_intersections(z, p, lb, ub,
                                           trust_radius)
    x2 = z + alpha*p

    # Return the best solution among x1 and x2.
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

    # Initial Values
    x = Y.dot(-b)
    r = Z.dot(H.dot(x) + c)
    g = Z.dot(r)
    p = -g

    # Store ``x`` value
    if return_all:
        allvecs = [x]
    # Values for the first iteration
    H_p = H.dot(p)
    rt_g = norm(g)**2  # g.T g = r.T Z g = r.T g (ref [1]_ p.1389)

    # If x > trust-region the problem does not have a solution.
    tr_distance = trust_radius - norm(x)
    if tr_distance < 0:
        raise ValueError("Trust region problem does not have a solution.")
    # If x == trust_radius, then x is the solution
    # to the optimization problem, since x is the
    # minimum norm solution to Ax=b.
    elif tr_distance < CLOSE_TO_ZERO:
        info = {'niter': 0, 'stop_cond': 2, 'hits_boundary': True}
        if return_all:
            allvecs.append(x)
            info['allvecs'] = allvecs
        return x, info

    # Set default tolerance
    if tol is None:
        tol = max(min(0.01 * np.sqrt(rt_g), 0.1 * rt_g), CLOSE_TO_ZERO)
    # Set default lower and upper bounds
    if lb is None:
        lb = np.full(n, -np.inf)
    if ub is None:
        ub = np.full(n, np.inf)
    # Set maximum iterations
    if max_iter is None:
        max_iter = n-m
    max_iter = min(max_iter, n-m)
    # Set maximum infeasible iterations
    if max_infeasible_iter is None:
        max_infeasible_iter = n-m

    hits_boundary = False
    stop_cond = 1
    counter = 0
    last_feasible_x = np.empty_like(x)
    k = 0
    for i in range(max_iter):
        # Stop criteria - Tolerance : r.T g < tol
        if rt_g < tol:
            stop_cond = 4
            break
        k += 1
        # Compute curvature
        pt_H_p = H_p.dot(p)
        # Stop criteria - Negative curvature
        if pt_H_p <= 0:
            if np.isinf(trust_radius):
                    raise ValueError("Negative curvature not "
                                     "allowed for unrestrited "
                                     "problems.")
            else:
                # Find intersection with constraints
                _, alpha, intersect = box_sphere_intersections(
                    x, p, lb, ub, trust_radius, entire_line=True)
                # Update solution
                if intersect:
                    x = x + alpha*p
                # Reinforce variables are inside box constraints.
                # This is only necessary because of roundoff errors.
                x = reinforce_box_boundaries(x, lb, ub)
                # Atribute information
                stop_cond = 3
                hits_boundary = True
                break

        # Get next step
        alpha = rt_g / pt_H_p
        x_next = x + alpha*p

        # Stop criteria - Hits boundary
        if np.linalg.norm(x_next) >= trust_radius:
            # Find intersection with box constraints
            _, theta, intersect = box_sphere_intersections(x, alpha*p, lb, ub,
                                                           trust_radius)
            # Update solution
            if intersect:
                x = x + theta*alpha*p
            # Reinforce variables are inside box constraints.
            # This is only necessary because of roundoff errors.
            x = reinforce_box_boundaries(x, lb, ub)
            # Atribute information
            stop_cond = 2
            hits_boundary = True
            break

        # Check if ``x`` is inside the box and start counter if it is not.
        if inside_box_boundaries(x_next, lb, ub):
            counter = 0
        else:
            counter += 1
        # Whenever outside box constraints keep looking for intersections.
        if counter > 0:
            _, theta, intersect = box_sphere_intersections(x, alpha*p, lb, ub,
                                                           trust_radius)
            if intersect:
                last_feasible_x = x + theta*alpha*p
                # Reinforce variables are inside box constraints.
                # This is only necessary because of roundoff errors.
                last_feasible_x = reinforce_box_boundaries(last_feasible_x,
                                                           lb, ub)
                counter = 0
        # Stop after too many infeasible (regarding box constraints) iteration.
        if counter > max_infeasible_iter:
            break
        # Store ``x_next`` value
        if return_all:
            allvecs.append(x_next)

        # Update residual
        r_next = r + alpha*H_p
        # Project residual g+ = Z r+
        g_next = Z.dot(r_next)
        # Compute conjugate direction step d
        rt_g_next = norm(g_next)**2  # g.T g = r.T g (ref [1]_ p.1389)
        beta = rt_g_next / rt_g
        p = - g_next + beta*p
        # Prepare for next iteration
        x = x_next
        g = g_next
        r = g_next
        rt_g = norm(g)**2  # g.T g = r.T Z g = r.T g (ref [1]_ p.1389)
        H_p = H.dot(p)

    if not inside_box_boundaries(x, lb, ub):
        x = last_feasible_x
        hits_boundary = True
    info = {'niter': k, 'stop_cond': stop_cond,
            'hits_boundary': hits_boundary}
    if return_all:
        info['allvecs'] = allvecs
    return x, info


if __name__ == "__main__":
    prob = Rosenbrock()
    result = minimize_constrained(prob.fun, prob.x0,
                                  prob.grad, prob.hess,
                                  prob.constr)
 
    print (result)
