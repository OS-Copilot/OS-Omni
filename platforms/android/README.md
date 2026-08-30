# Android 平台

## 2026-04-27 近期 Android 变更和运行注意事项

这一节记录指定的两次 Android 相关提交、当前工作区新增内容、需要准备的环境，以及长跑 Android benchmark 时容易踩的坑。

### 相关两次提交

- `4aaf9ae3 finished all android single tasks`：补齐 Android 单应用任务包和基础支撑：
  - 新增 Fossify Calendar 任务：`fossify_calendar_create_event_easy`、`fossify_calendar_update_and_followup_hard`、`fossify_calendar_reorganize_schedule_hard`。
  - 新增 OpenShop 任务：`openshop_add_coffee_to_cart`、`openshop_office_setup_checkout`、`openshop_home_refresh_checkout`。
  - 新增 `initializers/android/fossify_calendar.py`、`evaluators/android/fossify_calendar.py`、`initializers/android/openshop.py`、`evaluators/android/openshop.py` 和 `platforms/android/openshop_support.py`。
  - 新增 OpenShop/Fossify Calendar execution 包、Android smoke execution，以及对应 manual init/eval 和单测脚本。
  - 调整 OpenShop Android app 构建和前端实现，并更新 Android CLI/controller/runner 的部分支持逻辑。
  - 该提交曾改到 `core/llm/providers/base.py` 和 `configs/models.yaml`；当前工作区里 `core/llm` 相关文件没有额外未提交改动。
- `ad40eaba add android cross-app tasks`：新增两组 Android 跨应用任务和对应 initializer/evaluator/manual eval 脚本：
  - Email + Office/Markor：`email_office_send_document_code_easy`、`email_office_update_status_from_email_hard`、`email_office_compile_brief_and_reply_hard`。
  - Calendar + OpenShop：`calendar_shopping_add_calendar_item_easy`、`calendar_shopping_office_order_followup_hard`、`calendar_shopping_home_delivery_reminder_hard`。
  - 新增 `initializers/android/email_office_cross_app.py`、`evaluators/android/email_office_cross_app.py`、`initializers/android/calendar_shopping_cross_app.py`、`evaluators/android/calendar_shopping_cross_app.py`。
  - 新增 `tests/manual_android_cross_app_init_eval.py`，用于人工验证这些跨应用任务的 init/eval。
  - 注意：该提交里 `_evaluator/office_brief.md` 和 `_evaluator/office_status.md` 是人工验证过程产生的临时抽取文件，后续已把 `_evaluator/` 整体加入 `.gitignore`。

### 最近一次提交之后的当前改动

- Android task YAML 做了一轮命名整理：
  - 去掉部分旧文件名里的 `android_` 前缀，例如 `android_calculator_addition.yaml` -> `calculator_addition.yaml`。
  - 跨应用任务统一加 `cross_app_` 前缀，例如 `email_office_send_document_code_easy.yaml` -> `cross_app_email_office_send_document_code_easy.yaml`。
  - 对应更新了 `executions/android/android_*.yaml`、`tests/manual_android_cross_app_init_eval.py`、`tests/test_run_android_task_trials.py` 中的路径引用。
- 新增全量 Android execution：
  - `executions/android/android_main_screenshot_pyautogui_gpt5_4.yaml`
  - 包含当前 `tasks/android/*.yaml` 下 49 个任务。
  - 配置为 `models: [free_codesonline_gpt5_4_responses]`、`action_mode: code_adapter`、`observation_mode: screenshot_only`。
- Calculator 支持 Fossify Calculator：
  - `initializers/android/open_app.py` 增加 `calculator -> org.fossify.math` 映射。
  - `evaluators/android/calculator_addition.py` 允许 Fossify Calculator 主结果控件 `:id/result`，不再只接受 Google Calculator 的 `result_preview`。
- Oinkoin initializer 更稳：
  - `platforms/android/oinkoin_support.py` 在 UI seeding 失败时 fallback 到直接 SQLite 注入。
  - 避免 `dumpsys window` 卡住，改用更轻的 app ready 检查路径。
- Organic Maps 跨应用任务更稳：
  - `initializers/android/calendar_map_deltachat.py` 支持从宿主机下载/缓存 Organic Maps `.mwm` 地图文件，再 `adb push` 到 app 内部目录。
  - 使用 APK 内 `assets/countries.txt` 的版本和 SHA1 校验，当前验证过的地图版本是 `260404`。
  - 默认准备 `World.mwm`、`WorldCoasts.mwm`、`Monaco.mwm`，本地缓存目录为 `.cache/organicmaps/260404/`。
  - Fossify Calendar 事件初始化改为后台 SQLite 注入，避免 UI 填表太慢。
- `.gitignore` 已从只忽略 `_evaluator/*.odt` 改为忽略整个 `_evaluator/`。
- Android runner 日志增强：
  - `platforms/android/runners/base_episode.py` 在 LLM provider error 时会打印具体错误文本，方便定位网络/代理/API 错误。

### 新增或重命名后的 Android 任务包

- Email + Markor/Office 跨应用：
  - `tasks/android/cross_app_email_office_send_document_code_easy.yaml`
  - `tasks/android/cross_app_email_office_update_status_from_email_hard.yaml`
  - `tasks/android/cross_app_email_office_compile_brief_and_reply_hard.yaml`
- Calendar + OpenShop 跨应用：
  - `tasks/android/cross_app_calendar_shopping_add_calendar_item_easy.yaml`
  - `tasks/android/cross_app_calendar_shopping_office_order_followup_hard.yaml`
  - `tasks/android/cross_app_calendar_shopping_home_delivery_reminder_hard.yaml`
- Fossify Calendar + Organic Maps + Delta Chat：
  - `tasks/android/cross_app_fossify_maps_deltachat_send_cafe.yaml`
- 其他重命名后的任务：
  - `tasks/android/calculator_addition.yaml`
  - `tasks/android/libreoffice_viewer_mark.yaml`
  - `tasks/android/libreoffice_status_report_update.yaml`
  - `tasks/android/libreoffice_notes_append_hard.yaml`
  - `tasks/android/spotube_search_artist_play_attempt.yaml`
  - `tasks/android/spotube_profile_setup.yaml`
  - `tasks/android/spotube_queue_naina_zara.yaml`

### 需要准备的 Android app 和宿主机服务

已知会被当前 Android 全量 execution 用到的 app/服务：

