# 样地回访的空间区间估计

生态组做完一轮样地回访，明早要用调查均值估计整片区域的植物覆盖率。相邻样地受同一条沟谷或坡面影响，按单个样地独立重采样会把置信区间压得过窄；同时各地块的抽样权重本来就不相等。请把 `/app/spatial_bootstrap_support.py` 改成按空间块重采样的复核工具，并给出可稳定重复的区间。

## 调查文件

调查员交来的联络单是 UTF-8 JSON 文档。文件根对象含 `study_id`、`points`、`block_size_km`、`replicates`、`seed`、`confidence_level`。

研究标签 `study_id` 的字符范围是 2 到 48；空白和控制字符都不允许。`points` 有 12 到 120 条，每条只有 `plot_id`、`x_km`、`y_km`、`weight`、`coverage`：`plot_id` 匹配 `[A-Z][A-Z0-9_-]{1,15}` 且不重复；坐标和权重都是有限数，权重位于 `(0,100]`，覆盖率位于 [0,1]。`block_size_km` 位于 `(0,10000]`。`replicates` 是 50 到 2000 的整数。`seed` 是 0 到 4294967295 的整数。`confidence_level` 位于 0.8 到 0.99。布尔值不能冒充数字。

## 空间块与估计

每个点属于块坐标 `(floor(x_km/block_size_km), floor(y_km/block_size_km))`。点按块坐标、再按 `plot_id` 排成稳定数组。点估计是权重加权的覆盖率：

```text
estimate = sum(weight_i * coverage_i) / sum(weight_i)
```

每次 bootstrap 从全部空间块中等概率、有放回抽取同样多个块。被抽中一次的块内点集按原权重进入该次计算；重复抽中的块也重复计入。随机数使用 32 位线性同余序列 `state = (1664525*state + 1013904223) mod 2^32`，每次抽取块下标用 `state mod block_count`。

同输入重跑必须逐字节一致。

把所有 replicate 的加权均值升序排列，置信区间端点取 `(replicates-1)*p` 位置的线性插值，`p` 分别是 `(1-confidence_level)/2` 和 `1-(1-confidence_level)/2`。

## 复核结果

交回的报表是一行紧凑 JSON，最后仅保留 LF。顶层键依次为 `study_id`、`status`、`estimate`、`ci_low`、`ci_high`、`block_count`、`replicates`。`status` 写 `complete`。完整结束后，两个标准流都为空。结果先在同目录写临时文件，再替换目标；失败不能改旧结果，也不能留下临时文件。

## 退回

联络单不合格就别生成报表：退出码 1，标准错误为 `运行拒收: BAD_INPUT`。

如果结果无处可写，退出码为 1，标准错误只有 `运行拒收: IO_FAILURE`。

