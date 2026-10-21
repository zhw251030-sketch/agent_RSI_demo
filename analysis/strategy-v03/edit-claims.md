# measured-v03 全32份终稿的窄编辑声明核查

日期：2026-10-22。只读、人工事后核查；32/32覆盖，16规划、16符号。结果：{'supported': 25, 'contradicted': 4, 'unknown': 3}。

Read explanation in textual order. Select at most one first concrete present/completed edit-or-retention assertion, skipping prior-source diagnosis, causal rationale, hypotheses, predictions and future intentions. In a multi-action statement select its leftmost independently locatable operation; preserve its internal qualifiers and counts. Mere broad conservation slogans are not concrete edits. If wording cannot be assigned a narrow unambiguous predicate, mark unknown. Declaration-count change is eligible when earlier changes appear only as hypotheses. This is manual post-hoc annotation after results were known, not blinded or preregistered.

这不是规则遵守总分，也不是全文正确率。所有规则文本仅作上下文：规则本身通常宽泛，不能把一次具体编辑存在当成R01/R08已经被全面执行。真实任务分数完全沿用旧档，本审查没有运行程序、拟合或调用模型。

## 证据边界

- This is not an all-claims audit or policy obedience score. Four selected rule IDs and texts are contextual metadata only.
- AST equality is a syntactic observation after docstring removal; unequal AST is not proof of semantic change. Bytes differ when comments/docstrings/format change.
- A supported edit can produce incorrect programs; a true source comparison does not establish a correct failure cause, necessary structure, causal strategy effect, metric benefit, or generalization.
- One narrow manually selected claim per submission may omit other false statements. Counts cannot be interpreted as whole-explanation accuracy.
- No candidate source was executed or imported. No refit, model request, sealed data read, or historical file modification.
- All parent sources were checked byte-for-byte against the actual actor request; all child sources matched accepted submissions.

## 全量逐项记录

### r1-selection-P-select-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> this revision normalises every predicate with a strict _norm conversion

新增 _norm，_as_set 对每个输入谓词调用它；只认证这一规范化动作，不认证同句后续的逆序对象处理、全程序确定性或失败归因。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[623, 694)；SHA256 `c31036b8d931998d4520d41a3a3413a8cb6251f994e9c9e993a7242224d22753`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-1/source.py`；SHA256 `081ab4125587db6b90dbc218bc9fa109deee503b8382a0f2bb829e4e1da335a5`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-1-fixed/source.py`；SHA256 `565c6cf040a05a59a97f7a3174214a51960e9987d22c89861959914a6dac294e`。

- parent 源码第28–33行；完整原文及请求/源码哈希见JSON。
- child 源码第22–33行；完整原文及请求/源码哈希见JSON。

### r1-selection-P-select-1-updated

判定：**contradicted**。规则：R02 / R05 / R01 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> The rewrite parses `(name, type)` entries robustly (also tolerating a reversed `(type, name)` ordering)

所选子句明确包含逆序(type,name)字符串对。新 _types 遇到两个字符串总设 name=a,typ=b，故("man","bob")仍被读为name=man,type=bob，没有按已知类型识别并交换；无须运行即可由分支判定。这个反例不判断标准(name,type)输入。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[802, 905)；SHA256 `3041406baf2f5a8a03244bedd7fa3b38997755fdb8d25ef0fd08645035d571d1`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-1/source.py`；SHA256 `081ab4125587db6b90dbc218bc9fa109deee503b8382a0f2bb829e4e1da335a5`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-1-updated/source.py`；SHA256 `3d2b84e89294fccf323b254eafa2d28151210676acd3dd3b3ad5a18d94cfd3e7`。

- parent 源码第36–48行；完整原文及请求/源码哈希见JSON。
- child 源码第40–57行；完整原文及请求/源码哈希见JSON。

### r1-selection-P-select-2-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Thread the parsed `links` relation explicitly into action generation instead of the id()-keyed `_LINK_CACHE` module-level dict

新 get_plan 从init读取links，存入ctx；_actions通过ctx["links"]传入_walk，父程序的_LINK_CACHE消失。只认证显式传递替换缓存。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-2-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[442, 568)；SHA256 `5a8bebb8a30332347218fec1e71e0085c2e6507aa4c61ec52a86a643de208b41`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-2/source.py`；SHA256 `6acf551511d5dc5e245b7d7df989620aba03756f6e86b8fc3d3130592cfcf270`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-2-fixed/source.py`；SHA256 `49b09457a5cff059d1e5c0dd9978e83f67ec4bf9818d85401333a3858a9fd535`。