- Android SDK / ADB / AVD：默认 `emulator-5554`，AVD 名称见 `configs/android.yaml`。
- Fossify Calendar：`org.fossify.calendar`。
- Fossify Calculator：`org.fossify.math`。
- Delta Chat：`chat.delta`。
- K-9 Mail：`com.fsck.k9`，需要连接宿主机 GreenMail。
- Markor：`net.gsantner.markor`。
- OpenShop：`com.killt.openshop`。
- Organic Maps：`app.organicmaps.web`。
- Oinkoin：当前任务依赖已安装的 Oinkoin app。
- Fossify Gallery：`org.fossify.gallery`。
- Material Files：`me.zhanghai.android.files`。
- Tasks.org：`org.tasks`。
- LibreOffice Viewer：`org.documentfoundation.libreoffice`。
- Spotube：`oss.krtirtho.spotube`。

GreenMail 要在宿主机运行，K-9、Delta Chat 和 Email+Markor 相关任务会用到：

```powershell
docker ps
```

通常需要暴露这些端口：

- SMTP: `3025`
- IMAP: `3143`
- API: `8081`

Android 模拟器访问宿主机时使用 `10.0.2.2`，脚本里也可能使用 `adb reverse tcp:3025 tcp:3025` 和 `adb reverse tcp:3143 tcp:3143`。

### K-9 / Delta Chat 通信状态恢复

长跑 Android execution 前，建议先恢复 K-9 和 Delta Chat 的已配置账户状态，避免每个任务重新走 UI onboarding：

```powershell
python scripts\bootstrap_android_comm_state.py --apps k9 deltachat --restore-only
```

这条命令会从本地 `assets/android_comm_state/` 模板恢复应用数据。该目录不随核心仓库版本提交；首次使用需要先运行不带 `--restore-only` 的 bootstrap，或使用 `--refresh` 重新生成本地模板。

### LLM 和 PowerShell 运行环境

如果当前 Python 环境没有安装 `python-dotenv`，`.env` 不会自动加载。可以在运行 execution 前把 `.env` 注入当前 PowerShell 进程：

```powershell
cd D:\桌面\gui\HelloWorld

Get-Content .env | Where-Object { $_ -match '^\s*[^#][^=]*=' } | ForEach-Object {
  $name, $value = $_ -split '=', 2
  [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
}
```

本机上曾遇到 `httpx` 读取环境代理后报 `[Errno 0] Error`，而同一个 endpoint 用 `urllib` 可以连通。若出现 `PROVIDER_REQUEST_FAILED`，先在同一个 PowerShell 里禁用代理环境：

```powershell
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY, Env:http_proxy, Env:https_proxy, Env:all_proxy -ErrorAction SilentlyContinue
$env:NO_PROXY="*"
$env:no_proxy="*"
```

然后再运行全量 Android execution：

```powershell
python -m platforms.android.cli --execution executions\android\android_main_screenshot_pyautogui_gpt5_4.yaml
```

如果只想检查 execution YAML 是否能加载，不实际跑任务：

```powershell
python scripts\run_benchmark.py --execution executions\android\android_main_screenshot_pyautogui_gpt5_4.yaml
```

### 长跑注意事项

- 不要让电脑睡眠/休眠。睡眠或休眠会中断 Python、ADB、Docker/GreenMail 和 emulator。
- 插电时可临时禁用关屏和睡眠：

