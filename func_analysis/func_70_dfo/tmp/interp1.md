#+LaTeX_HEADER: \newcommand{\ud}{\,\mathrm{d}}
#+LaTeX_HEADER: \newcommand{\mlabel}[1]{\quad \text{(#1)}\quad}
#+LaTeX_HEADER: \usepackage{palatino,eulervm}
#+LaTeX_HEADER: \usepackage{cancel}

```python
from scipy.interpolate import Rbf
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
from matplotlib import cm
import numpy as np
import autograd.numpy as anp
import autograd

def random_ball(num_points, dimension, radius=1):
    from numpy import random, linalg
    random_directions = random.normal(size=(dimension,num_points))
    random_directions /= linalg.norm(random_directions, axis=0)
    random_radii = random.random(num_points) ** (1/dimension)
    return radius * (random_directions * random_radii).T

np.random.seed(0)
N = 20

def rosenbrock(x):
    return (1 + x[0])**2 + 100*(x[1] - x[0]**2)**2

def Rosenbrock(x,y):
    return (1 + x)**2 + 100*(y - x**2)**2

def get_fvals_in_region(xcurr, f, radius):    
    b = random_ball(N, 2, radius)
    pts = xcurr+b
    vals = [f(p) for p in pts]
    return xcurr+b, np.array(vals)

x0 = [1.5,0]
xs,vs = get_fvals_in_region(x0, rosenbrock, 0.5)

res = []
for i in range(vs.shape[0]):
    res.append((xs[i,0],xs[i,1],vs[i]))
res = np.array(res).reshape(vs.shape[0], 3)
```

```python
import itertools
import numpy.linalg as lin

def quad_interpolate(xi, yi):
    xi = np.hstack((xi, np.ones((1,len(xi))).T  ))
    #print (xi)
    D = xi.shape[1]
    print (D)
    X_train = []
    for row in xi:
        X_train.append([row[i]*row[j] for i,j in itertools.product(range(D),range(D)) ])
    X_train = np.array(X_train)
    print (X_train.shape)
    print (yi.shape)
    coef,_,_,_ = lin.lstsq(X_train, yi)
    return coef

xi = res[:,[0,1]]
yi = res[:,[2]]
coef = quad_interpolate(xi,yi)
```

```text
3
(20, 9)
(20, 1)
```

```python
x = np.linspace(-2,2,250)
y = np.linspace(-1,3,250)
X, Y = np.meshgrid(x, y)
Z = Rosenbrock(X, Y)

fig = plt.figure(figsize = (8,4))
ax = fig.gca(projection='3d')
ax.plot3D(res[:,0],res[:,1],res[:,2],'r.')
ax.plot_surface(X,Y,Z,rstride = 5, cstride = 5, cmap = 'jet', alpha = .4, edgecolor = 'none' )

def q_interp(x1,x2):
    x = np.array([[x1,x2,1]])
    A = coef.reshape(3,3)
    res = np.dot(np.dot(x,A),x.T)
    return np.float(res)

Zi = np.array([q_interp(xx,yy) for xx,yy in zip(X.flatten(),Y.flatten())])
Zi = Zi.reshape(X.shape)
ax.plot_wireframe(X,Y,Zi)

ax.set_zlim(0,2500)
SCALE = 2
ax.quiver(x0[0], x0[1], 0, g[0]*SCALE, g[1]*SCALE, 1, color='red')
ax.plot3D([x0[0]], [x0[1]], [0.0], 'b.')

ax.view_init(21, -133)
plt.savefig('/tmp/inter_01.png')
```

```python
#print (coef.reshape(3,3))
coefs = coef.reshape(3,3)
#print (coefs)
#print (coefs[:2,:2])

g = - (2 * np.dot(coefs[:2,:2],np.array(x0).reshape(2,1)))

g = g / np.sum(g)

print (g)

```

```text
[[ 1.27231897]
 [-0.27231897]]
```
















```python
def f(x1,x2):
    x = np.array([[x1,x2]])
    A = np.array([[2,3],[4,3]])
    b = np.array( [[1,1]] )
    a = 4
    res = np.dot(np.dot(x,A),x.T) + np.dot(b,x.T) + a
    return np.float(res)
    
x = np.linspace(-2,2,250)
y = np.linspace(-2,2,250)
X, Y = np.meshgrid(x, y)
Z = np.array([f(xx,yy) for xx,yy in zip(X.flatten(),Y.flatten())])
Z = Z.reshape(X.shape)

from mpl_toolkits.mplot3d import Axes3D
fig = plt.figure(figsize = (8,4))
ax = fig.gca(projection='3d')
ax.set_zlim(0,50)
ax.plot_surface(X,Y,Z,rstride = 5, cstride = 5, cmap = 'jet', alpha = .4, edgecolor = 'none' )
plt.savefig('/tmp/inter_01.png')
```







