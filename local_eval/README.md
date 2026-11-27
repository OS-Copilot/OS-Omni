# Android 本机评测

目标：使用 `deepseek-flash` 在 Android GUI 上执行发布的 48 道 v1 任务。

2026-10-08 按用户要求改为关闭思考（`reasoning_effort: none`），每题最多 180 个 agent step。此前完成的结果保留原设置；新运行旁保存 `execution-profile.json`。关闭思考的 API 实测返回 HTTP 200、reasoning_tokens 0。

## 运行

Python 环境为仓库内 `.runtime`（Python 3.12.14）。模型密钥从用户目录 `.codex/secrets/os-omni-deepseek.json` 读取，未写入仓库。

```powershell
& .\.runtime\Scripts\python.exe -X utf8 -u local_eval\run_queue.py
```

队列只使用 `emulator-5582`，按题串行运行。不要同时运行第二个队列或手动恢复模拟器快照。`queue/status.json` 是当前状态；`runs/<task_id>/<timestamp>/result.json` 为判题结果，旁边保留截图、`trajectory.jsonl` 和日志。

每题自动检查并启动缺失的本机 OpenDriver / GreenMail 服务。队列有独占锁；中断后重新运行上述命令，会接回已经写出的判题结果。正在后台运行时，`queue_companion.py` 刷新 SUMMARY 并防止自动睡眠。

每题从已校验下载包的原始磁盘文件冷启动并重建初始状态，再进行未操作负例检查。原 `os_omni_clean` 内存快照重复恢复会导致本机 Android 服务、共享存储及截图故障，因此改用冷启动；来源写入每题 `vm-reset-provenance.json`。初始化 PASS、未操作判题 FAIL、成功捕获起始截图才进入模型执行。环境 ERROR 不作为模型失败计分。已完成任务不会自动重复运行；环境错误可修复后重启队列重试。

## 重建范围与可比性

- 原始 `tasks/v1/android` 保留。本机修改位于 `local_eval/tasks`，包含重建来源记录。
- OpenNote、OpenBank、OpenShop、OpenTrip、OpenTwitter、OpenFood 优先复用安装 APK 的种子数据。对要求已登录的任务只补初始登录会话。
- OpenDriver 后端是依据安装 APK 中 Dart 源码恢复的本机替代实现，监听 127.0.0.1:4321，尚需逐项补全。HTTP 请求和业务变更分别留有记录。
- OpenDriver 地图使用本地经纬度示意底图，非原始道路图；无道路图的路由请求使用 APK 自带的几何回退。三次预约任务在模拟器内恢复 2026-08-29 的业务日历，使指定的 8 月 30/31 日可选，不修改宿主机时间。Logout 任务保留原始最终屏幕检查，并额外验证登录、指定工单、退出的事件顺序，防止初始登录屏幕直接判通过。
- Driver 预约判题器在无凭据且确认为本应用 Sign in / Choose a workspace 登录页时，将原读取 ERROR 标为任务 FAIL；其他读取异常保留 ERROR，已有凭据时沿用原业务判题。Flutter 原生输入框标签未全部出现在无障碍树中，页面识别使用实际可读文字；模型仍只接收截图。
- DeltaChat 的聊天初始输入在下载镜像中已存在。私有数据库通过模拟器 root 权限读取，同时复制 SQLite WAL，避免漏掉最新消息。邮件服务复用 GreenMail 2.1.8，采用本机 JDK 25；短临时目录解决了 JBR 21 的 Unix socket 启动问题。
- DeltaChat River Park 的最终标题来源消息保留；缺失的 `android_zoe_unread_11` 搜索标记作为初始来信补到既有最后标题消息之前。没有预先生成目标群组或 Markor 笔记。Delivery Claim 的第一步要求 Markor 新建笔记，初始前台改为 Markor。
- OpenFood 首次用户操作前不会写 localStorage。缺失键时使用经 APK 源码校验的空初始状态进行只读判题，保留全部业务检查；四题空初始状态均判 FAIL。
- OpenPhoto 的原始校准快照缺失。使用镜像照片重建纯 RGB 输入校准条，并记录既有导出文件，最终导出只由模型操作产生。保留原始输出尺寸、像素阈值。Cooking 的原始户外照片变体仍缺失，目前来源不同，结果必须标记为重建场景，不能声称精确复现原快照。
- 当前 OpenNote APK 会按空格、逗号、井号拆分标签，原判题规则部分要求带空格的单一标签。兼容判题器依 APK 实际解析规则比较标签；同时保留原始判分及全部原始检查。其他精确字段、记录数量和事件检查未放宽。

因此这些结果属于**重建环境评测**，不能无条件当作官方原始快照评测分数。最终汇总需同时说明环境错误、重建差异、原始判分和修复判分。

## 首次试跑

2026-10-08 失败审计后队列保持停止。已确认的初始化、判题兼容和执行脚本问题已修复，旧成绩加排除标签而不改原报告。详见 [FAILURE-AUDIT.md](FAILURE-AUDIT.md)；实际 24 题基线检查和 10 组正反例回归均已通过。银行业务日期兼容结果仍属于重建环境评测。

`android.opennote.city_food_469121/20261008_010841` 使用 Python 3.14 完成 184 步，原始判分 FAIL。问题包括标签规则不兼容和模型重复发布 Lemon stop notes。该次作为环境试跑保留；正式队列使用 Python 3.12 重跑。


## 作者授权的图片 benchmark v2
2026-10-09作者确认有权重建所有丢失资产并授权改evaluation。Cooking室内/户外照片已用built-in image_gen生成替代；原下载照片保留。Cooking/Guitar已用真实GUI精确原题参数重建四套参考成片及确定性重复验证，校准块不再使用容易截断的纯RGB；新增整图比较确保选图正确。12组正反例、两组真实设备PASS、冷启动initializerPASS及baselineFAIL已验证。详见benchmark-v2/README.md、repair.json、assets/generation-prompts.md。旧两题结果归档排除，新版两题DS重测；其他46有效结果保留。