- parent 源码第167–181行；完整原文及请求/源码哈希见JSON。
- parent 源码第227–235行；完整原文及请求/源码哈希见JSON。
- parent 源码第242–269行；完整原文及请求/源码哈希见JSON。
- child 源码第189–196行；完整原文及请求/源码哈希见JSON。
- child 源码第203–220行；完整原文及请求/源码哈希见JSON。

### r1-selection-P-select-2-updated

判定：**supported**。规则：R02 / R05 / R01 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Fix: declare _actions(state, types, links) and use the passed-in link relation instead of the id(types)-keyed cache and the empty _compute_links stub.

新签名三参数，与调用三参数一致；动作生成读取传入links，旧缓存和空_compute_links已移除。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-2-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[157, 307)；SHA256 `8fd29becf5396b8a50d384eb891ca700ac9cbbe184c1909084ae82baf7b0d887`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-2/source.py`；SHA256 `6acf551511d5dc5e245b7d7df989620aba03756f6e86b8fc3d3130592cfcf270`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-P-select-2-updated/source.py`；SHA256 `28aca17fdc0f7ebd3c0d294cb4166559e089ecf759e70ff95a8a879453e5b307`。

- parent 源码第167–181行；完整原文及请求/源码哈希见JSON。
- parent 源码第227–235行；完整原文及请求/源码哈希见JSON。
- parent 源码第269–269行；完整原文及请求/源码哈希见JSON。
- child 源码第133–150行；完整原文及请求/源码哈希见JSON。
- child 源码第193–197行；完整原文及请求/源码哈希见JSON。
- child 源码第214–214行；完整原文及请求/源码哈希见JSON。

### r1-selection-S-select-1-fixed

判定：**contradicted**。规则：R03 / R04 / R06 / R08。参数：15 → 15。字节相等：False；去docstring AST相等：True。

> adding higher-order polynomial terms while keeping 15 declared parameters

父子方程去docstring后的AST完全相同，执行体仍只有原来的三变量乘积与两项tanh，没有新增高阶多项式。15参数声明保持，但不能挽救增加项的主张。此处把提交后的说明中“the only case-specific change ... adding”视作本终稿编辑说明，不把模型所说可能降低偏差当成果。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[352, 425)；SHA256 `ab6036212e3e2a73376c612051151e7a24d6d4910bd15270079ca4896e117975`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-1/source.py`；SHA256 `4e741492c3ae7fa2836bc3080dd0657c98296e11dd8db880867bf00798494ff2`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-1-fixed/source.py`；SHA256 `9d2817370bbfdd521af91042018374613a65739b7eca74395a6c89a61b2630a7`。

- parent 源码第20–45行；完整原文及请求/源码哈希见JSON。
- child 源码第17–42行；完整原文及请求/源码哈希见JSON。


### r1-selection-S-select-1-updated

判定：**supported**。规则：R02 / R05 / R01 / R08。参数：15 → 15。字节相等：False；去docstring AST相等：False。

> I replace the cubic monomial with the squared summed pair-products cross term

旧p10*u0*u1*u2被p10*cross*cross替换，cross=u0*u1+u1*u2+u0*u2；声明仍15。只认证替换，不认证所谓额外独立方向或收益。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[580, 657)；SHA256 `dc66152a62eb4bc24b80a5178d8c91e5ffef326af9ff0b5df1d4abc13ff2d2fe`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-1/source.py`；SHA256 `4e741492c3ae7fa2836bc3080dd0657c98296e11dd8db880867bf00798494ff2`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-1-updated/source.py`；SHA256 `cf3e6bb5d584526709e550bb9142afb8e436795e2721648d6d0c5fa6186b6e80`。

- parent 源码第39–41行；完整原文及请求/源码哈希见JSON。
- child 源码第28–43行；完整原文及请求/源码哈希见JSON。


### r1-selection-S-select-2-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：8 → 8。字节相等：False；去docstring AST相等：False。

> I keep the observed baseline structure (8 parameters, NMSE 0.19068 on train)

