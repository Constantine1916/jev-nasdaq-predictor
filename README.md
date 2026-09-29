# JEV Nasdaq Daily Prediction

## 中文

这是一个使用 TypeSafe Jev 进行纳斯达克方向预测的 Python 项目。

当前本机每天北京时间 20:00 的定时任务由 Codex automation 管理，配置不包含在本仓库中。克隆本仓库后，可以直接使用脚本，但需要自行配置 API key 和定时任务。

每次运行会：

1. 获取 Nasdaq Composite（`^IXIC`）历史数据。
2. 获取 S&P 500、纳指期货、VIX、美元、WTI、Brent、黄金、美国国债收益率，以及 BLS CPI 和就业数据。
3. 将这些数据组装成 JEV 输入。
4. 调用固定版本 `jev-1.13.0`，预测下一次可用美股常规交易日相对于最近一次已知收盘是上涨还是下跌。
5. 保存完整请求、JEV 原始响应和可回测的预测记录。

### 安装和配置

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

### 运行

先执行 dry run，只获取数据并保存 JEV 请求，不调用 JEV：

```bash
python3 jev_nasdaq_predictor.py --dry-run
```

执行真实预测：

```bash
python3 jev_nasdaq_predictor.py
```

### 输出文件

- `runs/<run-id>/jev_request.json`：发送给 JEV 的完整 JSON 输入。
- `runs/<run-id>/jev_response.json`：JEV 原始响应，包括概率、置信度、模型版本和 token 用量。
- `runs/<run-id>/run_metadata.json`：运行时间、基准交易日和运行状态。
- `runs/predictions.jsonl`：每次成功预测的一行记录。后续运行会在下一次收盘数据可用后回填实际方向和 `correct` 结果。

`runs/` 和 Python 缓存已加入 `.gitignore`，不会被提交到 Git。

### 口径和限制

预测目标是“下一次可用的美股常规交易日收盘，相对于最近一次已知 Nasdaq 收盘上涨还是下跌”。周末和美股假期会自动顺延到下一次实际交易日。

这是一个持续测量和校准的实验流程，不保证高准确率。请根据 `predictions.jsonl` 中积累的真实结果，按概率和置信度区间评估效果，再调整输入参数。

## English

This repository contains a Python runner that uses TypeSafe Jev to predict the direction of the Nasdaq Composite.

The current daily schedule at 20:00 Asia/Shanghai is managed by a local Codex automation and is intentionally outside this repository. A clone includes the runner and configuration, but you must configure the API key and scheduler yourself.

Each run:

1. Fetches Nasdaq Composite (`^IXIC`) history.
2. Fetches S&P 500, Nasdaq futures, VIX, the dollar, WTI, Brent, gold, U.S. Treasury yields, and BLS CPI and labor observations.
3. Builds the state sent to Jev.
4. Calls the pinned `jev-1.13.0` model to predict whether the next available U.S. regular-session close will be higher or lower than the latest known close.
5. Stores the complete request, raw Jev response, and an evaluable prediction record.

### Setup

The project uses only the Python standard library. On macOS, store the API key in Keychain:

```bash
security add-generic-password -U -a "$USER" -s typesafe-api-key -w 'your-typesafe-api-key'
```

The script first checks `TYPESAFE_API_KEY`; if it is absent, it reads the Keychain item for the current macOS user. The API key is used only at runtime and is never written to request files, result files, or logs.

On non-macOS systems, provide the key through the environment:

```bash
export TYPESAFE_API_KEY='your-typesafe-api-key'
```

Never commit a real API key, a `.env` file, or generated `runs/` output.

### Usage

Run a dry run to fetch data and save the Jev request without calling Jev:

```bash
python3 jev_nasdaq_predictor.py --dry-run
```

Run a real prediction:

```bash
python3 jev_nasdaq_predictor.py
```

### Output files

- `runs/<run-id>/jev_request.json`: the complete JSON request sent to Jev.
- `runs/<run-id>/jev_response.json`: Jev's raw response, including probabilities, confidence, model version, and token usage.
- `runs/<run-id>/run_metadata.json`: timestamps, baseline session, and run status.
- `runs/predictions.jsonl`: one row per successful prediction. Later runs backfill the actual direction and `correct` after the next close is available.

`runs/` and Python caches are included in `.gitignore` and are not committed to Git.

### Definition and limitations

The target is whether the next available U.S. regular-session close is higher or lower than the latest known Nasdaq close. Weekends and U.S. market holidays advance automatically to the next actual trading session.

This is a measurement and calibration loop, not a guarantee of high accuracy. Use the accumulated outcomes in `predictions.jsonl` to evaluate performance by probability and confidence bucket before changing the input parameters.

## License

MIT. See [LICENSE](LICENSE).
