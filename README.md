# iterm-agents

[简体中文](README.md) | [English](README.en.md)

![iterm-agents：五种智能体，一个面板。查看运行状态，跳转到已完成的会话。](docs/promo-iterm-agents.png)

一个 iTerm2 工具栏（Toolbelt）面板，用于监控终端会话中的编程智能体：Claude Code、Codex、Cursor Agent、Devin 和 Kimi Code。你可以一眼看到哪个会话还在处理当前任务、哪个刚刚完成，再点击跳转到对应的终端窗格。

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

- **每个窗口都有 Agents 面板**：监控程序启动时会在已有窗口中打开面板，之后新开的窗口也会自动打开；手动隐藏的工具栏会保持隐藏。
- **显示每个会话的实时状态**：正在处理当前任务时显示 `running`，刚结束时显示 `done`，其余时间显示 `idle`。
- **按仓库分组**：根据 Git 仓库归类会话，worktree 会归入主仓库；可以单独折叠分组，也可以一次折叠全部分组。
- **跳转到会话**：点击一行即可聚焦对应的终端窗格。
- **搜索**：按会话名称、仓库、分支或智能体类型筛选。

所有数据都留在你的 Mac 上。监控程序读取本地进程、Git 仓库和 iTerm2 会话中可见的终端文本；面板服务仅监听 `127.0.0.1`，不会向外部网络发送数据。

## 环境要求