主表达式和三个仿射缩放保留、声明8；参数读取改为float列表解包，docstring变化，因此不是逐字节保留。只认证公式结构保留，括号NMSE仅为父记录引用、不是本条新测量。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-2-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[45, 121)；SHA256 `e4804f6558fa4803e3c41236e261e9977ec3c1e08c172b89e54b5673e8bd2278`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-2/source.py`；SHA256 `7ef02e17a7c07f2ec7ecd1b252261144f7836abb9e89bca2d4fae344cdd0b3f0`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-2-fixed/source.py`；SHA256 `c3dfb457e2a89d3d300e28be22dcef50cca84eaf2af63a04d4296862c3926bd2`。

- parent 源码第10–25行；完整原文及请求/源码哈希见JSON。
- child 源码第10–18行；完整原文及请求/源码哈希见JSON。

### r1-selection-S-select-2-updated

判定：**unknown**。规则：R02 / R05 / R01 / R08。参数：8 → 14。字节相等：False；去docstring AST相等：False。

> add six strictly linear-in-parameter basis terms (c8..c13) spanning the missing pair products and self-quadratics inside the same scaled envelope

新core确有c8..c13六项，但它们再乘含c1/c2/c3的s0*s1*s2；整体对全部拟合参数并非线性。若只指固定缩放时六个新增系数的条件线性则成立；若指整个候选严格线性则不成立。保留原限定词，不把歧义强判为支持。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-2-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[486, 631)；SHA256 `bf7787f1b11d2c40bc4bfc4867a6928cea47151fbf1d4e588f6ae6b4ce4df190`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-2/source.py`；SHA256 `7ef02e17a7c07f2ec7ecd1b252261144f7836abb9e89bca2d4fae344cdd0b3f0`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-selection-S-select-2-updated/source.py`；SHA256 `6a356c6206a140f2de2f600aa0b561b622a6b9943127c02eae1a3f03b3cfead2`。

- parent 源码第10–25行；完整原文及请求/源码哈希见JSON。
- child 源码第21–46行；完整原文及请求/源码哈希见JSON。


### r2-selection-P-select-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> replace the search-first design with a typed, order-respecting direct schedule

新get_plan先直接构造计划，_verify后返回或调用_search；父get_plan直接进入全状态BFS。仅认证先构造后搜索的控制流，不认证调度正确性或类型完全合规。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[770, 848)；SHA256 `89644cc807c37129b2fb7c547511bbcdabd9c6593b82286e699045a274050d44`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-1/source.py`；SHA256 `081ab4125587db6b90dbc218bc9fa109deee503b8382a0f2bb829e4e1da335a5`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-1-fixed/source.py`；SHA256 `5f2126ca08c16eecb891896bb44f5413191a177ce30b7b98252aa3f34f83412d`。

- parent 源码第155–182行；完整原文及请求/源码哈希见JSON。
- child 源码第65–202行；完整原文及请求/源码哈希见JSON。
- child 源码第243–303行；完整原文及请求/源码哈希见JSON。

### r2-selection-P-select-1-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Replaced with a clean two-ordering normaliser `_name_type` and dropped the misleading predicate-derived enrichment.

新_name_type按照已知类型词处理两种字符串顺序，_typed只从objects构建角色；旧遍历state/goal向men/nuts/spanners补充的分支移除。限定有效的字符串对象条目，不认证说明里宽泛根因和所有契约。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[596, 711)；SHA256 `b25da1f32733844558ab0ac9623be4a861c15a1bd9ea9feadb5383f6109833e2`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-1/source.py`；SHA256 `081ab4125587db6b90dbc218bc9fa109deee503b8382a0f2bb829e4e1da335a5`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-1-updated/source.py`；SHA256 `bd55bb9dd6572517e2c2e0893792b671abd6a3e00a046e72750d7a0ef4d54a87`。

- parent 源码第36–48行；完整原文及请求/源码哈希见JSON。
- parent 源码第55–87行；完整原文及请求/源码哈希见JSON。
- child 源码第49–81行；完整原文及请求/源码哈希见JSON。
- child 源码第84–100行；完整原文及请求/源码哈希见JSON。

### r2-selection-P-select-2-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Fixed by declaring `links` as a third parameter and passing the already-computed link map.

_actions(state,types,links)签名与get_plan三参数调用一致；links由init构建。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-2-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[145, 235)；SHA256 `8cf916ee2c1f8c59380b648fdab2360a84e79739a63e77950fd81e8c1e520780`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-2/source.py`；SHA256 `6acf551511d5dc5e245b7d7df989620aba03756f6e86b8fc3d3130592cfcf270`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-2-fixed/source.py`；SHA256 `93722fc74980d07c35309bf6be9231bc71a8383ec98c14cd9f1a4d44ac6acfcc`。

