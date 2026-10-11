# iterm-agents

[简体中文](README.md) | [English](README.en.md)

![iterm-agents：五种智能体，一个面板。查看运行状态，跳转到已完成的会话。](docs/promo-iterm-agents.png)

在 iTerm2 工具栏（Toolbelt）中统览 Claude Code、Codex、Cursor Agent、Devin 和 Kimi Code 的会话状态；点击直达对应窗格，随时接手下一步

![完整的 iTerm2 窗口：左侧为终端窗格，右侧为 Agents 面板](docs/iterm-window.png)

## 支持的智能体

| 智能体 | 检测的进程 |
| --- | --- |
| Claude Code | `claude` |
| Codex | `codex` |
| Cursor Agent | `cursor-agent`（或运行其 `index.js` 的 `node` / `agent`） |
| Devin CLI | `devin` |
| Kimi Code | `kimi` / `kimi-code` |

## 功能

- **多窗口**：每个 iTerm2 窗口都有 Agents 面板。
- **实时状态**：`running`（处理中）、`done`（刚完成）、`idle`（空闲）。
- **仓库分组**：worktree 归入主仓库，支持单独或全部折叠。
- **一键跳转**：点击会话，聚焦对应终端窗格。
- **搜索筛选**：按会话、仓库、分支或智能体查找。

所有数据都留在你的 Mac 上。监控程序读取本地进程、Git 仓库和 iTerm2 会话中可见的终端文本；面板服务仅监听 `127.0.0.1`，不会向外部网络发送数据。

## 环境要求