- **macOS 和 [iTerm2](https://iterm2.com/)**；监控程序运行期间需要保持 iTerm2 打开。
- 启用 iTerm2 的 **Python API** 和 **Shell Integration**（[配置步骤](#配置-iterm2)）。
- **Git**：用于获取仓库信息和手动克隆项目。如果 `git --version` 失败，运行 `xcode-select --install`，完成 Apple Command Line Tools 安装后重试。
- Python ≥ 3.10。快捷安装脚本会为你配置 Python 和 **[uv](https://docs.astral.sh/uv/getting-started/installation/)**。
- 至少一个支持的智能体 CLI，需要自行安装并登录。iterm-agents 只监控已有 CLI，不会安装或启动这些智能体。

## 快速开始

### 配置 iTerm2

两种安装方式都需要以下设置。按 `Cmd+Space`，输入 `iTerm`，然后按 `Enter` 打开 iTerm2。如果尚未安装，请从 [iterm2.com](https://iterm2.com/) 下载并移入 **Applications（应用程序）** 文件夹，然后：

1. **启用 Python API**：按 `Cmd+,`，打开 **General → Magic**，勾选 **Enable Python API**。如果提示重启，请重启 iTerm2。
2. **启用 Shell Integration**：选择 **iTerm2 → Install Shell Integration**，按提示完成安装，再按 `Cmd+T` 打开新标签页。它会报告各会话的工作目录，用于显示仓库、分支和分组。在 iTerm2 3.5 及以上版本中，如果使用受支持的登录 shell，也可以启用 **Settings → Profiles → General → Command → Load shell integration automatically**。详见 [iTerm2 Shell Integration 指南](https://iterm2.com/documentation-shell-integration.html)。

### macOS 安装脚本（推荐）

在 iTerm2 标签页中粘贴并执行：

```bash
curl -fsSL https://raw.githubusercontent.com/faithk7/iterm-agents/main/install.sh | bash
```

[安装脚本](install.sh) 会下载项目，复用已有的 uv 或安装 uv，配置 Python 3.12 和监控程序的依赖，并安装 AutoLaunch 启动脚本。它不会修改 shell 配置文件，默认安装到 `~/.local/share/iterm-agents`，无需 Homebrew 或 `sudo`。

安装完成后，退出并重新打开 iTerm2。**Agents** 面板应出现在工具栏中。如果面板被隐藏，选择 **View → Show Toolbelt**。

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

### 另一种方式：venv 和 pip

如果更习惯 pip，请使用 3.10 或更高版本的 `python3`。以下命令可完整替代上面的 uv 安装步骤：

```bash
git clone https://github.com/faithk7/iterm-agents.git
cd iterm-agents
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/iterm-agents
```

无需激活虚拟环境。后续命令中的 `uv run iterm-agents` 可以替换为 `.venv/bin/iterm-agents`。

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

如果使用 pip 安装，则运行 `.venv/bin/iterm-agents --install-autolaunch`。然后退出并重新打开 iTerm2。此后无需保留专门运行监控程序的标签页。

启动脚本位于 `~/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py`，与 it2ag 的自动启动脚本独立。监控程序同时只运行一个实例；再次启动会输出 `iterm-agents: already running` 并退出。

uv 安装方式会记录仓库的绝对路径；pip 安装方式会记录已安装可执行文件的绝对路径。请保留仓库和 `.venv`。如果移动了它们，请在新位置重新创建虚拟环境，再重新安装启动脚本：

```bash
uv run iterm-agents --install-autolaunch --force
```

仅在确定需要替换已有脚本时使用 `--force`。该命令也可以更新旧脚本，让它使用当前安装。

### 关闭自动启动

删除本项目的启动脚本：

```bash
rm "$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py"
```

删除后不会再自动启动，但不会停止已经运行的监控程序。删除后退出并重新打开 iTerm2。仍可使用快速开始中的命令手动启动。

## 卸载

按上文删除 AutoLaunch 启动脚本，停止监控程序，然后删除安装目录：

```bash
pkill -f 'bin/iterm-agents'
rm -rf "$HOME/.local/share/iterm-agents"
```

如果使用了 `--install-dir`，请改为自己的安装目录；手动安装则删除仓库目录。uv 可能还在 `~/.local/share/uv` 和 `~/.cache/uv` 中保存下载的 Python 和缓存；仅在没有其他项目使用 uv 时删除这些目录。

## 使用方法

- 每行显示带颜色的智能体徽标和状态：**running**（运行中）、**done**（刚完成）或 **idle**（空闲）。未检测到智能体的行只显示会话名称。
- **Done** 表示监控程序观察到从运行转为空闲，不代表任务成功；请查看智能体输出，确认是否有错误或待回答的问题。监控程序启动之前已结束的轮次不会显示完成标记。
- 点击一行即可跳转到对应终端窗格；点击已完成的行会清除其完成标记。
- 每个窗口的面板用蓝色标记表示该窗口当前活动的窗格。切换窗口不会改变其他面板的标记或滚动位置。
- 右键点击会话卡片可打开菜单：添加标签、聚焦会话或标记为已读。标签显示在卡片顶部，会保留到会话或监控程序退出。
- 顶部按钮：`✓` 将所有已完成会话标记为已读，`⊏` 折叠或展开全部仓库分组，`↻` 刷新。
- `Cmd+Shift+M` 打开当前窗口的工具栏，并聚焦搜索框。

面板获得焦点后，可以使用键盘导航：

| 按键 | 操作 |
| --- | --- |
| `↑` / `↓` | 在可见的会话行之间移动；在第一行按 `↑` 返回搜索框 |
| `Enter` | 聚焦选中的终端窗格 |
| `Escape` | 返回搜索框并选中其中的文本；关闭已打开的右键菜单或标签编辑框 |

搜索会匹配会话名称、仓库名称、分支、路径和智能体类型。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| `uv: command not found` | 按快速开始安装 uv。如果安装时修改了 `PATH`，请打开新的终端标签页。 |
| 安装程序提示 Git 未就绪 | 运行 `xcode-select --install`，完成 Apple Command Line Tools 安装后重新运行安装程序。 |
| 安装程序拒绝使用不受管理的目录 | 使用 `--install-dir` 指定另一个专用目录。安装程序会保护并非由它创建的已有目录。 |
| 无法连接 iTerm2 | 保持 iTerm2 打开，启用 **Settings → General → Magic → Enable Python API**，如有提示则重启 iTerm2。 |
| 没有 Agents 面板 | 将 iTerm2 切到前台，选择 **View → Show Toolbelt** 或按 `Cmd+Shift+M`。检查监控程序是否输出了 `running`。 |
| 没有仓库或分支信息 | 为该会话的配置或 shell 启用 Shell Integration，打开新标签页并进入 Git 仓库。仓库之外的会话不会显示仓库或分支标签。 |
| 会话没有智能体徽标 | 在对应的 iTerm2 窗格中运行受支持的 CLI。检测只扫描本地进程，无法检测通过 SSH 在远程主机上运行的智能体，也不会检测桌面应用。 |
| 智能体工作时仍显示 idle，或过早显示 done | 活动检测依赖进程和屏幕提示，不同 CLI 版本可能不同。目前屏幕提示只匹配英文界面文本。详见[检测原理](#检测原理)。 |
| `iterm-agents: already running` | 已有监控程序在运行，可能由 AutoLaunch 启动。直接使用它的面板；如需启动另一个实例，先在手动运行的实例所在终端按 `Ctrl+C` 停止它。 |
| `Failed to load sessions` | `TypeError: Load failed` 表示监控程序未运行；使用 `pgrep -fl iterm-agents` 检查。其他情况请查看监控程序终端中的错误。重启后点击面板的 `↻` 按钮。 |
| 面板没有蓝色标记 | 将该窗口切换为活动的 iTerm2 窗口一次，或点击其面板内部。随后面板会跟踪该窗口的活动窗格。 |
| AutoLaunch 没有启动 | 先尝试手动启动，确认保存的仓库或可执行文件路径及 `.venv` 仍存在。在可正常运行的安装中使用 `--install-autolaunch --force` 重新安装启动脚本。 |
| 安装启动脚本时提示文件已存在且内容不同 | 检查错误信息给出的脚本路径。确定需要替换时使用 `--force`。 |

查看可用命令或版本号：

```bash
uv run iterm-agents --help
uv run iterm-agents --version
```

本地服务默认自动选择可用端口。如果需要固定端口，可以使用 `uv run iterm-agents --port 50123`，请确保该端口未被占用。

## 检测原理

通过[支持的智能体](#支持的智能体)中列出的进程识别会话。以下信号会被判定为 **running**：

| 智能体 | 运行信号 |
| --- | --- |
| Claude Code | `caffeinate` 子进程，与 it2ag 使用的信号相同 |
| Codex | 沙箱子进程、IOKit 断言 `Codex is running an active turn`，或屏幕提示 |
| Cursor Agent | 正在工作的子进程，或屏幕提示 |
| Devin CLI | 正在工作的子进程，或屏幕提示 |
| Kimi Code | 正在工作的子进程，或屏幕提示 |

Cursor 编辑器（`Cursor.app`）、Kimi 桌面应用和 `kimi-cu` 不会被视为 CLI。Cursor Agent 使用私有的 `node` 可执行文件，其命令行必须同时包含 `/cursor-agent/` 和 `index.js`；没有这些路径的单独 `agent` 进程会被忽略。

Cursor Agent、Devin 和 Kimi Code 没有提供类似 Claude 或 Codex 的轮次信号，因此在没有工作中的子进程时，会回退到检查会话屏幕。提示必须位于当前输入区域上方，以避免将历史输出中的相同文本误判为当前状态。所有提示均为英文界面文本，使用本地化版本时可能无法检测。具体屏幕提示如下：

- **Cursor**：输入区域显示 `ctrl+c to stop`，且屏幕持续变化；只有旋转指示器时，也会继续将暂时没有输出的会话视为运行中。底部提示连续 30 秒没有变化时，视为已结束。
- **Devin**：输入框上方显示 `esc twice/again to interrupt`。
- **Codex**：`›` 输入区域或 `? for shortcuts` 底部提示上方显示 `esc to interrupt`；用于覆盖禁用沙箱、没有子进程或 IOKit 断言的启动方式。面板会等待约三秒的空闲状态再显示 **done**，短暂停顿期间仍显示 **running**。
- **Kimi**：显示 `Working…` / `Prompting…` / `Orchestrating…` / `Queued…` / `Rate limited…` / `Thinking…` 状态，或在工具运行时显示旋转指示器和 `· Tip:` 行。`Completed.` / `Failed.` / `Aborted.` / `Cancelled.` 不算运行信号。

## 开发

```bash
uv run pytest            # 测试
uv run ruff check src/   # lint 检查
uv run mypy src/         # 类型检查（仅 src/；测试使用模拟对象）
```

`uv sync` 以可编辑模式安装项目，修改 `src/` 中的代码后，重启监控程序即可生效。

## 致谢

本项目衍生自 [@mkusaka](https://github.com/mkusaka) 的 [it2ag](https://github.com/mkusaka/it2ag)。复用了其进程扫描、工具栏面板、会话列表、Git 和 worktree 分组、点击聚焦，以及 Claude Code 和 Codex 的活动信号；Cursor Agent、Devin 和 Kimi Code 的检测为本项目新增。详见 [NOTICE](NOTICE)。

## 许可证

GPL-2.0。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