- parent 源码第167–181行；完整原文及请求/源码哈希见JSON。
- parent 源码第269–269行；完整原文及请求/源码哈希见JSON。
- child 源码第137–155行；完整原文及请求/源码哈希见JSON。
- child 源码第199–238行；完整原文及请求/源码哈希见JSON。

### r2-selection-P-select-2-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> The fix removes the broken `_LINK_CACHE`/`_compute_links` indirection (which relied on data not actually passed in) and threads the link relation through `_actions` as a proper argument extracted from `init` via a new `_read_links` helper.

缓存和空stub移除，新增_read_links(init)，传入_actions的第三个实参。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-2-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[176, 415)；SHA256 `f9bd4d7c3f9de4095b9b9557e0747cfbe6dd2c46ce03e90dc08567e02f8f40e6`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-select-2/source.py`；SHA256 `6acf551511d5dc5e245b7d7df989620aba03756f6e86b8fc3d3130592cfcf270`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-P-select-2-updated/source.py`；SHA256 `3ba160adf1f8e70623679f5c3920567a4ad076e08075c95971ac6ab5f9ae76eb`。

- parent 源码第167–181行；完整原文及请求/源码哈希见JSON。
- parent 源码第227–235行；完整原文及请求/源码哈希见JSON。
- parent 源码第244–269行；完整原文及请求/源码哈希见JSON。
- child 源码第138–146行；完整原文及请求/源码哈希见JSON。
- child 源码第176–191行；完整原文及请求/源码哈希见JSON。
- child 源码第234–264行；完整原文及请求/源码哈希见JSON。

### r2-selection-S-select-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：15 → 15。字节相等：False；去docstring AST相等：True。

> I retain the expression and declared parameter count unchanged

去docstring后AST一致，声明15；实际改变仅docstring。此条不认证父候选本来正确或保留策略必优。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[311, 373)；SHA256 `82771c8d5d20c207a28d5988f181f7109c4a16c9ded38cabf5e4eeab5598781b`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-1/source.py`；SHA256 `4e741492c3ae7fa2836bc3080dd0657c98296e11dd8db880867bf00798494ff2`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-1-fixed/source.py`；SHA256 `6f2862b1eb08dbb1690f8ba892ac7b0ee38e060e71de0048255fc9d471218657`。

- parent 源码第4–45行；完整原文及请求/源码哈希见JSON。
- child 源码第4–48行；完整原文及请求/源码哈希见JSON。

### r2-selection-S-select-1-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：15 → 16。字节相等：False；去docstring AST相等：False。

> Under this change every declared parameter is a linear coefficient on a fixed feature

新feats不含p，循环按y+=p[i]*fi组合16个固定特征，替换父式含参数的tanh内部增益。只认证有限输入下最终非有限值保护前的系数-特征构造，不认证完整拟合器是线性算法、参数可识别性或quartic等其他文字。首个swap句明确为intended change，不单凭该意图判完成；这里核对后续现时结构断言。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[820, 905)；SHA256 `763e4737ef61dbaa517b6dd10043f93b9a76e430cf3212a6e05232f4a9b88fdb`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-1/source.py`；SHA256 `4e741492c3ae7fa2836bc3080dd0657c98296e11dd8db880867bf00798494ff2`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-1-updated/source.py`；SHA256 `d81ea12e975c7fdda29d7f0b89df7d21885062f54d888fe43c67f42b563c3f74`。

- parent 源码第39–42行；完整原文及请求/源码哈希见JSON。
- child 源码第34–59行；完整原文及请求/源码哈希见JSON。

### r2-selection-S-select-2-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：8 → 8。字节相等：False；去docstring AST相等：True。

> Kept the starting candidate unchanged.

去docstring后AST一致、参数数8保持。原句未明确要求字节一致，按候选计算结构不变解释；docstring确有删词，字节未保持，已独立记录。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-2-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[0, 38)；SHA256 `c4d99666c404e69020e550192b036dfca0f9cdb92e1a08817e235f1b1218955b`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-2/source.py`；SHA256 `7ef02e17a7c07f2ec7ecd1b252261144f7836abb9e89bca2d4fae344cdd0b3f0`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-2-fixed/source.py`；SHA256 `6300e74f47693adbe52c5caea9440841451882e72c95b5449b72545ebc24ece7`。

