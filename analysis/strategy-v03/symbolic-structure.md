# measured-v03 符号侧完整静态与拟合记录审查

审查日期：2026-10-22。覆盖全部16份符号终稿与4个起点，不只挑选获胜样本。只读取源码、AST和已保存拟合回执；本次模型调用、候选执行、拟合、CSV读取、封存读取均为0。

## 核心结果

- 20份既有拟合记录：18有数值、2份optimization_failed。16终稿中7份在宿主浮点参数契约下保持起点函数，9份更换函数/表示；其中5份去文档字符串后的AST与起点相同（含1份字节相同）。
- 相对各自起点：6份训练NMSE改善、1份退化、7份相同、2份无可用NMSE。8个fixed/updated配对中4个数值正向差异全部伴随声明参数增加；2个持平、2个因失败不可数值比较。r1后续两对使用同S0，不能归因策略更新。
- 声明参数数并非独立有效系数数：stressstrain起点7参数仅4个多项式系数；r1 fixed8参数仅6个系数。源码docstring多处错误，不能作为结构标签。
- 宿主实际调用 least_squares(residual, params, max_nfev=100)，没有系数bounds参数。r2选择S1的16参数拟合含绝对值22914.17系数；“有界”只能描述请求/资源/评估次数边界。

## 全部记录

|记录|参数|NMSE / 失败|nfev / candidate_calls|源码/表示判定|
|---|---:|---|---|---|
|S-bact-eval-1|7|0.8503733599018976|5 / 34|linear_core_with_identity_guard|
|S-select-1|15|0.1533855701895147|30 / 421|nonlinear|
|S-select-2|8|0.1906789858240599|29 / 182|nonlinear|
|S-stress-eval-1|7|0.34361657358684433|21 / 106|nonlinear_redundant|
|r1-evaluation-S-bact-eval-1-fixed|8|0.8599611404838751|4 / 37|representation_and_count_changed|
|r1-evaluation-S-bact-eval-1-updated|12|0.8043228059470892|13 / 134|representation_and_count_changed|
|r1-evaluation-S-stress-eval-1-fixed|8|0.21437303407759964|32 / 201|representation_and_count_changed|
|r1-evaluation-S-stress-eval-1-updated|6|optimization_failed|未保存|constrained_reparameterization|
|r1-selection-S-select-1-fixed|15|0.1533855701895147|30 / 421|docstring_only|
|r1-selection-S-select-1-updated|15|optimization_failed|未保存|representation_changed_same_count|
|r1-selection-S-select-2-fixed|8|0.1906789858240599|29 / 182|equivalent_on_host_float_params|
|r1-selection-S-select-2-updated|14|0.14318745181009088|26 / 377|nested_expansion|
|r2-evaluation-S-bact-eval-1-fixed|14|0.844801449043118|4 / 61|nested_expansion|
|r2-evaluation-S-bact-eval-1-updated|15|0.7280577515442443|4 / 65|representation_and_count_changed|
|r2-evaluation-S-stress-eval-1-fixed|7|0.34361657358684433|21 / 106|byte_identical|
|r2-evaluation-S-stress-eval-1-updated|7|0.34361657358684433|21 / 106|algebraic_identity|
|r2-selection-S-select-1-fixed|15|0.1533855701895147|30 / 421|docstring_only|
|r2-selection-S-select-1-updated|16|0.14774482274486497|21 / 262|representation_and_count_changed|
|r2-selection-S-select-2-fixed|8|0.1906789858240599|29 / 182|docstring_only|
|r2-selection-S-select-2-updated|8|0.1906789858240599|29 / 182|docstring_only|

## 逐份可核验分类

源码SHA使用原UTF-8字节；全部引用路径相对于项目根目录。JSON同时保存完整AST/去docstring AST哈希、拟合参数、原始回执路径和证据文件哈希。

### S-bact-eval-1

7个独立系数的固定基：1,u0,u1,u2,u0*u1,u2*u3,u0*u1*u2。有限实数下clip(out/(1+abs(out)),-1,1)*(1+abs(out))为恒等式；浮点并不保证逐位不变。没有u3线性项但并非完全没有u3。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/executions/db526da7c87f4329b112b02c00547836/source.py`
- SHA-256：`93e698f8e8b01a0a2c508955b42ee162b194181878b7cdfae48d562a4448c19e`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/db526da7c87f4329b112b02c00547836/result.json`
- 参数结构：`linear_core_with_identity_guard`；声明参数：7。