```powershell
powercfg /change monitor-timeout-ac 0
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

- 如果是笔记本合盖长跑，插电时合盖动作设为不操作：

```powershell
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
```

- 关屏通常不影响 ADB 从 Android framebuffer 截图，但锁屏/睡眠可能影响 emulator 渲染稳定性。长跑时更推荐保持登录状态，或使用 PowerToys Awake。
- `.env`、`.env.backup`、`.cache/`、`_evaluator/` 不应提交。`.env.backup` 里如果有真实 API key，提交前务必确认已被 `.gitignore` 排除或手动移除。
- Organic Maps 地图由宿主机下载再推入模拟器。若 app 仍提示下载世界地图，优先检查 `/data/data/app.organicmaps.web/files/<version>/` 下 `.mwm` 文件的 owner 和 SELinux context，而不是外部存储目录。

Android platform support for OS-Omni follows the existing execution/task/result protocol.

## 架构

- Host runner 通过 ADB 与 Android 模拟器/真机通信（不同于 Windows/Linux 的 HTTP Guest Runtime 架构）
- ADB Controller 提供截屏、UI 层级树、触控、滑动、文本输入、按键等操作
- Host 侧复用 OS-Omni 共享的 LLM、Prompt、Runner、Initializer、Evaluator 协议

## 前置条件

- Android SDK（包含 `adb` 和 `emulator`）
- 一个可用的 AVD（默认使用 `AndroidWorldAvd`）
- Python 3.12

## 快速开始

### 1. 配置

编辑 `configs/android.yaml`:

```yaml
adb_device: "emulator-5554"
avd_name: "AndroidWorldAvd"
auto_launch_emulator: true
emulator_boot_timeout: 120
```

### 2. 配置模型密钥

Android execution 现在默认走仓库内置的 `free_codesonline_gpt5_4_responses` 模型配置。它通过 `FREE_CODESONLINE_BASE_URL` 指向远端 OpenAI-compatible endpoint，当前推荐值是：

```text
https://mx.free.codesonline.dev/v1
```

因此至少要在 shell 环境，或者一个本地忽略文件里配置：

```
FREE_CODESONLINE_API_KEY=sk-...
FREE_CODESONLINE_BASE_URL=https://mx.free.codesonline.dev/v1
```

如果你沿用仓库提供的 `executions/android*.yaml`，通常**不需要**再设置 `OPENAI_API_KEY` / `OPENAI_BASE_URL`，因为 Android 专用 execution 已经统一绑定到 `free_codesonline_gpt5_4_responses`，读取的是 `FREE_CODESONLINE_*` 这组环境变量。

一个方便的本地做法是把它们写到 gitignored 的 `.omx/context/android-benchmark-provider.env`，然后执行：

```bash
source .omx/context/android-benchmark-provider.env
```

### 3. 运行实验

```bash
python -m platforms.android.cli --execution executions/android/android_main_screenshot_pyautogui_gpt5_4.yaml
```

这是 Android 平台当前推荐的入口。`executions/android/android_main_screenshot_pyautogui_gpt5_4.yaml` 现在包含 **27 个任务**，覆盖：

- baseline/system smoke：Contacts / Clock / Bluetooth / Markor
- Material Files 三任务包
- Fossify Gallery 三任务包
- Tasks.org 三任务包
- Oinkoin 五任务本地记账包
- K-9 Mail 发信场景
- K-9 Mail 手动 IMAP/SMTP 配置并发信场景
- Delta Chat 六任务包
- Fossify Calendar + Organic Maps + Delta Chat 跨应用场景

目前仓库里的 Android 真模型 execution 已统一切到 `free_codesonline_gpt5_4_responses`，也就是默认使用远端 GPT-5.4 Responses API 路径；动作模式统一为 `code_adapter`，观测模式统一收敛为 `screenshot_only`，不再把 a11y tree 作为 Android 默认 benchmark 输入。

如果只是第一次验证 Android 链路，建议先跑单任务 execution：

```bash
python -m platforms.android.cli --execution executions/android/android_material_files_create_folder.yaml
python -m platforms.android.cli --execution executions/android/android_material_files_create_folder.yaml
python -m platforms.android.cli --execution executions/android/android_tasks_org_create_task_with_note.yaml
python -m platforms.android.cli --execution executions/android/android_oinkoin_edit_expense.yaml
python -m platforms.android.cli --execution executions/android/android_k9_send_email.yaml
python -m platforms.android.cli --execution executions/android/android_deltachat_send_message.yaml
```

### 4. 本地 Smoke 测试

```bash
python -m platforms.android.local_smoke
```

单任务测试:

```bash
python -m platforms.android.local_smoke --task tasks/android/clock_stopwatch_running.yaml
```

## 新增的本地 app pack

这轮 Android 扩展新增了三个**完全离线、可 deterministic 评测**的 app family：

1. **Material Files**
2. **Fossify Gallery**
3. **Tasks.org**

它们都不依赖公网账号体系，最终真值分别落在共享存储或本地 SQLite 上，更适合做稳定 benchmark。

### Material Files

- `android.material_files.create_folder`
- `android.material_files.rename_file`
- `android.material_files.organize_file`

这组任务统一使用 `/sdcard/Documents/bench_files_lab` 作为 benchmark workspace，evaluator 直接检查共享存储中的最终路径状态。

### Fossify Gallery

- `android.fossify_gallery.delete_photo`
- `android.fossify_gallery.rename_photo`
- `android.fossify_gallery.move_rename_photo`

这组任务统一使用 `/sdcard/Pictures/bench_gallery_lab` 作为 seeded media workspace，evaluator 直接检查照片是否出现在预期文件夹、是否使用预期文件名。

### Tasks.org

- `android.tasks_org.create_task_with_note`
- `android.tasks_org.create_task_with_due_date`
- `android.tasks_org.create_task_with_subtasks`

这组任务统一通过 Tasks.org 本地数据库判定最终状态。当前使用的真值库路径是：

```text
/data/user/0/org.tasks/databases/database
```

而不是旧的 `tasks.db`。

### 已观测到的 live step counts

下面这组步数来自当前仓库版本在 `emulator-5556` 上，用 `free_codesonline_gpt5_4_responses`（GPT-5.4 + remote Responses API）跑 focused execution 时实际观测到的 step 数。它们会写进 task metadata 的 `observed_agent_steps` 字段，便于后续重新校准难度标签。

| App | Task ID | 设计难度标签 | Observed agent steps |
| --- | --- | --- | --- |
| Material Files | `android.material_files.create_folder` | easy | 5 |
| Material Files | `android.material_files.rename_file` | medium | 10 |
| Material Files | `android.material_files.organize_file` | hard | 23 |
| Fossify Gallery | `android.fossify_gallery.delete_photo` | easy | 4 |
| Fossify Gallery | `android.fossify_gallery.rename_photo` | medium | 12 |
| Fossify Gallery | `android.fossify_gallery.move_rename_photo` | hard | 28 |
| Tasks.org | `android.tasks_org.create_task_with_note` | easy | 5 |
| Tasks.org | `android.tasks_org.create_task_with_due_date` | medium | 10 |
| Tasks.org | `android.tasks_org.create_task_with_subtasks` | hard | 28 |

也就是说，这三个 app pack 当前已经形成了 `easy / medium / hard` 的**任务设计梯度**，但如果后续你们要完全按实测步数或成功率重新定义难度，可以直接复用这里的观测值做后处理。

## K-9 邮件任务

`android.k9.send_email` 是一个带副作用的真实邮件发送任务，但它不依赖真实公网邮箱。它通过 K-9 Mail 发送邮件到宿主机上的 GreenMail，再由 evaluator 直接查询 GreenMail API 判定是否送达。

### 一次性环境准备

1. 启动 GreenMail

优先直接用仓库脚本：

```bash
bash scripts/start_greenmail.sh
```

这个脚本会自动选择 `podman` 或 `docker`，重复执行会覆盖同名容器，并等待 `http://127.0.0.1:8081/api/service/readiness` 返回成功。

如果你需要手工起容器，也可以等价执行：

```bash
podman run -d --name greenmail-bench --replace \
  -e GREENMAIL_OPTS='-Dgreenmail.setup.test.smtp -Dgreenmail.setup.test.imap -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.users=benchsender:benchpass@example.test,benchrecv:benchpass@example.test -Dgreenmail.users.login=email -Dgreenmail.verbose' \
  -p 3025:3025 \
  -p 3143:3143 \
  -p 8081:8080 \
  docker.io/greenmail/standalone:2.1.8
```

2. 确认 GreenMail 就绪

```bash
curl http://127.0.0.1:8081/api/service/readiness
```

期望返回：

```json
{"message":"Service running"}
```

3. 在 AVD 中安装 K-9 Mail

如需手工安装 APK，可用官方发行渠道或你们已有的镜像。当前更推荐直接跑仓库内的自动 onboarding 脚本，而不是手工逐页点完首配：

```bash
python scripts/bootstrap_android_comm_apps.py k9 --clear-app-data
```

这条脚本会：

- 检查 `http://127.0.0.1:8081` 上的 GreenMail 是否就绪
- 清空 K-9 Mail 应用数据
- 自动点击 `Get started -> Configure manually`
- 自动填写 `benchsender@example.test / benchpass / 10.0.2.2 / 3143 / 3025`
- 自动把 IMAP 和 SMTP 的 `Security` 设为 `None`
- 自动跳过 `Special folders / Sync options / Improve the experience` 这几段与 benchmark 无关的首配页面