- parent 源码第4–25行；完整原文及请求/源码哈希见JSON。
- child 源码第4–25行；完整原文及请求/源码哈希见JSON。

### r2-selection-S-select-2-updated

判定：**contradicted**。规则：R02 / R01 / R05 / R08。参数：8 → 8。字节相等：False；去docstring AST相等：True。

> replace the multiplicative cubic scaling with a shared quadratic-in-u0 scaling plus an extra cross term

去docstring后AST一致；旧s0*s1*s2与核心项逐字未变，未加入所声称的新缩放或额外交叉项。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-2-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[673, 776)；SHA256 `d3e026463fc662ea207d7aabc6dbfcd0011b4db226df5f0461499732b8fb54f8`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-select-2/source.py`；SHA256 `7ef02e17a7c07f2ec7ecd1b252261144f7836abb9e89bca2d4fae344cdd0b3f0`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-selection-S-select-2-updated/source.py`；SHA256 `160036e362a50b1acf650723166e107f113c3e9b4d19bc6806abdc59db6d5332`。

- parent 源码第10–25行；完整原文及请求/源码哈希见JSON。
- child 源码第10–25行；完整原文及请求/源码哈希见JSON。

### r1-evaluation-P-eval-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Links are now filtered by declared type and indexed as a directed adjacency map

新links_out只接收两端tmap均为location的有向边并去重排序；旧只检查两端存在于tmap。只认证这项局部编辑，不认证整个重写保留原成功行为。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[482, 561)；SHA256 `f287ac4bf1aed58305d6bced34c0ca3ee3d83ad3abd98bfa4dc7739d1943812b`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-1/source.py`；SHA256 `0972061b30d682c2023f394e2727af2139857125ef2778daf2f173d2cb01a07e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-1-fixed/source.py`；SHA256 `3242c3314c112b0bb979813a28d4cd08891ce4654914ad8d78cb24c4e7849947`。

- parent 源码第82–86行；完整原文及请求/源码哈希见JSON。
- child 源码第82–89行；完整原文及请求/源码哈希见JSON。

### r1-evaluation-P-eval-1-updated

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> replaces global state-space search with a goal-directed constructive procedure

父全状态queue循环被按goal nut的构造流程替代，保留的bfs_path只搜索位置图；只认证结构替换，不认证保持前提、复杂度或10题成绩。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[430, 508)；SHA256 `0ffbda433049c2570942910c13db83f10abeae7dd81ff7969f3042979894ce8c`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-1/source.py`；SHA256 `0972061b30d682c2023f394e2727af2139857125ef2778daf2f173d2cb01a07e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-1-updated/source.py`；SHA256 `0ed38074463245e3f7da292cc59da1b2b34a0d0a67e12961dd2951e7cd46ccea`。

- parent 源码第140–163行；完整原文及请求/源码哈希见JSON。
- child 源码第97–120行；完整原文及请求/源码哈希见JSON。
- child 源码第154–227行；完整原文及请求/源码哈希见JSON。

### r1-evaluation-P-eval-2-fixed

判定：**unknown**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> rewrites the planner as a single, deterministic, state-serialising greedy construction

新源码确有贪心构造而旧有嵌套试探，但“deterministic”要求遍历/决策整体确定。代码仍多处直接迭代state/set（如useable_spanners等），仅静态局部改写不足以认证完整限定的确定性。该句不把新增drop动作当合法性认证。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-2-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[742, 828)；SHA256 `d4cae575f45346dbfb9c3d027e194168b4c89a9701d817a6a56680f692c511ce`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-2/source.py`；SHA256 `64881221233ab478d7bae624ef4cb6c7a35a1e0ca7f76480745801cf3a24a660`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-2-fixed/source.py`；SHA256 `be6bf79fde8fcf2fd50196a75bc6137424fc988fd13c9aaa9b845c0a95c02286`。

- parent 源码第201–242行；完整原文及请求/源码哈希见JSON。
- parent 源码第261–268行；完整原文及请求/源码哈希见JSON。
- child 源码第175–246行；完整原文及请求/源码哈希见JSON。
- child 源码第253–287行；完整原文及请求/源码哈希见JSON。

### r1-evaluation-P-eval-2-updated

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Repair: replace the entangled nested-loop/closure code with a clean, explicit grounded simulator

