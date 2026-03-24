# Self-Hosted Runner Setup

The daily digest workflow runs on a self-hosted GitHub Actions runner where Ollama, Kokoro, and ffmpeg are available locally.

## Prerequisites

| Requirement | Install |
|---|---|
| Python 3.11+ | `brew install python@3.11` or system package manager |
| Ollama | [ollama.com](https://ollama.com) — must be running (`ollama serve`) |
| Ollama model | `ollama pull llama3.2:3b` |
| ffmpeg | `brew install ffmpeg` |
| Kokoro / PyTorch | Installed via `pip install -r requirements.txt` |

## Register the Runner

1. Go to your repository on GitHub: **Settings > Actions > Runners > New self-hosted runner**
2. Follow the platform-specific instructions to download and configure the runner:

```bash
# Example for macOS (check GitHub for the latest URL)
mkdir actions-runner && cd actions-runner
curl -o actions-runner-osx-arm64.tar.gz -L <URL_FROM_GITHUB>
tar xzf actions-runner-osx-arm64.tar.gz

./config.sh --url https://github.com/<owner>/voice-news --token <TOKEN>
```

3. Start the runner:

```bash
./run.sh
```

Or install as a service for persistent background operation:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

## Verify

1. Go to **Actions > Daily Voice News** and click **Run workflow**
2. Watch the run logs to confirm all steps pass
3. Check the deployed site at `https://<owner>.github.io/voice-news/`

## Notes

- The runner needs internet access to fetch news sources
- Ollama must be running before the workflow triggers (`ollama serve`)
- The workflow runs daily at 7 AM Pacific (cron: `0 14 * * *` UTC)
- You can trigger it manually anytime via **workflow_dispatch**