### S-select-1

15参数：10个常数/线性/二次项、1个三变量乘积、p11*tanh(p12*u1)、p13*tanh(p14*u0)*u2。p12/p14在非线性函数内部；不可称线性参数模型。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/executions/17ddebf161b94d649007d202d250e608/source.py`
- SHA-256：`4e741492c3ae7fa2836bc3080dd0657c98296e11dd8db880867bf00798494ff2`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/17ddebf161b94d649007d202d250e608/result.json`
- 参数结构：`nonlinear`；声明参数：15。

### S-select-2

8参数：五项core乘三个(1+ci*ui)因子；展开后含多个参数的乘积。线性core不等于整个函数对参数线性。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/executions/b579685e1f1140c7856cef1ce2dbf07e/source.py`
- SHA-256：`7ef02e17a7c07f2ec7ecd1b252261144f7836abb9e89bca2d4fae344cdd0b3f0`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/b579685e1f1140c7856cef1ce2dbf07e/result.json`
- 参数结构：`nonlinear`；声明参数：8。

### S-stress-eval-1

7声明参数只产生四个有效多项式系数：A=g*c01*l0*l1,B=g*q0*l0^2,C=g*q1*l1^2,D=b，输出A*u0*u1+B*u0^2+C*u1^2+D。声明数不是有效维数；在无系数界下可选g=l0=l1=1覆盖全部四系数。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/executions/75b9afdde6df4678a79da87c906e1c5f/source.py`
- SHA-256：`58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/75b9afdde6df4678a79da87c906e1c5f/result.json`
- 参数结构：`nonlinear_redundant`；声明参数：7。

### r1-evaluation-S-bact-eval-1-fixed

7→8；加u3线性项及u1u2项，同时删掉旧u0u1u2项。基函数非嵌套；8系数线性核，移除旧恒等式guard。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-bact-eval-1-fixed/source.py`
- SHA-256：`ed997a93fc95f08d6d991974138eb68eeb17e2edc59862b19db6b4ec53141492`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/93f1c66244c749d0805dcec259260b0e/result.json`
- 参数结构：`linear_core`；声明参数：8。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r1-evaluation-S-bact-eval-1-updated

7→12；12项线性核后有8*tanh(core/8)，输出压缩使模型对参数非线性；不是纯线性最小二乘。核为1,四个ui,u0u1,u2u3,u0u1u2,u0²,u2²,u1u3,u0u3。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-bact-eval-1-updated/source.py`
- SHA-256：`96afd970ef2268ec9983cced418b21baf6ddc084a87b3a1eb0e78f8ed6828780`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/4bd59c0c97a2469d93a1286ffa506c52/result.json`
- 参数结构：`nonlinear`；声明参数：12。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r1-evaluation-S-stress-eval-1-fixed

7→8；新增u0/u1线性项。a=(u0+u1)/2,d=(u0-u1)/2，因此s*(a²-d²)=s*u0u1，与已有交叉项重复；有效系数为6个（常数、两线性、两平方、一交叉），不是8个独立方向。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-stress-eval-1-fixed/source.py`
- SHA-256：`562e92193d076307da35b70a3f71d76023f5afdd0f2471866b73cbb83c03606d`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/9c264312f0d8457da5a5e8761f96886c/result.json`
- 参数结构：`nonlinear_redundant`；声明参数：8。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r1-evaluation-S-stress-eval-1-updated

7→6；g*(c01*l0*l1*u0u1+q0*(l0u0+l1u1)^2)+b，含参数乘积和参数平方，linear-in-parameters声明错误。同样四个多项式支撑，但两平方系数乘积非负，不能笼统说与原任意四系数族相同。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-stress-eval-1-updated/source.py`
- SHA-256：`d00a34cb574ddf84af20b402b7dd1ea36d1af9692a15eed6cdf3274ef75cb3e9`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/296141b55e8941aa86fdc6b7dcca97a0/result.json`
- 参数结构：`nonlinear_redundant`；声明参数：6。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r1-selection-S-select-1-fixed

仅改文档字符串，可执行AST与起点一致；15参数非线性tanh斜率保留。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-1-fixed/source.py`
- SHA-256：`9d2817370bbfdd521af91042018374613a65739b7eca74395a6c89a61b2630a7`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/1bdffe4f06f341eb9f44f338deb63cf5/result.json`
- 参数结构：`nonlinear`；声明参数：15。
- 相对起点：字节一致=False；去docstring AST一致=True；保存的完整fitting对象一致=True。

### r1-selection-S-select-1-updated

15参数不变，但u0*u1*u2被(u0*u1+u1*u2+u0*u2)^2替换，另一tanh项改为p13*u0*u2*tanh(p14*u2)。改变次数、基函数及优化地形；仍有两个独立tanh斜率，不是docstring所说shared slope。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-1-updated/source.py`
- SHA-256：`cf3e6bb5d584526709e550bb9142afb8e436795e2721648d6d0c5fa6186b6e80`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/c605d0d22996434c80ef1710c808cfaf/result.json`
- 参数结构：`nonlinear`；声明参数：15。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r1-selection-S-select-2-fixed

用float转换并解包代替8次索引；宿主参数本为有限浮点向量，公式和参数顺序相同。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-2-fixed/source.py`
- SHA-256：`c3dfb457e2a89d3d300e28be22dcef50cca84eaf2af63a04d4296862c3926bd2`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/97b3ddfb4ef14c89a67ca6ef99470dc8/result.json`
- 参数结构：`nonlinear`；声明参数：8。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=True。

### r1-selection-S-select-2-updated

8→14，在同样三个仿射增益因子内增加6个core特征：u0u2,u1u2,u0²,u1²,u2²,u0u1u2。令新增6系数为0恢复旧函数；docstring strictly linear in params 与公式参数乘积矛盾。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-2-updated/source.py`
- SHA-256：`6a356c6206a140f2de2f600aa0b561b622a6b9943127c02eae1a3f03b3cfead2`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/ba3515964f3648369687b16dd2136b44/result.json`
- 参数结构：`nonlinear`；声明参数：14。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r2-evaluation-S-bact-eval-1-fixed

7→14；常数+四线性+六对乘积+三个三变量乘积(u0u1u2,u0u1u3,u0u2u3)。包含旧7特征，但docstring one triple 实际是三个。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-bact-eval-1-fixed/source.py`
- SHA-256：`9c045f8b32a4dd4941a362b187cf49780a14a7b7c6b38c70bf1f5d59ed7c5c0e`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/73dc11fea9214056bb7281d0b2b30353/result.json`
- 参数结构：`linear_core`；声明参数：14。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r2-evaluation-S-bact-eval-1-updated

7→15；常数+四线性+六对乘积+四平方项。与本对fixed共享前11项，三个三变量项被四平方项替换；并非单加一个参数的嵌套扩张。out/scale*scale对实数恒等，但有浮点舍入。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-bact-eval-1-updated/source.py`
- SHA-256：`9604a6385064ef2aa3ae49128d4e2293c9ec10b8a81a0798eb86e063388f371b`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/74f9fac472b44601b893e60e048cb0e8/result.json`
- 参数结构：`linear_core_with_identity_guard`；声明参数：15。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r2-evaluation-S-stress-eval-1-fixed

字节与起点相同，7声明参数、4有效系数；完整保存拟合对象也相同。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-stress-eval-1-fixed/source.py`
- SHA-256：`58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/e8258b81dfc44a5e9bbea8b36d16b89e/result.json`
- 参数结构：`nonlinear_redundant`；声明参数：7。
- 相对起点：字节一致=True；去docstring AST一致=True；保存的完整fitting对象一致=True。