新增_Domain、显式actions/apply/precondition_ok/successor；旧嵌套全局恢复结构被移除。只认证显式模拟器替换，不把紧随其后的exactly等全文正确性主张纳入本条。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-2-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[529, 625)；SHA256 `1c9921275a04f6ad4f1d355f65ffba454f0fc4ac3891bb7adb03f41cc70a869a`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-2/source.py`；SHA256 `64881221233ab478d7bae624ef4cb6c7a35a1e0ca7f76480745801cf3a24a660`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-P-eval-2-updated/source.py`；SHA256 `5ed5c9ba44123ff98e1f56b127043f021a159b78475b20dfe06b8e9de4779df9`。

- parent 源码第201–268行；完整原文及请求/源码哈希见JSON。
- child 源码第23–111行；完整原文及请求/源码哈希见JSON。

### r1-evaluation-S-bact-eval-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：7 → 8。字节相等：False；去docstring AST相等：False。

> Declared count rises from 7 to 8

前文adding/removing/replacing写为hypotheses，未单独视为已完成承诺；首个明确现时编辑是声明参数数7→8，与submission.n_params和p[0..7]匹配。并非认证线性拟合只能受益的归因。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-bact-eval-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[906, 938)；SHA256 `45e516d6cb7d6473e7e942a38451a7da09683440761a6405e7e2e1493af0273b`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-bact-eval-1/source.py`；SHA256 `93e698f8e8b01a0a2c508955b42ee162b194181878b7cdfae48d562a4448c19e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-bact-eval-1-fixed/source.py`；SHA256 `ed997a93fc95f08d6d991974138eb68eeb17e2edc59862b19db6b4ec53141492`。

- child 源码第13–20行；完整原文及请求/源码哈希见JSON。
- parent 源码第12–18行；完整原文及请求/源码哈希见JSON。


### r1-evaluation-S-bact-eval-1-updated

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：7 → 12。字节相等：False；去docstring AST相等：False。

> adds a linear u3 term

新lin增加b3*u3（b3来自参数索引4），旧lin无u3项。只认证新增线性输入项，不认证忽略信息必然导致误差等因果判断。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-bact-eval-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[458, 479)；SHA256 `49a4ce1e6412349ed98eed3f9e293ac8ab3433ba85999467783e40e488d1a8a1`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-bact-eval-1/source.py`；SHA256 `93e698f8e8b01a0a2c508955b42ee162b194181878b7cdfae48d562a4448c19e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-bact-eval-1-updated/source.py`；SHA256 `96afd970ef2268ec9983cced418b21baf6ddc084a87b3a1eb0e78f8ed6828780`。

- child 源码第31–35行；完整原文及请求/源码哈希见JSON。
- child 源码第44–44行；完整原文及请求/源码哈希见JSON。
- parent 源码第25–26行；完整原文及请求/源码哈希见JSON。


### r1-evaluation-S-stress-eval-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：7 → 8。字节相等：False；去docstring AST相等：False。

> Declared count rises from 7 to 8

前文adding是未验证假设，明确完成性声明为参数7→8，submission及p[0..7]一致；不把降低误差或反对称解释当已测事实。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-stress-eval-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[413, 445)；SHA256 `6f8db0af747d15759abe4805652aa6690eedf62d9ac2eaa08633cfe34243d5d1`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-stress-eval-1/source.py`；SHA256 `58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-stress-eval-1-fixed/source.py`；SHA256 `562e92193d076307da35b70a3f71d76023f5afdd0f2471866b73cbb83c03606d`。

- parent 源码第11–17行；完整原文及请求/源码哈希见JSON。
- child 源码第11–18行；完整原文及请求/源码哈希见JSON。

### r1-evaluation-S-stress-eval-1-updated

判定：**contradicted**。规则：R03 / R04 / R06 / R08。参数：7 → 6。字节相等：False；去docstring AST相等：False。

> keep the original 7-parameter hypothesis unchanged

实际submission.n_params=6，父7；子代码将两个独立曲率合并为q0*(a+d)^2，参数索引和公式均改变。这与解释“选择原样保留”直接相反；不是仅末尾空白变化。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-stress-eval-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[356, 406)；SHA256 `e7fedee98e31f0e3dfca7adbda3ca72f76a630a71c4ea9c34cf4fb9bf7cc057d`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-stress-eval-1/source.py`；SHA256 `58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r1-evaluation-S-stress-eval-1-updated/source.py`；SHA256 `d00a34cb574ddf84af20b402b7dd1ea36d1af9692a15eed6cdf3274ef75cb3e9`。

