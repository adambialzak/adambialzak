# quant_agent — Autonomous Research-Driven Paper Trading Platform

> **Not financial advice.** This is an educational and research tool.  
> Read the disclaimer printed at every startup before using.

---

## What this is

A multi-agent equity trading platform in Python that:

1. **Researches** stocks from a watchlist (fetches history + fundamentals, computes numeric features)
2. **QA-vets** every thesis independently with a deterministic adversarial agent
3. **Sizes positions** under hard, auditable risk limits
4. **Executes** on a $10,000 paper account (or Webull UAT/live behind multiple opt-ins)
5. **Persists** every decision, fill, and equity snapshot to SQLite for full auditability
6. Runs as an **unattended daemon** (`run` subcommand) indefinitely

---

## Architecture

```
watchlist
  → ResearchAgent  (fetch + features + Reasoner thesis)
  → QAAgent        (independent, deterministic: APPROVE / REVISE / REJECT)
  → RiskManager    (fixed-fractional sizing; 7 hard limits enforced)
  → Broker         (PaperBroker with slippage/spread/commission; or Webull)
  → Store          (SQLite: decisions, fills, equity)
```

**Swap points** (change one string in Config or env vars):

| Role | Offline default | Real alternative |
|------|----------------|-----------------|
| Data | `sample` (synthetic GBM) | `yfinance` |
| Reasoner | `heuristic` (rule-based, auditable) | `anthropic` (Claude, grounded in features) |
| Broker | `paper` (PaperBroker with friction) | `webull` (OpenAPI) |

---

## Quick start (fully offline, zero dependencies)

```bash
git clone <repo>
cd adambialzak

# One cycle
python -m quant_agent.cli cycle

# Bounded walk-forward simulation (40 cycles)
python -m quant_agent.cli simulate --cycles 40

# Continuous daemon for 30 cycles at 1-second interval
python -m quant_agent.cli run --interval 1 --max-cycles 30 --report-every 15

# Print performance from the database
python -m quant_agent.cli report

# Show open positions and recent decisions
python -m quant_agent.cli status
```

Press **Ctrl-C** during `run` to trigger a graceful shutdown (finishes the current cycle, prints a final report, exits 0).

---

## Tests

```bash
python tests/test_paper_broker.py
python tests/test_risk.py

# Or with pytest
pip install pytest
pytest tests/
```

---

## Wiring real data (yfinance)

```bash
pip install yfinance
QA_DATA_PROVIDER=yfinance python -m quant_agent.cli cycle
```

---

## Wiring LLM reasoning (Anthropic)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
QA_REASONER=anthropic python -m quant_agent.cli cycle
```

The LLM receives only pre-computed numeric features — it cannot invent prices.
Entry, stop, and target always come from the heuristic baseline.  On any
network or parse error the system falls back to the heuristic automatically.

---

## Wiring Webull (UAT to production)

### UAT (paper account on Webull infrastructure)

```bash
pip install webull-openapi-python-sdk
export QA_WEBULL_APP_KEY=...
export QA_WEBULL_APP_SECRET=...
export QA_WEBULL_ACCOUNT_ID=...
export QA_WEBULL_REGION=US
QA_BROKER=webull python -m quant_agent.cli cycle
```

### Production (real money — two-factor opt-in required)

Both of the following must be satisfied simultaneously:

1. Pass `--live` flag (triggers interactive confirmation prompt)
2. Set `QA_WEBULL_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`

```bash
export QA_WEBULL_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY
python -m quant_agent.cli --live run --interval 60
# You will be prompted to type "I_UNDERSTAND_REAL_MONEY" interactively
```

---

## Always-on daemon (systemd)

```bash
sudo cp quant-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable quant-agent
sudo systemctl start quant-agent
journalctl -u quant-agent -f
```

See `quant-agent.service` for environment variable configuration.

---

## Pre-live checklist

Before risking real money, work through this list:

- [ ] Forward-test on Webull UAT for at least several weeks
- [ ] After costs, confirm the strategy beats buy-and-hold SPY over the same period
- [ ] Stress-test with pessimistic cost assumptions (double the slippage)
- [ ] Size very small on first live trades to validate execution
- [ ] Understand PDT (Pattern Day Trader) rules if trading under $25k
- [ ] Understand wash-sale rules before year-end tax filing
- [ ] Consult a tax professional

---

## Honest caveats

- **A long-running paper daemon is forward-testing, not proof of edge.**
- **Risk and return trade off.** The system bounds risk; it does not eliminate it.
- **The heuristic has no predictive edge by construction** — it was not fit to historical data.
- **Synthetic data is not calibrated to real markets.** It exists only for offline demonstration.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QA_STARTING_CASH` | 10000 | Initial paper account balance |
| `QA_DATA_PROVIDER` | sample | `sample` or `yfinance` |
| `QA_REASONER` | heuristic | `heuristic` or `anthropic` |
| `QA_BROKER` | paper | `paper` or `webull` |
| `QA_ANTHROPIC_MODEL` | claude-sonnet-4-6 | Anthropic model ID |
| `QA_WATCHLIST` | AAPL,MSFT,... | Comma-separated symbol list |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic` reasoner |
| `QA_WEBULL_APP_KEY` | — | Required for `webull` broker |
| `QA_WEBULL_APP_SECRET` | — | Required for `webull` broker |
| `QA_WEBULL_ACCOUNT_ID` | — | Required for `webull` broker |
| `QA_WEBULL_REGION` | US | Webull region |
| `QA_WEBULL_LIVE_CONFIRM` | — | Must be `I_UNDERSTAND_REAL_MONEY` for production |