如需覆盖默认参数，可显式传入：

```bash
python scripts/bootstrap_android_comm_apps.py k9 \
  --device emulator-5554 \
  --email benchsender@example.test \
  --username benchsender@example.test \
  --password benchpass \
  --incoming-server 10.0.2.2 \
  --incoming-port 3143 \
  --incoming-security None \
  --outgoing-server 10.0.2.2 \
  --outgoing-port 3025 \
  --outgoing-security None \
  --display-name BenchSender
```

建议在账户配置完成后保存一个 AVD 快照。这样后续跑 benchmark 时，不需要重复配置 K-9。

### 任务运行

单任务运行：

```bash
python -m platforms.android.cli --execution executions/android/android_k9_send_email.yaml
```

如果你想测更深的单任务设置能力，可以运行 K-9 手动配置场景：

```bash
python -m platforms.android.cli --execution executions/android/android_k9_manual_setup_send_email.yaml
```

这个 execution 现在也统一使用 `screenshot_only`。如果 K-9 的配置表单在纯截图模式下更难，这是刻意保留的 benchmark 难度，而不是继续给模型开放 a11y tree 快捷通道。

完整 Android 测试集运行：

```bash
python -m platforms.android.cli --execution executions/android/android_main_screenshot_pyautogui_gpt5_4.yaml
```

### 成功判定

- initializer 会在任务开始前清空 GreenMail 收件箱，并拉起 K-9
- agent 需要发送一封固定邮件到 `benchrecv@example.test`
- evaluator 会查询 `http://127.0.0.1:8081/api/user/benchrecv@example.test/messages/INBOX`
- 只有收件箱里实际出现匹配的 `收件人 + 主题 + 正文` 邮件，任务才算 `PASS`

如果 K-9 弹出 `Sent folder not found` 提示，需要选择 `Send and Delete`。这个行为已经写进 task instruction，属于场景的一部分。

## K-9 手动配置并发信任务

`android.k9.manual_setup_send_email` 是一个更深的单任务场景。initializer 会先把 K-9 推进到手动配置流的起点，随后要求 agent 选择 IMAP（如果账户类型选择页可见），并完成隐藏较深的 IMAP/SMTP 设置，再发送一封固定邮件到 GreenMail。

### 适用意义

- 场景难点集中在真实设置流程，而不是跨应用跳转
- 需要进入 `Configure manually`，填写 IMAP / SMTP 多组参数
- 对普通用户来说，这类手动邮箱配置本来就常常需要查文档
- 最终仍然通过 GreenMail 外部真值判断是否真的发出
- 当前 Android benchmark 默认强制使用 `screenshot_only`，即便这会让手动邮箱配置比 a11y 模式更难

### 运行方式

```bash
python -m platforms.android.cli --execution executions/android/android_k9_manual_setup_send_email.yaml
```

### 成功判定

- initializer 会清空 GreenMail，并把 K-9 推进到手动配置流起点
- agent 需要手动完成 IMAP/SMTP 账户配置
- agent 需要发送一封固定邮件到 `benchrecv@example.test`
- evaluator 会查询 GreenMail 收件箱
- 只有真正收到匹配 `收件人 + 主题 + 正文` 的邮件，任务才算 `PASS`

## K-9 扩展任务集

在 `android.k9.send_email` 与 `android.k9.manual_setup_send_email` 之外，新增了 3 个 K-9 任务，覆盖严格正文校验、单封转发、多封转发场景。

### 1) `android.k9.simple_send_email_v2`

- **任务文件**: `tasks/android/k9_simple_send_email_v2.yaml`
- **执行文件**: `executions/android/android_k9_send_email.yaml`
- **评测**: `evaluators/android/k9_simple_send_email_v2.py`
- **initializer**: 复用 `initializers.android.k9_email:K9SendEmailInitializer`（未新增 initializer 文件）
- **描述**:
  - 收件人：`benchrecv@example.test`
  - 主题：`Test Email 1`
  - 正文两行：
    - `Hello` 
    - `This is a test`
- **评测方式**:
  - 基于 GreenMail 拉取邮件
  - 校验主题、收件人、正文两行（逐行校验，避免换行格式差异误判）

运行方式：

```bash
python -m platforms.android.cli --execution executions/android/android_k9_send_email.yaml
```

### 2) `android.k9.forward_meeting_notes`

- **任务文件**: `tasks/android/k9_forward_meeting_notes.yaml`

- **执行文件**: `executions/android/android_k9_forward_alpha_beta_reports.yaml`

- **评测**: `evaluators/android/k9_forward_email.py` 中 `K9ForwardMeetingNotesEvaluator`

- **任务目标**:
  - 找到主题为 `Meeting Notes` 的邮件并转发给 `benchrecv@example.test`
  - 在正文最前添加 `Please review this.`


运行方式：
```bash
python -m platforms.android.cli --execution executions/android/android_k9_forward_alpha_beta_reports.yaml
```

### 3) `android.k9.forward_alpha_beta_reports`

- **任务文件**: `tasks/android/k9_forward_alpha_beta_reports.yaml`

- **执行文件**: `executions/android/android_k9_forward_alpha_beta_reports.yaml`

- **initializer**: `initializers/android/k9_seed_inbox_open.py`

- **评测**: `evaluators/android/k9_forward_email.py` 中 `K9ForwardAlphaBetaReportsEvaluator`

- **任务目标**:
  - 分别转发 `Alpha Report` / `Beta Report`
  - 收件人均为 `benchrecv@example.test`
  - 正文顶部插入统一前缀（任务定义中的要求）

- **评测方式**  :
  - 基于 GreenMail 拉取并解析 MIME
  - 按来源、前缀、marker 做结构化校验（非模糊匹配）


运行方式：
```bash
python -m platforms.android.cli --execution executions/android/android_k9_forward_alpha_beta_reports.yaml
```

### 新增复用能力文件（K-9）

- ```
  initializers/android/k9_seed_inbox_open.py
  ```

  - 统一 K-9 转发任务初始化：可选清空 GreenMail、批量 seed 收件箱邮件、拉起 K-9。

- ```
  evaluators/android/k9_forward_email.py
  ```

  - 统一 K-9 转发任务评估：
    - `K9ForwardMeetingNotesEvaluator`：校验单封目标转发
    - `K9ForwardAlphaBetaReportsEvaluator`：校验 Alpha/Beta 双邮件转发