- parent 源码第11–20行；完整原文及请求/源码哈希见JSON。
- child 源码第18–30行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-P-eval-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> adds (a) a static seed set derived from goal nuts and their locations

新seed从goal_nut_locs生成相关at/useable事实；父源码无seed。只认证增加该集合，不认证随后priority安全、相同后继集或最短性。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[585, 654)；SHA256 `0bc5fdc3e14b07313b42fb749c7c6701a3988f44c99841246e07ac151e86f137`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-1/source.py`；SHA256 `0972061b30d682c2023f394e2727af2139857125ef2778daf2f173d2cb01a07e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-1-fixed/source.py`；SHA256 `e65805c29ff431e6e100d6906f62eed313aa5615f429276cefcb7d6678a00a45`。

- parent 源码第82–91行；完整原文及请求/源码哈希见JSON。
- child 源码第89–106行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-P-eval-1-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> the early goal check now also covers an empty goal

显式由goal<=start改为not goal or goal<=start；空集合原来已满足subset，说明也承认冗余。只认证显式分支，不能作为新任务收益来源。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[279, 329)；SHA256 `957990b8ea95feb008de9d0ae3b652bff4f3a6a61a8ac29061d05c2573aac970`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-1/source.py`；SHA256 `0972061b30d682c2023f394e2727af2139857125ef2778daf2f173d2cb01a07e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-1-updated/source.py`；SHA256 `36228e93c43e1dac95ce11da4f558a7314f049f84c15ea6e450e1d17ff1349fb`。

- parent 源码第78–80行；完整原文及请求/源码哈希见JSON。
- child 源码第89–90行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-P-eval-2-fixed

判定：**unknown**。规则：R03 / R04 / R06 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> Rewrote the planner around a single coherent search: a deterministic fact-set state with fully checked grounded action appliers

源码有重写及apply_*前提检查，但“single coherent / fully checked”是全路径合规断言；其他act/DFS路径仍需具体输入或形式证明。未执行新候选，不把组件存在扩大为整个流程完整验证。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-2-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[0, 127)；SHA256 `037a8a96b4f0c04883e74a34a78638dff44614eb2412358e8ddcc6cb19a4791c`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-2/source.py`；SHA256 `64881221233ab478d7bae624ef4cb6c7a35a1e0ca7f76480745801cf3a24a660`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-2-fixed/source.py`；SHA256 `6be510b70ad0f3ac7eefc99923005ebc168346c4afce5904ecacbeb76ed4635f`。

- parent 源码第68–92行；完整原文及请求/源码哈希见JSON。
- parent 源码第201–242行；完整原文及请求/源码哈希见JSON。
- child 源码第58–80行；完整原文及请求/源码哈希见JSON。
- child 源码第103–145行；完整原文及请求/源码哈希见JSON。
- child 源码第265–301行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-P-eval-2-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：0 → 0。字节相等：False；去docstring AST相等：False。

> The new version keeps an explicit `initial` snapshot

子initial=set(state)明确存在，旧用_snapshot/_restore且无该初始快照变量。仅认证新快照，不认证旧_restore擦掉最终复制或新模拟正确的解释。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-2-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[300, 352)；SHA256 `32dd52a291f238492d554af97bde080184fbdadf99373404e569fe7c449b122c`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/P-eval-2/source.py`；SHA256 `64881221233ab478d7bae624ef4cb6c7a35a1e0ca7f76480745801cf3a24a660`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-P-eval-2-updated/source.py`；SHA256 `3fcb80ffecc15d82d3115af9d9275a27256b59dc5bc7c4319f0d48874a3d6630`。

- parent 源码第261–268行；完整原文及请求/源码哈希见JSON。
- child 源码第131–140行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-S-bact-eval-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：7 → 14。字节相等：False；去docstring AST相等：False。

> Replaced the ad-hoc linear+cross-term blend (which also had a redundant clip/scale identity transform) with a systematic multilinear expansion: constant, four singles, six pairwise, three triples = 14 coefficients