- **macOS 和 [iTerm2](https://iterm2.com/)**；监控程序运行期间需要保持 iTerm2 打开。
- 启用 iTerm2 的 **Python API** 和 **Shell Integration**（[配置步骤](#配置-iterm2)）。
- **Git**：用于获取仓库信息和手动克隆项目。如果 `git --version` 失败，运行 `xcode-select --install`，完成 Apple Command Line Tools 安装后重试。
- Python ≥ 3.10。快捷安装脚本会为你配置 Python 和 **[uv](https://docs.astral.sh/uv/getting-started/installation/)**。
- 至少一个支持的智能体 CLI，需要自行安装并登录。iterm-agents 只监控已有 CLI，不会安装或启动这些智能体。

## 快速开始

配置 iTerm2、运行安装命令、重开 iTerm2，即可使用。

### 配置 iTerm2

打开 iTerm2；如果尚未安装，请从 [iterm2.com](https://iterm2.com/) 下载并移入 **Applications（应用程序）** 文件夹。

1. **启用 Python API**：按 `Cmd+,`，打开 **General → Magic**，勾选 **Enable Python API**。如果提示重启，请重启 iTerm2。
2. **启用 Shell Integration**：选择 **iTerm2 → Install Shell Integration**，按提示完成安装，再按 `Cmd+T` 打开新标签页。这让面板能显示仓库和分支信息。详见 [iTerm2 Shell Integration 指南](https://iterm2.com/documentation-shell-integration.html)。

### 安装

在 iTerm2 标签页中粘贴并执行：

```bash
curl -fsSL https://raw.githubusercontent.com/faithk7/iterm-agents/main/install.sh | bash
```

[安装脚本](install.sh) 会配置 uv、Python 和依赖，并设置随 iTerm2 自动启动。默认安装到 `~/.local/share/iterm-agents`，无需 Homebrew 或 `sudo`。

### 开始使用

1. 安装完成后，按 `Cmd+Q` 退出 iTerm2，再重新打开。
2. 右侧应出现 **Agents** 面板；如果看不到，选择 **View → Show Toolbelt**。
3. 在终端中进入你的项目，运行已安装的 `claude`、`codex` 或其他支持的智能体。面板会显示会话状态，点击即可跳转。

## 安装选项

### 手动启动和更新

手动启动已安装的监控程序：

```bash
"$HOME/.local/share/iterm-agents/venv/bin/iterm-agents"
```

再次运行安装命令即可更新，然后重启监控程序以加载新版本。请保留安装目录，以便 AutoLaunch 正常工作。

如果已经有本地仓库，可以安装本地版本：

```bash
bash install.sh --source .
```

使用 `--no-autolaunch` 可仅保留手动启动。如果已有的 AutoLaunch 脚本与新脚本不同，安装程序会停止，不会覆盖它；确定需要替换时，可以使用 `--force-autolaunch`。例如：

```bash
bash install.sh --source . --no-autolaunch
bash install.sh --source . --force-autolaunch
```

运行 `bash install.sh --help` 可查看所有选项，包括自定义安装目录。

### 使用 uv 手动安装

先完成 [iTerm2 配置](#配置-iterm2)。如果之后要启用自动启动，请将仓库保存在打算长期保留的位置。以下命令都在 iTerm2 中执行。

1. **安装 uv**（如果尚未安装）。使用 Homebrew：

   ```bash
   brew install uv
   ```

   如果不使用 Homebrew，请参考 [uv 安装指南](https://docs.astral.sh/uv/getting-started/installation/)。

2. **克隆、安装并启动监控程序：**

   ```bash
   git clone https://github.com/faithk7/iterm-agents.git
   cd iterm-agents
   uv sync
   uv run iterm-agents
   ```

   保持该命令在标签页或窗格中运行。按 `Ctrl+C` 可停止监控程序。再次启动时，在仓库目录中运行 `uv run iterm-agents`。

**Agents** 面板会在每个窗口的工具栏中打开。如果被隐藏，选择 **View → Show Toolbelt**。

## 确认运行正常

1. 如果在终端中启动监控程序，应看到类似输出：

   ```text
   iterm-agents: running (http://127.0.0.1:50123/)
   iterm-agents: Ctrl+C to stop
   ```

   端口会自动选择，可能与示例不同。自动启动时没有对应的终端输出，可以通过 **Agents** 面板是否出现来确认，也可以运行 `pgrep -fl iterm-agents` 查看监控进程。

2. 按 `Cmd+T` 打开另一个标签页，进入 Git 仓库，启动你已安装的受支持 CLI，例如 `claude` 或 `codex`。
3. 在 **Agents** 中找到该会话。应能看到智能体徽标；启用 Shell Integration 后，还会显示仓库和分支信息。
4. 提交提示词，观察状态变为 **running**，在监控程序检测到当前轮次结束后变为 **done**。点击该行可以聚焦对应窗格，并清除完成标记。检测所用信号见下文。

## 自动启动

macOS 安装脚本默认配置 AutoLaunch。以下命令适用于手动安装；通过安装脚本安装的用户，可以将 `uv run iterm-agents` 替换为 `"$HOME/.local/share/iterm-agents/venv/bin/iterm-agents"`。

确认手动启动正常后，在监控程序所在终端按 `Ctrl+C` 停止运行，再从仓库目录安装 AutoLaunch 启动脚本：

```bash
uv run iterm-agents --install-autolaunch
```

然后退出并重新打开 iTerm2。此后无需保留专门运行监控程序的标签页。

启动脚本位于 `~/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py`，与 it2ag 的自动启动脚本独立。监控程序同时只运行一个实例；再次启动会输出 `iterm-agents: already running` 并退出。

手动使用 uv 安装时，启动脚本会记录仓库的绝对路径，请保留仓库和 `.venv`；使用安装脚本时，则记录已安装可执行文件的绝对路径，请保留安装目录。

如果移动了手动安装的仓库，请在新位置重新创建虚拟环境，再重新安装启动脚本：

```bash
uv run iterm-agents --install-autolaunch --force
```

仅在确定需要替换已有脚本时使用 `--force`。该命令也可以更新旧脚本，让它使用当前安装。

### 关闭自动启动

删除本项目的启动脚本：

```bash
rm "$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py"
```

删除后不会再自动启动，但不会停止已经运行的监控程序。删除后退出并重新打开 iTerm2。仍可使用[安装选项](#安装选项)中的命令手动启动。

## 卸载

按上文删除 AutoLaunch 启动脚本，停止监控程序，然后删除安装目录：

```bash
pkill -f 'bin/iterm-agents'
rm -rf "$HOME/.local/share/iterm-agents"
```

如果使用了 `--install-dir`，请改为自己的安装目录；手动安装则删除仓库目录。uv 可能还在 `~/.local/share/uv` 和 `~/.cache/uv` 中保存下载的 Python 和缓存；仅在没有其他项目使用 uv 时删除这些目录。

## 使用方法

- **done** 表示当前轮次已结束，不代表任务成功；点击会话会清除完成标记。
- 右键点击会话可添加标签或标记为已读。标签在会话或监控程序退出后消失。
- `Cmd+Shift+M` 打开当前窗口的工具栏，并聚焦搜索框。

面板获得焦点后，按 `↑` / `↓` 选择会话，`Enter` 跳转，`Escape` 关闭菜单或返回搜索框。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 面板未显示或加载失败 | 按 `Cmd+Shift+M` 显示面板；仍有问题时，检查 [Python API 设置](#配置-iterm2)并尝试[手动启动](#手动启动和更新)。 |
| 没有仓库或分支 | 启用 Shell Integration，打开新标签页并进入 Git 仓库。 |
| 没有检测到智能体 | 确认受支持的 CLI 正在本地 iTerm2 窗格中运行；不支持 SSH 远程会话或桌面应用。 |
| 状态判断不准 | 检测依赖进程和英文屏幕提示，可能随 CLI 版本变化，见[检测原理](#检测原理)。 |
| `already running` | 监控程序已在运行，直接使用现有面板即可。 |
| 自动启动失败 | 确认安装目录仍在，先尝试手动启动，再按[自动启动](#自动启动)重新安装启动脚本。 |

查看可用命令或版本号：

```bash
uv run iterm-agents --help
uv run iterm-agents --version
```

本地服务默认自动选择可用端口。如果需要固定端口，可以使用 `uv run iterm-agents --port 50123`，请确保该端口未被占用。

## 检测原理

通过本地 CLI 进程识别智能体会话，再结合子进程、系统活动信号和终端屏幕提示判断是否正在处理任务。从运行转为空闲时，显示 **done**。

屏幕提示目前只匹配英文文本，检测结果可能随 CLI 版本变化；不支持 SSH 远程智能体或桌面应用。实现细节见[进程检测](src/iterm_agents/detector.py)和[屏幕信号](src/iterm_agents/screen_signals.py)。

## 开发

```bash
uv run pytest            # 测试
uv run ruff check src/   # lint 检查
uv run mypy src/         # 类型检查（仅 src/；测试使用模拟对象）
```

`uv sync` 以可编辑模式安装项目，修改 `src/` 中的代码后，重启监控程序即可生效。

模块职责、数据流及缓存和焦点状态规则见 [Python 架构说明](docs/architecture.md)。

## 致谢

本项目衍生自 [@mkusaka](https://github.com/mkusaka) 的 [it2ag](https://github.com/mkusaka/it2ag)。复用了其进程扫描、工具栏面板、会话列表、Git 和 worktree 分组、点击聚焦，以及 Claude Code 和 Codex 的活动信号；Cursor Agent、Devin 和 Kimi Code 的检测为本项目新增。详见 [NOTICE](NOTICE)。

## 许可证

GPL-2.0。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
