# Kimi Code ACP Client Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KIMI_CODE_ACP_FIRST` | `0` | Set to `1` to make `_safe_llm_invoke` try ACP before the configured provider. |
| `KIMI_CODE_ACP_COMMAND` | `~/.kimi-code/bin/kimi acp` | Command used to launch the ACP subprocess. |
| `KIMI_CODE_ACP_CWD` | `/home/ubuntu/learning-investment-strategies` | Working directory for the ACP subprocess and new sessions. |
| `KIMI_CODE_ACP_TIMEOUT` | `300` | Maximum seconds to wait for a single ACP turn. |
| `KIMI_CODE_ACP_PERMISSION_MODE` | `yolo` | ACP permission mode; use `manual` or `auto` if you need interactive approvals. |

## Migration from `kimi -p`

The old `kimi-code-cli` provider passed the prompt as a command-line argument,
which hit OS `ARG_MAX` limits on large prompts. The new `kimi-code-acp` provider
spawns an independent `kimi acp` subprocess and sends prompts via JSON-RPC over
stdio, avoiding argv limits entirely.

To enable:

```bash
export KIMI_CODE_ACP_FIRST=1
```

To keep using the old CLI:

```bash
export KIMI_CODE_CLI_FIRST=1
```

Both fall back to the configured API provider on failure.
