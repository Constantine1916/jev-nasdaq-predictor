# JEV 纳斯达克每日涨跌预测

[English](README.md) / 简体中文

这是一个使用 TypeSafe Jev 进行纳斯达克方向预测的 Python 项目。

当前本机每天北京时间 20:00 的定时任务由 Codex automation 管理，配置不包含在本仓库中。克隆本仓库后，可以直接使用脚本，但需要自行配置 API key 和定时任务。

每次运行会：

1. 获取 Nasdaq Composite（`^IXIC`）历史数据。
2. 获取 S&P 500、纳指期货、VIX、美元、WTI、Brent、黄金、美国国债收益率，以及 BLS CPI 和就业数据。
3. 将这些数据组装成 JEV 输入。
4. 调用固定版本 `jev-1.13.0`，预测下一次可用美股常规交易日相对于最近一次已知收盘是上涨还是下跌。
5. 保存完整请求、JEV 原始响应和可回测的预测记录。

## 安装和配置

项目只使用 Python 标准库，不需要安装额外 Python 依赖。macOS 可以将 API key 保存到 Keychain：

```bash
security add-generic-password -U -a "$USER" -s typesafe-api-key -w 'your-typesafe-api-key'
```

脚本先读取 `TYPESAFE_API_KEY` 环境变量；如果没有，再读取当前 macOS 用户的 Keychain 项目。API key 只在运行时使用，不会写入请求文件、结果文件或日志。

非 macOS 环境请通过环境变量提供 key：

```bash
export TYPESAFE_API_KEY='your-typesafe-api-key'
```

不要提交真实 API key、`.env` 文件或 `runs/` 运行结果。

## 运行

先执行 dry run，只获取数据并保存 JEV 请求，不调用 JEV：

```bash
python3 jev_nasdaq_predictor.py --dry-run
```

执行真实预测：

```bash
python3 jev_nasdaq_predictor.py
```

## 输出文件

- `runs/<run-id>/jev_request.json`：发送给 JEV 的完整 JSON 输入。
- `runs/<run-id>/jev_response.json`：JEV 原始响应，包括概率、置信度、模型版本和 token 用量。
- `runs/<run-id>/run_metadata.json`：运行时间、基准交易日和运行状态。
- `runs/predictions.jsonl`：每次成功预测的一行记录。后续运行会在下一次收盘数据可用后回填实际方向和 `correct` 结果。

`runs/` 和 Python 缓存已加入 `.gitignore`，不会被提交到 Git。

## 口径和限制

预测目标是“下一次可用的美股常规交易日收盘，相对于最近一次已知 Nasdaq 收盘上涨还是下跌”。周末和美股假期会自动顺延到下一次实际交易日。

这是一个持续测量和校准的实验流程，不保证高准确率。请根据 `predictions.jsonl` 中积累的真实结果，按概率和置信度区间评估效果，再调整输入参数。

## License

MIT，详见 [LICENSE](LICENSE)。