## Delta Chat 聊天任务

`android.deltachat.send_message` 是一个实验性的聊天场景。它沿用宿主机上的 GreenMail 作为真值源，但 Android 端用的是 Delta Chat，而不是 K-9。

### 一次性环境准备

1. 启动 GreenMail

可直接复用上面的 GreenMail 启动命令。

2. 在 AVD 中安装 Delta Chat

推荐使用官方 GitHub Release APK。当前验证时使用的是：

```bash
gh release download v2.47.0 -R deltachat/deltachat-android \
  -p 'deltachat-gplay-release-2.47.0.apk' \
  -D /tmp/deltachat-install
adb install -r /tmp/deltachat-install/deltachat-gplay-release-2.47.0.apk
```

3. 运行自动 onboarding 脚本

推荐直接用仓库里的 bootstrap 脚本完成首配，而不是手工逐个字段输入：

```bash
python scripts/bootstrap_android_comm_apps.py deltachat --clear-app-data
```

这条脚本会：

- 检查 `http://127.0.0.1:8081` 上的 GreenMail 是否就绪
- 清空 Delta Chat 应用数据
- 自动点击 `Create New Profile -> Use Other Server -> Use Classic Email as Relay`
- 自动填写 `benchsender@example.test / benchpass / 10.0.2.2 / 3143 / 3025`
- 自动把 `IMAP Security` 和 `SMTP Security` 设为 `Off`

如需覆盖默认参数，可显式传入：

```bash
python scripts/bootstrap_android_comm_apps.py deltachat \
  --device emulator-5554 \
  --profile-name BenchSender \
  --email benchsender@example.test \
  --password benchpass \
  --imap-login benchsender@example.test \
  --imap-server 10.0.2.2 \
  --imap-port 3143 \
  --imap-security Off \
  --smtp-login benchsender@example.test \
  --smtp-password benchpass \
  --smtp-server 10.0.2.2 \
  --smtp-port 3025 \
  --smtp-security Off
```

首次配置完成后，仍然建议保存一个 AVD 快照。这样后续跑 benchmark 时不需要重复做 onboarding。

### 任务运行

```bash
python -m platforms.android.cli --execution executions/android/android_deltachat_send_message.yaml
```

### 成功判定

- initializer 会在任务开始前清空 GreenMail，并通过宿主机 SMTP 预先注入一条 `benchrecv@example.test -> benchsender@example.test` 的种子消息，然后拉起 Delta Chat
- agent 需要打开现有对话，并回复一条固定消息给 `benchrecv@example.test`
- evaluator 会查询 `http://127.0.0.1:8081/api/user/benchrecv@example.test/messages/INBOX`
- 只有收件箱里实际出现匹配的 `收件人 + 正文` 邮件，任务才算 `PASS`

这条 Delta Chat 聊天场景已经并入 `executions/android/android_main_screenshot_pyautogui_gpt5_4.yaml`。如果只是第一次验证聊天链路，仍然建议优先跑单任务 execution。

## Delta Chat 扩展任务集（5 个新增任务）

在 `send_message` 基础上，新增了 5 个覆盖不同交互模式的 Delta Chat 任务。它们全部依赖宿主机 GreenMail 作为评测真值源。

### 环境前提

与上面 `send_message` 完全一致：GreenMail 运行在宿主机、Delta Chat 已完成 onboarding、AVD 快照已保存。

### 任务一览

| 任务 ID | 难度 | 描述 |
|---------|------|------|
| `android.deltachat.set_status` | Easy | 进入设置修改个人签名 |
| `android.deltachat.create_contact_send_message` | Medium | 创建新联系人并发送指定消息 |
| `android.deltachat.forward_message` | Hard | 在对话 A 中长按消息并转发到对话 B |
| `android.deltachat.search_reply` | Hard | 使用全局搜索找到特定消息并引用回复 |
| `android.deltachat.archive_and_reply` | Hard | 归档对话后在归档区找到它并发送回复 |

### 各任务详细说明

#### 1. `android.deltachat.set_status`

- **任务文件**: `tasks/android/deltachat_set_status.yaml`
- **初始化器**: `initializers/android/deltachat_set_status.py`
- **评测器**: `evaluators/android/deltachat_set_status.py`
- **操作**: agent 需要进入 Delta Chat 设置页面，修改个人「Status」为指定值 `benchmark_status_msg_ok`
- **评测方式**: 直接拉取 Delta Chat 本地数据库 `dc.db`，使用二进制 grep 扫描确认状态值已写入
- **注意**: 评测不依赖 GreenMail，而是依赖本地 SQLite

#### 2. `android.deltachat.create_contact_send_message`

- **任务文件**: `tasks/android/deltachat_create_contact_send_message.yaml`
- **初始化器**: `initializers/android/deltachat_create_contact.py`
- **评测器**: `evaluators/android/deltachat_create_contact_send_message.py`
- **操作**: agent 需要创建新联系人 `newcontact@example.test`，并在新建的 1:1 对话中发送 `hello_new_contact_message`
- **评测方式**: 轮询 GreenMail 的 `newcontact@example.test` 收件箱，检查是否收到匹配邮件

#### 3. `android.deltachat.forward_message`

- **任务文件**: `tasks/android/deltachat_forward_message.yaml`
- **初始化器**: `initializers/android/deltachat_forward.py`
- **评测器**: `evaluators/android/deltachat_forward_message.py`
- **操作**: 初始化器预注入两个对话（source 和 target），agent 需要打开 source 对话，长按 `forward_this_important_message`，转发给 target 对话
- **评测方式**: 检查 `forwardtarget@example.test` 的收件箱中是否包含转发的消息

#### 4. `android.deltachat.search_reply`

- **任务文件**: `tasks/android/deltachat_search_reply.yaml`
- **初始化器**: `initializers/android/deltachat_search_reply.py`
- **评测器**: `evaluators/android/deltachat_search_reply.py`
- **操作**: 初始化器注入 3 个对话（2 个干扰项 + 1 个目标），agent 需要用全局搜索找到 `urgent_project_deadline_reminder` 消息，长按引用回复 `acknowledged_will_handle_asap`
- **评测方式**: 检查 `charlie@example.test` 的收件箱中是否收到包含回复文本和引用原文的邮件