子式有1常数+4一次+6二阶交叉+3三阶交叉，14个系数，父7项；这里“linear”指固定输入特征对系数线性，未认证可泛化或拟合收益。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-bact-eval-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[100, 313)；SHA256 `9736123745efc113ae052f7fc8b9a9212bbdd1b061a4ca960f3b6a580ae20e33`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-bact-eval-1/source.py`；SHA256 `93e698f8e8b01a0a2c508955b42ee162b194181878b7cdfae48d562a4448c19e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-bact-eval-1-fixed/source.py`；SHA256 `9c045f8b32a4dd4941a362b187cf49780a14a7b7c6b38c70bf1f5d59ed7c5c0e`。

- parent 源码第11–33行；完整原文及请求/源码哈希见JSON。
- child 源码第19–44行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-S-bact-eval-1-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：7 → 15。字节相等：False；去docstring AST相等：False。

> Change applied: replace the ad-hoc 7-term expression with a fixed 15-feature linear basis

子列出f0..f14（常数4线性6交叉4平方），循环乘对应p[i]；父7参数。仅认证特征构造，末尾scale表达式的浮点性质与拟合收益另论。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-bact-eval-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[323, 412)；SHA256 `fb55179e00dcff519b0290c31fda5c3f8061cacbae5b634aab222cc56bc781dd`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-bact-eval-1/source.py`；SHA256 `93e698f8e8b01a0a2c508955b42ee162b194181878b7cdfae48d562a4448c19e`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-bact-eval-1-updated/source.py`；SHA256 `9604a6385064ef2aa3ae49128d4e2293c9ec10b8a81a0798eb86e063388f371b`。

- parent 源码第11–33行；完整原文及请求/源码哈希见JSON。
- child 源码第18–43行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-S-stress-eval-1-fixed

判定：**supported**。规则：R03 / R04 / R06 / R08。参数：7 → 7。字节相等：True；去docstring AST相等：True。

> I keep the original hypothesis family unchanged

父子源码逐字节相同、参数7一致，因此公式族确实保留；不认证“无回归风险”及策略价值。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-stress-eval-1-fixed/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[215, 262)；SHA256 `a2a04ff652ee56566f1103df5867cc30d9cc54a15bacd2b098c94ae8591bd0d7`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-stress-eval-1/source.py`；SHA256 `58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-stress-eval-1-fixed/source.py`；SHA256 `58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`。

- parent 源码第1–20行；完整原文及请求/源码哈希见JSON。
- child 源码第1–20行；完整原文及请求/源码哈希见JSON。

### r2-evaluation-S-stress-eval-1-updated

判定：**supported**。规则：R02 / R01 / R05 / R08。参数：7 → 7。字节相等：False；去docstring AST相等：False。

> Change: replaced the redundant squared-scaled-input products with precomputed scaled variables x0 = l0*u0 and x1 = l1*u1 used in all three terms.

子先计算x0/x1并在三个项中替换父重复(l0*u0)/(l1*u1)表达式；只认证公共子表达式提取，不认证它减少幂运算、避免溢出、改善条件数等后续解释。

引文：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-stress-eval-1-updated/explanation.json` 第1行，JSON指针 `/explanation`，字符区间[619, 764)；SHA256 `9c3b375c1030457ef708f3130586744f2e6ccdbeb95505193e45ef08efe36207`。

父源码：`artifacts/state-generation/2026-10-21/v02/sessions/S-stress-eval-1/source.py`；SHA256 `58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`。
子源码：`artifacts/strategy-measured/2026-10-21/v03/raw/experiment/sessions/r2-evaluation-S-stress-eval-1-updated/source.py`；SHA256 `7648b20250d4dce1efa09743864ae39b08f883e71d6ee748ead88bc27c33465b`。

- parent 源码第19–20行；完整原文及请求/源码哈希见JSON。
- child 源码第19–23行；完整原文及请求/源码哈希见JSON。

## 研究含义

三个特别直接的结构矛盾：r1-selection-S-select-1-fixed说增加高阶项但只改docstring；r2-selection-S-select-2-updated说换缩放/交叉项但只改docstring；r1-evaluation-S-stress-eval-1-updated说保留7参数却提交6参数并合并曲率。另r1-selection-P-select-1-updated所称支持逆序字符串对象对，与_types分支相矛盾。

窄声明支持不认证全文。例如r2-evaluation-S-stress-eval-1-updated确实提取x0/x1公共子表达式，却不能由此推出避免溢出或改进条件数；r1-evaluation-P-eval-1-fixed确实新增类型过滤，却不意味着整个重写保留原成绩。下一轮可把明确的编辑承诺绑定父子源码，先测试拒绝/纠正这类直接矛盾是否改变部署决策，再用独立多次生成检验收益。只修好说明、未改善程序，不算任务收益。