### r2-evaluation-S-stress-eval-1-updated

将l0*u0、l1*u1提取为x0,x1，其余运算相同；参数仍非线性且冗余，完整保存拟合对象与起点/本对fixed相同。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-stress-eval-1-updated/source.py`
- SHA-256：`7648b20250d4dce1efa09743864ae39b08f883e71d6ee748ead88bc27c33465b`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/98e0ed12085c4bcd8215d18692faf84a/result.json`
- 参数结构：`nonlinear_redundant`；声明参数：7。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=True。

### r2-selection-S-select-1-fixed

只改文档字符串；去docstring AST与起点一致。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-1-fixed/source.py`
- SHA-256：`6f2862b1eb08dbb1690f8ba892ac7b0ee38e060e71de0048255fc9d471218657`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/0ed39e0c5f024043bf27e9bb725eb96c/result.json`
- 参数结构：`nonlinear`；声明参数：15。
- 相对起点：字节一致=False；去docstring AST一致=True；保存的完整fitting对象一致=True。

### r2-selection-S-select-1-updated

15→16；去掉可训练斜率tanh，改为16固定输入基的线性组合：1,u0,u1,u2,u0u1,u0u2,u1u2,u0²,u1²,u2²,u0u1u2,q*s,s³,u1³,sin(2u1),tanh(u0u2)。q=sum(ui²),s=sum(ui)，q*s为三次，不是docstring所说四次；参数化与表示同时改变。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-1-updated/source.py`
- SHA-256：`d81ea12e975c7fdda29d7f0b89df7d21885062f54d888fe43c67f42b563c3f74`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/893f6eba3f9e471089ea019c6ce3408d/result.json`
- 参数结构：`linear_core`；声明参数：16。
- 相对起点：字节一致=False；去docstring AST一致=False；保存的完整fitting对象一致=False。