#### 5. `android.deltachat.archive_and_reply`

- **任务文件**: `tasks/android/deltachat_archive_and_reply.yaml`
- **初始化器**: `initializers/android/deltachat_archive.py`
- **评测器**: `evaluators/android/deltachat_archive_and_reply.py`
- **操作**: 初始化器注入一个对话，agent 需要长按该对话将其归档，然后到「Archived chats」区找到它，打开并发送 `reply_from_archive_message`
- **评测方式**: 检查 `archiveuser@example.test` 的收件箱中是否收到回复

### 已知问题

- Delta Chat v2.42.0+ 存在已知 Bug（[#4231](https://github.com/deltachat/deltachat-android/issues/4231)）：无法通过 UI 正常添加群成员。因此原计划的 `create_group_send_message` 任务已替换为 `search_reply`
- 所有基于 GreenMail 的评测器已包含 HTTP 400 错误的优雅处理，避免因邮箱不存在导致评测崩溃
- 初始化器中的 SMTP 登录做了容错处理（`try/except`），兼容 GreenMail 不同版本的认证行为

## Oinkoin 本地记账任务


Oinkoin 现在是一组 5 个离线 finance/accounting 场景。它们都不依赖账号登录、网络服务或外部 API，统一通过本地 SQLite 真值做最终判定：

- `android.oinkoin.create_expense`：从 fresh state 新增固定 Food 支出
- `android.oinkoin.create_income`：从 fresh state 新增固定 Salary 收入
- `android.oinkoin.edit_expense`：编辑 initializer 预置的一条支出记录
- `android.oinkoin.delete_expense`：删除 initializer 预置的一条支出记录
- `android.oinkoin.create_custom_category_and_use_it`：创建自定义分类 `BenchCafe`，先新增一条支出，再重新打开并编辑金额与标题成最终版本（hard）

### 一次性环境准备

1. 在 AVD 中安装 Oinkoin PRO

推荐直接从 GitHub Releases 安装与模拟器 ABI 对应的 APK。对于常见的 x86_64 AVD，可执行：

```bash
gh release download -R emavgl/oinkoin \
  -p 'app-x86_64-pro-release.apk' \
  -D /tmp/oinkoin-install \
  --clobber
adb install -r /tmp/oinkoin-install/app-x86_64-pro-release.apk
```

如果你们的 AVD 不是 x86_64，请改成对应 ABI 的 release asset。

2. 确认包名可见

```bash
adb shell pm list packages | grep com.github.emavgl.piggybankpro
```

Oinkoin 当前这条 benchmark 使用：

- package: `com.github.emavgl.piggybankpro`
- activity: `com.example.piggybank.MainActivity`

### 任务运行

```bash
python -m platforms.android.cli --execution executions/android/android_oinkoin_edit_expense.yaml
python -m platforms.android.cli --execution executions/android/android_oinkoin_edit_expense.yaml
python -m platforms.android.cli --execution executions/android/android_oinkoin_edit_expense.yaml
python -m platforms.android.cli --execution executions/android/android_oinkoin_delete_expense.yaml
python -m platforms.android.cli --execution executions/android/android_oinkoin_create_custom_category_and_use_it.yaml
```

### 成功判定

- 所有 Oinkoin task 的 initializer 都会先确认包名 `com.github.emavgl.piggybankpro` 可用，并把 app 拉到可操作的起始状态
- 当前 Android benchmark 统一强制使用 `screenshot_only`。即便 Oinkoin 的 Flutter a11y resource-id 原本较完整，我们也不再把 a11y tree 作为默认输入，以免真实模型走可访问性捷径。
- evaluator 会通过 `adb root` 直接读取：
  - `/data/user/0/com.github.emavgl.piggybankpro/databases/movements.db`
- 只有当 SQLite 真值满足各自 task 的约束时才算 `PASS`：
  - create expense：必须出现 `Food / 12.34 / Coffee / bench_expense_note`
  - create income：必须出现 `Salary / 1234.56 / Payday / bench_income_note`
  - edit expense：必须只剩更新后的 `Food / 18.88 / Coffee Beans / bench_edit_note`，旧 seed row 不得保留
  - delete expense：seed 的 `Tea / 9.99 / bench_delete_me` 必须完全消失
  - custom category：必须存在 `BenchCafe` 分类，且最终只剩编辑后的 `Special Coffee Beans / 24.80 / bench_custom_category_note` 记录；初始的 `Special Coffee / 21.50 / bench_custom_category_note` 不得保留

## Fossify Calendar + Organic Maps + Delta Chat 跨应用场景

`android.fossify_maps_deltachat.send_cafe_address` 是一个多应用协作场景：

- initializer 会清理并重建一条当天的 Fossify Calendar 事件
- 事件内容要求 agent 去 Organic Maps 查找目标咖啡馆
- 最终结果通过 Delta Chat 发给 `benchrecv@example.test`
- evaluator 仍然只以 GreenMail 中实际收到的消息为准

### 前置条件

- Fossify Calendar 已安装在模拟器中
- Organic Maps 已安装在模拟器中
- Delta Chat 已完成一次针对 GreenMail 的账户配置
- GreenMail 正在宿主机运行，并暴露 `http://127.0.0.1:8081`

这个场景依赖截图理解，因此 `executions/android/android_main_screenshot_pyautogui_gpt5_4.yaml` 和 focused execution 现在统一使用 `free_codesonline_gpt5_4_responses` + `screenshot_only`。如果你只想单独验证这条跨应用链路，仍然推荐 focused execution：

```bash
python -m platforms.android.cli --execution executions/android/android_fossify_maps_deltachat_send_cafe.yaml
```

如果你要对单条任务连续重试，可以直接用：

```bash
python scripts/run_android_task_trials.py \
  --task tasks/android/cross_app_fossify_maps_deltachat_send_cafe.yaml \
  --model-id free_codesonline_gpt5_4_responses \
  --mode until_pass \
  --attempts 5 \
  --adb-device emulator-5554
```

这里有两个模式：

- `until_pass`：最多跑 `--attempts` 轮，首个 `PASS` 就停止。这个模式适合验证“当前场景能不能跑通”。
- `fixed`：固定跑满 `--attempts` 轮，再根据 `PASS / 总轮数` 计算经验成功率。这个模式适合比较模型稳定性。

每轮会写到新的 session 目录下，并在 session 根目录生成 `summary.json`。如果你要做真正的成功率统计，不要在首个成功后停止。

### 初始化内容

- 清空 Fossify Calendar 的 app data
- 预授予 `POST_NOTIFICATIONS`，避免保存事件时被系统权限弹窗打断
- 自动创建一条当天的 `Bench Coffee Task` 事件
- 确保 Organic Maps 的 Monaco 区域已下载，并且能搜索到 `Richmond Bar`
- 清空 GreenMail，并预注入一条 `benchrecv@example.test -> benchsender@example.test` 的 Delta Chat 种子消息

### 成功判定

- agent 需要从日历事件中读出要求
- 在 Organic Maps 中找到正确的咖啡馆
- 通过 Delta Chat 向 `benchrecv@example.test` 发送咖啡馆名称和地址
- evaluator 会查询 GreenMail 收件箱，并检查消息中至少包含：
  - `Richmond Bar`
  - `Boulevard Princesse Charlotte, 20, 98000`

这条任务目前是实验性的多模态场景，验证入口优先使用单任务 execution，而不是直接并入现有 Android 默认测试集。

## 结果目录

```
results/<model>/android/<execution_name>_<timestamp>/
  <task_id>/
    result.json
    trajectory.jsonl
    screenshots/
```

## 环境变量覆盖

- `HELLOWORLD_ANDROID_ADB_DEVICE` — 覆盖 adb_device
- `HELLOWORLD_ANDROID_AVD_NAME` — 覆盖 avd_name

## Calculator 加法任务

`android.calculator.addition42` 是一个基础计算场景，要求 agent 在系统计算器中完成 `12 + 34` 并得到 `46`。

### 任务运行

​```bash
python -m platforms.android.cli --execution executions/android/android_material_files_create_folder.yaml
```

### 成功判定

- evaluator 读取计算器界面的结果区域
- 目标结果为 `46`
- 评估逻辑避免历史记录干扰，按当前显示结果判定

## LibreOffice 文档标记任务

`android.libreoffice.viewer.mark` 是一个编辑/保存/重开场景，要求 agent 在 LibreOffice 中写入 `READ_BY_VIEWER`，保存为 `bench_read_by_viewer.odt`，并在重新打开后完成验证。

### 任务运行

```bash
python -m platforms.android.cli --execution executions/android/android_libreoffice_viewer_mark.yaml
```

### 成功判定

- evaluator 优先检查最终 a11y tree 是否包含 `READ_BY_VIEWER`
- 若正文未暴露到 a11y（LibreOffice 常见），回退检查已保存 ODT 的 `content.xml` 是否包含该标记
- initializer 负责把应用带到可操作状态，减少 FAB 菜单开关造成的无效循环

## LibreOffice 文档编辑任务
文档编辑/重开验证任务，均遵循 LibreOffice Android 的真实行为约束：编辑后可能不即时可见，需保存并重开确认。
### 1) `android.libreoffice.status_report_update`
- **initializer**: `initializers/android/libreoffice_status_report_prep.py`
- **任务文件**: `tasks/android/libreoffice_status_report_update.yaml`
- **评测器**: `evaluators/android/libreoffice_status_report.py`
- **执行文件**: `executions/android/android_libreoffice_status_report_update.yaml`
- **任务目标**:
  - 打开 `status_report.odt`
  - 将 `Status: Pending` 修改为 `Status: Completed`
  - 保存 -> 返回首页 -> 重开 -> 再确认
- **评测方式**:
  - 拉取保存后的 ODT，解析 `content.xml`
  - 校验新文本存在、旧文本不存在（以持久化结果为准）

运行方式：
```bash
python -m platforms.android.cli --execution executions/android/android_libreoffice_status_report_update.yaml
```

### 2) `android.libreoffice.notes_append_hard`

- **initializer**: `initializers/android/libreoffice_notes_append_prep.py`

- **任务文件**: `tasks/android/libreoffice_notes_append_hard.yaml`

- **评测器**: `evaluators/android/libreoffice_notes_append.py`

- **执行文件**: `executions/android/android_libreoffice_notes_append_hard.yaml`

- **任务目标**:
  - 打开 `notes.odt`，滚动到末尾
  - 追加三行任务文本并完成编号/格式化操作
  - 保存 -> 返回首页 -> 重开 -> 再次滚动到末尾确认

- **评测方式**  :
  - 仅验证文本持久化，不验证 bold/italic 样式
  - 断言保存后的 ODT  content.xml   至少包含：
    - `Task A completed`
    - `Task B completed`
    - `Task C completed`

运行方式：

```bash
python -m platforms.android.cli --execution executions/android/android_libreoffice_notes_append_hard.yaml

```
## Spotube 任务集（1 Easy + 2 Hard）
### 1) `android.spotube.search_artist_play_attempt`（Easy）
**此次任务简述**
- **目标**：在 Spotube 搜索 `Taylor Swift`，进入第一个艺术家结果并点击任意歌曲触发“播放尝试”（不依赖真实播放成功）。
- **设计原则**：允许播放链路不稳定，但要求 UI 与本地状态证据一致。
- **通过条件**：前台正确 + 艺术家证据 + 最近播放尝试信号 + 底部当前歌曲栏与目标艺术家一致。
**四个相关文件作用**
- `initializers/android/spotube_open_clean_session.py`
  - 任务前置：检查安装、清理旧日志、启动 Spotube、确认前台（含 launcher fallback 与轮询）。
- `tasks/android/spotube_search_artist_play_attempt.yaml`
  - 人类可执行任务说明与参数入口：步骤、回车触发搜索、失败时纠偏策略、初始化与评测参数。
- `evaluators/android/spotube_search_artist_play_attempt.py`
  - 成败裁决：前台检测 + UI dump 解析 + `media_session` 新鲜度 + mini-player 文本一致性，避免假阳性。
- `executions/android/android_spotube_search_artist_play_attempt.yaml`
  - 运行编排：绑定 task、模型（`free_codesonline_gpt5_4_responses`）、观测模式（`screenshot_only`）、`history_window`。
运行方式：
```bash
python -m platforms.android.cli --execution executions/android/android_spotube_search_artist_play_attempt.yaml
```
### 2) `android.spotube.profile_setup`（Hard）
**任务目标简述**
- 在 Spotube 完成 Profile Setup：
  - `Jiosaavn Audio` 设为默认音频源
  - `Language=English`
  - `Marketplace Region=Austria`
  - `Theme=Light`
  - `Accent Color=rose`
  - `Normalize audio` 打开
- 评测层面对 `Normalize audio` 采用可见性硬检 + on/off 可观测诊断（兼容 Flutter a11y 暴露不稳定）。
**涉及文件简述**
- `tasks/android/spotube_profile_setup.yaml`
  - 定义任务目标、操作步骤、行为约束和 evaluator 参数，是“模型该做什么”的主入口。
- `evaluators/android/spotube_profile_setup.py`
  - 负责验收：前台应用检查、Settings 滚动采样、Plugins 导航验证默认音源、逐项检查输出与总判定。
- `executions/android/android_spotube_profile_setup.yaml`
  - 定义执行编排：运行哪个 task、用哪个模型、观测模式等。
- `initializers/android/spotube_open_clean_session.py`
  - 任务前置环境准备：启动 Spotube、清理日志/会话相关干扰、确保前台状态稳定，并做 app 内 Home 稳定尝试。
运行方式：
```bash
python -m platforms.android.cli --execution executions/android/android_spotube_profile_setup.yaml
```
### 3) `android.spotube.queue_naina_zara`（Hard）
**任务目标简述**
- 在 Spotube 完成一个稳定的队列操作流程：
  - 前置做音源与基础设置（用于稳定性，不硬验）
  - 搜索并播放 `Naina`
  - 将 `Zara Zara` 第一条通过三点菜单加入队列
  - 打开 Queue 并显示两首都在队列中
**涉及文件简述**
- `initializers/android/spotube_open_clean_session.py`
  - 负责任务启动前环境：启动 Spotube、前台就绪检测、清理日志、尝试稳定到 app 内 Home。
- `tasks/android/spotube_queue_naina_zara.yaml`
  - 定义 Task B 的操作步骤与行为约束（尤其是不搜/不重装 Jiosaavn、最终停在 Queue）。
- `evaluators/android/spotube_queue_naina_zara.py`
  - 定义成功判定：Spotube 前台 + Queue 证据 + `Naina` 证据 + `Zara Zara` 证据。
- `executions/android/android_spotube_queue_naina_zara.yaml`
  - 定义运行配置（模型、观测模式、`history_window`）；当前统一采用 `screenshot_only`，避免真实模型直接利用 a11y tree。
运行方式：
```bash
python -m platforms.android.cli --execution executions/android/android_spotube_queue_naina_zara.yaml
```


## 包含的任务

| 任务 | 来源 | 说明 |
|---|---|---|
| `android.contacts.add_contact` | ContactsAddContact | 创建联系人 |
| `android.clock.stopwatch_running` | ClockStopWatchRunning | 启动秒表 |
| `android.system.bluetooth_turn_on` | SystemBluetoothTurnOn | 打开蓝牙 |
| `android.markor.create_note` | MarkorCreateNote | 创建笔记 |
| `android.oinkoin.create_expense` | OinkoinCreateExpense | 在 Oinkoin 中新增一条固定 Food 支出，并通过本地 SQLite 真值验证持久化 |
| `android.oinkoin.create_income` | OinkoinCreateIncome | 在 Oinkoin 中新增一条固定 Salary 收入，并通过本地 SQLite 真值验证持久化 |
| `android.oinkoin.edit_expense` | OinkoinEditExpense | 编辑 initializer 预置的 Food 支出，并要求旧记录消失、更新记录落库 |
| `android.oinkoin.delete_expense` | OinkoinDeleteExpense | 删除 initializer 预置的 Food 支出，并通过本地 SQLite 确认硬删除 |
| `android.oinkoin.create_custom_category_and_use_it` | OinkoinCreateCustomCategoryAndUseIt | 新建自定义 BenchCafe 分类，创建记录后重新打开并编辑金额与标题，最终验证分类与编辑后的记录 |
| `android.k9.send_email` | K9SendEmail | 通过 K-9 发送邮件到 GreenMail 并验证送达 |
| `android.k9.manual_setup_send_email` | K9ManualSetup | 从手动 IMAP/SMTP 配置流开始完成 K-9 建账并发邮件到 GreenMail |
| `android.deltachat.send_message` | DeltaChatSendMessage | 通过 Delta Chat 在种子会话中回复固定聊天消息到 GreenMail 并验证送达 |
| `android.fossify_maps_deltachat.send_cafe_address` | CalendarMapDeltaChat | 从 Fossify Calendar 读取任务，在 Organic Maps 定位咖啡馆，再用 Delta Chat 发送地址到 GreenMail |
| `android.calculator.addition42` | CalculatorAddition | 在系统计算器中完成 12+34，结果为 46 |
| `android.libreoffice.viewer.mark` | LibreOfficeViewerMark | 新建文档写入 READ_BY_VIEWER，保存并重开后验证 |
| `android.k9.simple_send_email_v2` | K9SimpleSendEmailV2 | K-9 发信（严格两行正文）并通过 GreenMail 精确校验 |
| `android.k9.forward_meeting_notes` | K9ForwardMeetingNotes | 从多邮件中定位 Meeting Notes 并转发，正文前置提示语 |
| `android.k9.forward_alpha_beta_reports` | K9ForwardAlphaBetaReports | 分别转发 Alpha/Beta 报告并校验前缀与来源 |
| `android.libreoffice.status_report_update` | LibreOfficeStatusReportUpdate | 修改状态字段并通过保存-重开后的 ODT 内容校验持久化 |
| `android.libreoffice.notes_append_hard` | LibreOfficeNotesAppendHard | 文档末尾追加三行任务文本（含编号/格式化流程），评测仅校验文本持久化 |
| `android.libreoffice.notes_append_hard` | LibreOfficeNotesAppendHard | 文档末尾追加三行任务文本（含编号/格式化流程），评测仅校验文本持久化 |
| `android.spotube.search_artist_play_attempt` | SpotubeSearchArtistPlayAttempt | 搜索 Taylor Swift，进入首个艺术家并点击歌曲，基于 UI + media_session + mini-player 验证播放尝试 |
| `android.spotube.profile_setup` | SpotubeProfileSetup | 完成 Jiosaavn 默认音源与 Profile 设置（English/Austria/Light/rose/Normalize）并做结构化评测 |
| `android.spotube.queue_naina_zara` | SpotubeQueueNainaZara | 播放 Naina、将 Zara Zara 加入队列，并在 Queue 视图验证两首歌曲同时存在 |
