#+LaTeX_HEADER: \newcommand{\ud}{\,\mathrm{d}}
#+LaTeX_HEADER: \newcommand{\mlabel}[1]{\quad \text{(#1)}\quad}
#+LaTeX_HEADER: \usepackage{palatino,eulervm}
#+LaTeX_HEADER: \usepackage{cancel}

Eşitsizlik Sınırlamaları 

Optimizasyon problemimizde 

$$
\min_x f(x), 
\quad 
\textrm{oyle ki}, 
\quad 
c_i(x) \ge 0, 
\quad i=1,2,..,m
$$

$c_i$ ile gösterilen eşitsizlik içeren (üstte büyüklük türünden)
kısıtlamalar olduğunu düşünelim. Bu problemi nasıl çözeriz?

Bir fikir, problemin eşitizliklerini bir gösterge (indicator)
fonksiyonu üzerinden, Lagrange yönteminde olduğu gibi, ana hedef
fonksiyonuna dahil etmek, ve elde edilen yeni hedefi kısıtlanmamış bir
problem gibi çözmek. Yani üstteki yerine, alttaki problemi çözmek,

$$
\min_x f(x) + \sum_{i=1}^{m} I(c_i(x))
$$

ki $I$ pozitif reel fonksiyonlar için göstergeç fonksiyonu,

$$
I(u) = 
\left\{ \begin{array}{ll}
0 & u \le 0 \\
\infty & u > 0
\end{array} \right.
$$

Bu yaklaşımın nasıl işleyeceğini kabaca tahmin edebiliriz. $I$
fonksiyonu 0'dan büyük değerler için müthiş büyük değerler veriyor, bu
sebeple optimizasyon sırasında o değerlerden tabii ki kaçınılacak, ve
arayış istediğimiz noktalara doğru kayacak. Tabii $x_1 > 3$ gibi bir
şart varsa onu $x_1 - 3 > 0$ şartına değiştiriyoruz ki üstteki
göstergeci kullanabilelim. Bu yaklaşıma "bariyer metotu" ismi
veriliyor çünkü $I$ ile bir bariyer yaratılmış oluyor.

Fakat bir problem var, göstergeç fonksiyonunun türevini almak, ve
pürüzsüz rahat kullanılabilen bir yeni fonksiyon elde etmek kolay
değil. Acaba $I$ yerine onu yaklaşık temsil edebilen bir başka sürekli
fonksiyon kullanamaz mıyız?

Log fonksiyonunu kullanabiliriz. Altta farklı $\mu$ değerleri için
$-\mu \log(-u)$ fonksiyonun değerlerini görüyoruz. Fonksiyon görüldüğü
gibi $I$'ya oldukca yakın.

```python
def I(u): 
   if u<0: return 0.
   else: return 10.0

u = np.linspace(-3,1,100)
Is = np.array([I(x) for x in u])

import pandas as pd
df = pd.DataFrame(index=u)

df['I'] = Is
df['$\mu$=0.5'] = -0.5*np.log(-u)
df['$\mu$=1.0'] = -1.0*np.log(-u)
df['$\mu$=2.0'] = -2.0*np.log(-u)

df.plot()
plt.savefig('func_40_autograd_04.png')
```

\includegraphics[width=25em]{func_40_autograd_04.png}

O zaman eldeki tüm $c_i(x) \ge 0$ kısıtlamalarını

$$
- \sum_{i=1}^{m} \log c_i(x)
$$

ile hedef fonksiyonuna dahil edebiliriz, yeni birleşik fonksiyon,

$$
P(x;\mu) = f(x) - \mu \sum_{i=1}^{m} \log c_i(x) 
$$

olur. Böylece elde edilen yaklaşım log-bariyer yaklaşımı olacaktır. 

Algoritma olarak optimizasyon şu şekilde gider;

1) Bir $x$ ve $\mu$ değerinden başla.

2) Newton metotu ile birkaç adım at (durma kriteri yaklaşıma göre değisebilir)

3) $\mu$'yu küçült

4) Ana durma kriterine bak, tamamsa dur. Yoksa başa dön

Bu yaklaşımın dışbükey (convex) problemler için global minimuma
gittiği ispatlanmıştır [8, sf. 504].

Örnek

$\min (x_1 + 0.5)^2 + (x_2 - 0.5)^2$ problemini çöz, $x_1 \in [0,1]$ ve $x_2 \in
[0,1]$ kriterine göre.

Üstteki fonksiyon için log-bariyer,

$$
P(x;\mu) = (x_1 + 0.5)^2 + (x_2-0.5)^2 -
\mu 
\big[
\log x_1 + \log (1-x_1) + \log x_2 + \log (1-x_2)
\big]
$$

Bu formülasyonu nasıl elde ettiğimiz bariz herhalde, $x_1 \ge 0$ ve
$x_1 \le 1$ kısıtlamaları var mesela, ikinci ifadeyi büyüktür
işaretine çevirmek için eksi ile çarptık, $-x_1 \ge 1$, ya da $1-x_1
\ge 0$
böylece $\log(1-x_1)$ oldu.

Artık Newton yöntemini kullanarak sanki elimizde bir kısıtlanması
olmayan fonksiyon varmış gibi kodlama yapabiliriz, $P$'yi minimize
edebiliriz. Newton yönü $d$ için gereken Hessian ve Jacobian
matrislerini otomatik türevle hesaplayacağız, belli bir noktadan
başlayacağız, ve her adımda $d = -H(x)^{-1} \nabla f(x)$ yönünde adım
atacağız.

```python
from autograd import numpy as anp, grad, hessian, jacobian
import numpy.linalg as lin

x = np.array([0.8,0.2])
mu = 2.0
for i in range(10):
    def P(x):
    	x1,x2=x[0],x[1]
    	return (x1+0.5)**2 + (x2-0.5)**2 - mu * \
	   (anp.log(x1) + anp.log(1-x1) + anp.log(x2)+anp.log(1-x2))

    h = hessian(P)
    j = jacobian(P)
    J = j(np.array(x))
    H = h(np.array(x))
    d = np.dot(-lin.inv(H), J)
    x = x + d
    print (i, x, np.round(mu,5))
    mu = mu*0.1
```

```text
0 [0.61678005 0.34693878] 2.0
1 [-0.00858974  0.486471  ] 0.2
2 [-0.02078755  0.49999853] 0.02
3 [-0.18014768  0.5       ] 0.002
4 [-0.49963245  0.5       ] 0.0002
5 [-0.50002667  0.5       ] 2e-05
6 [-0.50000267  0.5       ] 0.0
7 [-0.50000027  0.5       ] 0.0
8 [-0.50000003  0.5       ] 0.0
9 [-0.5  0.5] 0.0
```

Görüldüğü gibi 5. adımda optimal noktaya gelindi, o noktada $\mu$
oldukca küçük, ve bariyerle tanımladığımız yerlerden uzak duruldu,
optimal nokta $x_1=-0.5,x_2=0.5$ bulundu.










[devam edecek]














