### r2-selection-S-select-2-fixed

仅文档字符串改变；去docstring AST与起点一致。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-2-fixed/source.py`
- SHA-256：`6300e74f47693adbe52c5caea9440841451882e72c95b5449b72545ebc24ece7`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/89854513fa854c46b5f2d70311c6d3a5/result.json`
- 参数结构：`nonlinear`；声明参数：8。
- 相对起点：字节一致=False；去docstring AST一致=True；保存的完整fitting对象一致=True。

### r2-selection-S-select-2-updated

仅文档字符串改变；去docstring AST与起点一致，也与本对fixed可执行AST一致。

- 源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-2-updated/source.py`
- SHA-256：`160036e362a50b1acf650723166e107f113c3e9b4d19bc6806abdc59db6d5332`
- 拟合回执：`artifacts/strategy-measured/2026-10-21/v03/executions/2016ef98efff4d6dbe02512f777ad42c/result.json`
- 参数结构：`nonlinear`；声明参数：8。
- 相对起点：字节一致=False；去docstring AST一致=True；保存的完整fitting对象一致=True。

## 失败记录与不能下的结论

r1-selection-S-select-1-updated（15参数）与r1-evaluation-S-stress-eval-1-updated（6参数）均记录optimization_failed，没有NMSE或fitting内部详情。宿主此标签可由优化器非成功、拟合参数非有限或通用异常产生；现有回执不能确定是否恰好耗尽100次nfev，更不能据此宣称其函数族本身错误。两份缺失必须留在总体分母，不能丢弃、补拟合或用0替换。

r2-selection-S-select-1的15→16同时把可训练tanh斜率改为固定特征线性系数；r2-bactgrow的14→15同时用4平方项替换3三变量项。两对都不是只增加1个参数的纯容量消融。r1-stress的8→6也不是纯简化：一方有线性项，另一方没有，且后者平方系数有耦合约束。

## 建议下一步，分开回答两个问题

1. 先以已见数据作研究者指定的数值诊断：stressstrain保留完全相同的四个基函数，把7参数乘积形式改写为4个直接系数。这能够区分冗余参数化/拟合难度与函数表达能力；它本身不是Agent学习成果。两个版本保持相同训练数据、求解器、资源上限，另保存新记录，不覆盖旧分数。
2. 对bactgrow做等K表示诊断：共同11项不动，将原3个三变量项与四种“4个平方项中删去1个”的3项组合分别比较，全部预先登记并全部报告；保留原15项条件作容量参考。不能看结果后选最佳删项再称为公平单对照。
3. 新机制轮采用固定K、冻结特征字典、相同线性系数求解器，让Agent只选择/替换恰好K个不同基函数。固定与学习策略共享该表示、预算与求解器，另外保留同策略重复生成组。在新起点与多次独立S学习上评价；选择阶段与后续评分继续隔离。这样更直接检验策略是否帮助选择有用结构，而非偶然引入更易拟合或更大的模型。

这些建议尚未执行。没有读取设计矩阵或估计秩，不声称实际样本上各特征数值线性独立；有限算术核心的线性分类也不认证溢出/NaN处的全局数学性质。

证据核对：83个引用文件与归档清单（适用时）匹配，读取前后哈希不变；Python 3.12.14。
