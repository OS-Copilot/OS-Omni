# Android 失败审计（2026-10-08）

评测队列已停止。本次没有调用 DS，也没有重跑正式任务。原始 result.json 和轨迹保留；队列另加审计标签，旧成绩不计入修复后的干净成功率。

## 旧结果能说明什么

已有 12 个正式 FAIL，另有 6 次环境错误、3 次运行错误、1 个被审计中断的任务。

| 分类 | 数量 | 结论 |
|---|---:|---|
| 解析错误／空响应导致提前终止 | 4 | 不能当作完整任务能力测试；其中商店代码围栏解析确有脚本错误 |
| 模型错误与银行判题不兼容混合 | 2 | 有漏做或错误日期，也有 ID 与业务日期冲突 |
| Twitter 必需基线缺失与模型漏做混合 | 1 | 基线检查必败；轨迹同时漏做任务要求 |
| Twitter 漏做且存在历史截图／保存状态疑点 | 1 | 多项漏做可确认；单个保存判定不能追溯确认 |
| 可见模型漏做，但需干净基线重测 | 4 | 短轨迹只完成最后部分、或未找到目标；并非全部是环境问题 |
| 环境／运行错误或中断 | 10 | 根本没有形成可用模型成绩 |

逐题失败检查、轨迹路径和归因见 failure-audit.json。原来第一题跑了 240 步，不能与现在最多 180 步、关闭思考的设置混算。

## 已修复

- 初始化写入状态后立即导航会断开 CDP。改为延迟导航，等待页面与应用函数就绪。
- OpenNote 错把 sessionStorage 标记当作登录状态。现在从 APK 原始种子启动，明确设置退出登录并等待登录页。
- Twitter 原始初始化器没有写判题所需基线。现在记录真实事件序号、初始通知数量、已有目标操作和重建来源；检测污染时拒绝开始。
- OpenShop 页面脚本尚未就绪就调用 readLocalState。新增就绪检查。
- 银行争议存交易 ID，规则却写商户名或转账备注。现在通过交易账本做精确关联；仍检查争议数量、原因、详情、联系商户状态。
- 银行 APK 业务日期固定为 2026-06-01。未来日期操作实际为 Scheduled；兼容规则保留金额、日期、收款人等精确检查，同时记录原状态要求与原日历规则判定。这是安装版本兼容评测，不能冒充原始官方环境成绩。
- 保留原有笔记标签兼容规则；核对确认判题器直接读取子类 RULESET_SPEC，该兼容修改有效。
- 行内 ```adb shell ...``` 围栏误吃 adb。已修复；超过命令上限现在拒绝，不再静默截断。
- 格式错误允许再尝试两次，每次仍消耗步骤；总上限仍是 180。GUI 输入失败不再记录为成功。
- 截图直接用 adb exec-out 获取，校验 PNG；失败重试后报错，绝不返回不存在的文件。
- 删除同一次正式运行中的重复初始化；文本历史保留，图片历史仍限制最近三张。
- 后续保存真实结束状态、终止原因、执行有效性；执行错误从模型成功率排除。
- 48 个任务的有效 limits.max_steps 均不超过 180；原来更小的题目上限保留。DS 思考仍为 none。

## 验证

实际模拟器上银行、笔记、商店、Twitter 共 24 个任务：24/24 初始化 PASS，24/24 未操作判题 FAIL，均成功保存有效起始截图。证据目录 audit-smoke/20261008_152904。

audit_regression.py 的 10 组离线回归全部通过：6 个银行任务的合成正确状态通过、删除必需记录失败；错误日期、错误争议详情、重复争议失败；围栏修复与命令拒绝通过。合成正例只用于测试判题器，不计入模型成绩。

另通过正式 run_one.py 的完整冷启动预检：opennote_city_food，证据 runs/android.opennote.city_food_469121/20261008_153943。初始化 PASS、未操作判题 FAIL，真实起始页面为 login.html，PNG 校验通过；不调用模型。

真实 Twitter 应用 API 的保存／取消保存持久化检查通过，探针帖子已删除。这只是应用接口检查，不是 DS 完成任务。

## 尚不能追溯确定的事实

Twitter 01 历史末步截图显示 Owners aligned. 已保存，但旧判题说保存不存在。旧运行未保存完整结束状态，当前应用 API 无法复现丢失，不能凭猜测放宽判题或把该检查改为通过。后续干净重测用结束状态和操作证据核对。该题其他多项漏做已有证据，因此这个疑点也不意味着整题应当通过。

原始任务快照没有提供。现有测试使用 APK 种子加重建登录态，明确保留该限制；不声称已经恢复作者原始快照。队列继续保持停止，尚未产生修复后的 DS 成功率。


## 2026-10-09 OpenShop baseline repair
The clean APK has four history orders; four snapshot tasks require five. ReconstructedBaselineInitializer now adds required prior ID TB1781113752081 using the APK March delivered order schema and records provenance, then validates exact baseline IDs. Original prior-order contents remain unavailable. Business rules unchanged. Positive / missing-baseline / wrong-review regressions pass. Real cold preflight PASS with untouched evaluator FAIL; device order-history DOM has all five cards and headphone review controls. Beauty old result preserved and excluded, queued for retest; interrupted commute queued to resume. Evidence: monitor-audits/20261009_0030-shop-*.json.


## 2026-10-09 OpenTrip hotel schema repair
Observed APK fields item.id/name, booking.room and booking.checkIn/checkOut, charges.baseFare differ from grader aliases. Read-only deep-copy adapter now maps them without changing requirements. Correct saved hotel-review episode regraded PASS in separate result.schema-corrected.json; original FAIL preserved. Wrong hotel rejected, duplicate suite orders remain FAIL, correct single discounted suite passes. Real cold preflight initializer PASS / untouched grader FAIL. Resumed interrupted reschedule task after validation. Evidence monitor-audits/20261009_0330-trip-*.


## 2026-10-09 OpenTrip history schema repair
APK rescheduleHistory is ordered list with previous record. Grader now compares first previous entry, preserving original itinerary requirement. Saved DS reschedule run passes; wrong previous date and missing history fail. Original report preserved; separate schema-corrected report supplies score. Cold preflight initializer PASS / untouched evaluator FAIL. Interrupted Food task resumes. Evidence monitor-audits/20261009_0400-*.


## 2026-10-09 04:45 pending OpenFood event repair
Queue stopped after confirming original APK emits neither reorder provenance nor status-transition history required by some tasks. Do not restart before adding truthful runtime action recording and validating it. Evidence monitor-audits/20261009_0445-food-event-blocker.json; interrupted smokehouse espresso run preserved. Poke Add taps actually accumulated cart quantity37, so unresponsive-button claim is false.


## 2026-10-09 05:00 OpenFood event repair completed
Original APK does not emit required process provenance. openfood-events-v1 records only actual successful reorder source, checkout and advance/cancel actions. Clear/cart restaurant switch invalidates pending source. Patched APK signed locally and installed after every pristine VM restore, checksum verified. Cold preflight initializer PASS and untouched evaluator FAIL with empty storage. Actual device controls generated correct Reorder and Preparing -> Out for delivery -> Delivered history; missing/wrong source/missing middle status negatives rejected. Real delivered screenshot inspected. Poke original report preserved and excluded for impossible process evidence, pending retest; its independent wrong restaurant and 37 repeated Add actions remain documented. Dumpling has no event requirements and remains valid model FAIL. Interrupted espresso will restart from clean state. Evidence monitor-audits/20261009_0500-food-event-repair.json and 20261009_0500-food-events/.


## 2026-10-09 05:29 Poke repaired retest review
78-step valid model FAIL. Model again claimed Add unresponsive, but saved cart has Wrap quantity28 and Noodles quantity1; no orders placed. Empty event arrays are expected before checkout, patched APK provenance present. Final physical screenshot inspected, prior device-handler regression passed. Correction: r96 is the required Central La Jolla Poke in the APK catalog, not a wrong restaurant; its Mexican cuisine/burrito menu are seed content. Earlier wrong-restaurant interpretation is withdrawn. Queue continues espresso; valid score 30/48 with4PASS26FAIL. Evidence monitor-audits/20261009_0529-poke-retest-review.json.


## 2026-10-09 05:44 Espresso review
128-step model DONE but valid FAIL: all four orders use wrong variants and coffee quantities. Exact Pulled Pork Sandwich/Mac and Cheese visibly exist in step66 screenshot; model consciously substituted alternative BBQ items in step26 and never corrected them. Support, coupons, restaurant closure and availability all pass. Original exact item requirements retained. Patched app correctly persisted two real reorder links and12 status events. Final and step66 screenshots inspected. Queue continues Pizza. Evidence monitor-audits/20261009_0544-espresso-review.json. Two completions since deep audit; perform next deeper audit after Pizza completes.


## 2026-10-09 06:14 Food deep audit and navigation blocker
Pizza141DONE validFAIL: extra Mac and Cheese in both BBQ orders, only2/3 BBQ orders, wrong coupon on second, support text missing spaces. Correct NY Slice order and merchant operations pass. Original exact requirements retained. All three new Food results cross-checked against saved state/catalog/trace; no further Food infrastructure defect confirmed. Navigation original APK Options and Report are alert-only; Records and save-route UI absent. Queue stopped safely; active navigation interrupted for audit with original trace preserved. Required reconstruction must be validated before resume. Evidence monitor-audits/20261009_0614-pizza-and-deep-audit.json.


## 2026-10-09 06:24 Navigation reconstruction validated
Original APK lacks route preference dialog, save-route/Records, and real incident reporting. Locally reconstructed generic UI persists actual selected backend routes with mode/destination/waypoints/preferences and reports associated with the saved route used during navigation. No task names or targets are prepopulated. Original evaluators unchanged. Actual device backend route->save->reopen->start->report->Records probe passes original evaluator; wrong endpoint and wrong route linkage fail. Real record screenshot inspected. Required Heavy traffic/Hazard/Transit delay/Road closure available. Final cold preflight initializer PASS (signed in, zero records) and untouched grader FAIL. Every VM restore installs checksum-verified debug-signed patched APK. Compatibility limitation: author workflow/snapshot unavailable; preference flags are sent/recorded but route behavior is limited to existing rebuilt backend. Interrupted24-step original trace excluded, preserved with interruption.json; will restart clean. Evidence monitor-audits/20261009_0614-nav-repair.json.


## 2026-10-09 06:44 Navigation first repaired DS PASS
91-step valid PASS under unchanged official grader. Clean signed-in baseline zero routes/incidents. Three required names/modes/endpoints and Heavy traffic/OfficeCongestion linked to MetaCommute verified in saved end-state, final screenshot and UI checks. Duplicate MetaCommute/TransitLink saves observed; original checker requires presence and association, not exact unique count. Rebuilt-environment limitations preserved. Queue continues next navigation task. Evidence monitor-audits/20261009_0644-nav-pass-review.json.


## 2026-10-09 07:14 Navigation second run review
180-step max FAIL. Model repeatedly claims Save route unresponsive but32 saved records include required Transit Stanford/Drive Meta associations. No incident records; final screenshot is Saved places, not Records. Judge correctly rejects incomplete final evidence. Original trace, state and screenshot inspected; no confirmed new bench defect. Two completions since deep audit; next completion triggers deeper audit. Evidence monitor-audits/20261009_0714-nav-fail-review.json.


## 2026-10-09 07:29 Navigation deep audit: waypoint UI omission
Silicon76DONE saved all3 routes and linked Road closure/BridgeClosed report. Released instruction places target locations in waypoints; official card evidence expects those waypoint names. Source saved-state confirms all associations, but reconstructed Records only showed destination. Confirmed presentation defect; queue stopped and original interrupted Driver trace retained. v1.1 renders only real persisted waypoint names alongside destination. Original graders/requirements unchanged. Silicon oldFAIL retained/excluded pending clean DS retest. Prior navigationPASS still valid; max180 run still independently fails missing reports/finalRecords. Device verification pending. Evidence monitor-audits/20261009_0729-nav-waypoint-repair.json.


## 2026-10-09 07:34 Waypoint presentation repair validated
v1.1 shows actual persisted Via waypoints, without altering stored routes, required associations or grader. Cold clean initializer PASS/untouched evaluator FAIL. Audit-only replay of original DS immutable saved state passes original grader; deleting waypoints fails. Original and repaired device screenshots inspected. Probe results never counted formally; contaminated SiliconFAIL excluded and queued for full clean DS retest. Prior valid navigation results retained. Interrupted Driver will restart clean after Silicon. Evidence monitor-audits/20261009_0729-nav-waypoint-device/regressions.json. Deep audit of three navigation results complete, counter reset.


## 2026-10-09 07:59 Silicon clean DS retest PASS
138-step fresh formal PASS after v1.1 waypoint display repair. Final real screenshot, immutable end-state and unchanged official checks confirm required names/modes/waypoint associations and linked Road closure/BridgeClosed. No probe outcome counted. Extra blank waypoint controls appear Unknown place; original requirements do not forbid extras. Clean baseline confirmed. Queue resumes interrupted Driver from pristine VM. Valid35/48 with6PASS29FAIL. Evidence monitor-audits/20261009_0759-nav-retest-pass.json.


## 2026-10-09 08:14 Driver workspace original UI PASS
94-step valid PASS under original final UI checker: actual screenshot shows Support/rider issue-open/Reply to ticket signed-in Driver Workspace. Native Flutter has no WebView end-state.json; original checker evidence saved in result UI excerpt and screenshot. Duplicate tickets/message newlines observed; checker does not require exact unique count/message, so do not overstate business coverage. Queue proceeds rider logout task. Evidence monitor-audits/20261009_0814-driver-pass-review.json. Two completions since deep audit.


## 2026-10-09 08:32 Rider logout deeper audit

37/48 complete, 7 PASS / 30 FAIL. Rider full-service run 20261009_081237: 68 steps, DONE, actual final Sign in screenshot confirmed. Original final-screen grader PASS; workflow wrapper FAIL is justified: complete trajectory skips Safety and support creation, immutable run-window HTTP log has no POST /support/tickets. Positive, missing ticket, wrong message and wrong order event fixtures all behave correctly. No new confirmed bench defect; existing reconstructed snapshot/menu differences remain limitations. Native Flutter has no WebView end-state.json. Third completion since last deep audit reviewed; counter reset. Queue 36908 and companion 26392 remain active; scheduled-rides task progressing. Evidence: monitor-audits/20261009_0832-driver-logout-review.json.


## 2026-10-09 08:55 Native Driver credential reader v2
Confirmed grader infrastructure defect: actual original APK stores token in code_cache/opendriver/auth_token.txt, not previously searched cache/files. Added real native path; no backend-token substitution or business/grader requirement relaxation. Audit-only GUI login followed by authenticated GET /users/me returns HTTP200; GUI logout removes token and reader raises expected missing-credential error. Scheduled run 082618 ended at180 fail_max_steps with two rides, third incomplete; evaluator ERROR retained/excluded and queued for clean DS retest. Actual final screenshot and HTTP window inspected, all HTTP200. Next seeded-driver preflight interrupted before model actions. Formal valid totals remain37/48,7PASS30FAIL. Evidence monitor-audits/20261009_0855-driver-reader-repair.json; independent probes never scored.


## 2026-10-09 09:18 Driver API envelope v3
Confirmed native success/data wrapper was not unwrapped, creating empty grader user/rides. Shared readonly reader now unwraps successful dictionary payload and retains raw response; business checks unchanged. Actual GET user visible. Exact original scheduled-grader positive fixture passes; wrong destination fails. Immutable backend from 085801 contains one scheduled ride; user check now true, count/matches still fail. Actual final screenshot inspected,180 maxsteps,native no WebView end-state. Original report excluded; clean DS retest queued. Seeded-driver preflight interrupted before model. Evidence monitor-audits/20261009_0915-driver-schema/repair.json. Valid37/48,7PASS30FAIL.


## 2026-10-09 09:45 Scheduled Rider clean retest FAIL
180-step cap, execution valid. Credential/envelope readers now show actual Lin Rider and2 scheduled rides. First required route/date/tier/promo correct; second pickup raw SF, third unbooked. Actual final screenshot shows Stop1=SFO and visible matches panel with no matches, contradicting model claim panel absent; no confirmed new app defect. Native no WebView end-state; immutable grader records retained.38/48,7PASS31FAIL. Queue14596/companion5556 healthy, seeded-driver running. One new completion since schema audit. Evidence monitor-audits/20261009_0945-driver-retest-review.json.


## 2026-10-09 10:03 Driver execution outage / fresh-screen guard
Seeded-driver094036 is INVALID execution, not model FAIL: last actual screenshot127 then19 missingscreens/device-not-found/action errors, model continued claiming unobserved messages/arrival. Saved originalreport/trajectory and last actualscreen inspected. No proven backend transition bug. Runner now stops before LLM when fresh screenshot/image unavailable, existing FAIL_ERROR execution_valid=false. Positive/negative guard probes pass. All39completed trace scan: only this outage and Twitter01 isolated missingstep3; Twitter independent finalPASS retained with gap caveat. Driver excluded/requeued; Delta cold-start interrupted beforemodel. Valid38/48,7PASS31FAIL. Emulator disappearance root cause unknown; pristine restart/preflight will restore. Evidence monitor-audits/20261009_1000-driver-transition/repair.json.


## 2026-10-09 10:31 Repeated Driver QEMU crash audit
Run100428:143steps,fail_error,execution_valid=false; fresh-screen guard verified on actual outage stops beforeLLM144. Windows Application event1000 records qemu-system-x86_64 access violations0xc0000005 at09:57 and10:22, matching both Driver failures. Internal fault unknown; no evidence backend business transition bug.602GB free,3.86GB RAM available. Healthy Delta now running; no emulator manipulation while DS active. Before Driver retry perform controlled alternate ANGLE rendering stability probe and inspect crash artifacts; avoid unchanged repeated crash loop.38valid/48,7PASS31FAIL,1excludedexecutionerror. Evidence monitor-audits/20261009_1000-driver-transition/20261009_1031-repeat-crash-review.json and windows-qemu-crashes.json. Repeated-outage deep audit complete.


## 2026-10-09 Delta source media audit
Bot102415111step FAIL polluted by absent required phone/rain street inputs; preserved and excluded. All five Delta original initializers omit task-specific photos. Twelve scene-matched generated reconstructions saved with hashes/provenance; initializer now verifies source/device hashes and MediaStore indexing. No requested final messages/groups/notes created; graders unchanged. Real-device validation pending. Driver crash retry deferred; resume remaining Delta/OpenPhoto groups after verification.

Media validation completed: bot initializer PASS/original baseline FAIL; device hashes and MediaStore verified; actual picker visually shows phone and rainy street. Canonical /storage/emulated/0 alias handled. All12 asset hashes/five mappings verified, unknownmapping rejected. Delta/OpenPhoto queue resumed; Driver remains excluded/deferred for alternate rendering probe.


## 2026-10-09 11:44 Delta note reader / shell input audit
Bot110816118steps modelDONE, allgroup/messages true, only noteunique false because /sdcard and /storage/emulated/0 alias counted2. Both photos genuinely sent (actual finalscreen). Delivery11261240steps modelFAIL, malformed/incomplete2line note and no group; trajectory shows leading #/literal space commands lost shellquoting. Reader now quotes filepaths and deduplicates canonical aliases, preserving distinct files; controller restores shellquoting only inputtext literals. Realdevice positive+negative reader probes pass; Markor actual screenshot confirms #spaces,%s,newline working. Originalcleanbaseline FAIL preserved. Both originalreports excluded/preserved, clean DS retests pending; no retrospective PASS absent capturednotecontents. Delta evaluator now records immutable end-state.json from reads. Mobility interrupted duringcoldreset beforemodel, retained. Deepaudit complete, counterreset. Driver alternate rendering stillpending.


## 2026-10-09 12:25 Delta clean retests
Bot114829138DONE/FAIL: real endstate contains unique note, heading+Avatar line, missing Sticker line. Group/all4messages both photos completed (actualscreen inspected); legitimate incomplete note, no new bench defect. Delivery12094414FAIL: DS incorrectly begins at step57 despite supplied full1-80, searches never-created note then givesup. Actualscreen+durable4baseline notes show no outputs, filename spaces working. Both valid modelFAIL retained.40valid/48,7PASS33FAIL,1excludedDriverexecutionerror. Queue37572/10244 healthy, Mobility running;2new completions since deepaudit, audit nextcompletion. Evidence monitor-audits/20261009_1225-delta-clean-review.json.


## 2026-10-09 12:55 Three-completion Delta deep audit
Mobility121707164DONE/FAIL valid: note River path may  be wet extra space, final Cafe bike car evidence linked absent. Actualscreen verifies attachment delivered; DONE premature. Originalgrader replay immutableendstate FAIL; independently correctnote/message eachFAIL, bothcorrect fixturePASS offline only. Bot missingSticker/Delivery starts57 remain legitimateFAIL. No confirmed newbench issue.41valid/48,7PASS34FAIL; Driverexcludedexecutionerror. Release running, queue37572/10244 healthy.3completiondeepaudit counterreset. Evidence monitor-audits/20261009_1255-delta-deep/review.json.


## 2026-10-09 13:10 Release review
Release124056130DONE/FAIL executionvalid: groupdescription actual Launch evidence and ownersners, wrong input and faulty correction in trace; required Board owns launch sequence mistyped Board%stowns%slaunch%ssequence. Noteall11linesPASS, alias/content repairs functioning, finalphoto/messages visuallyconfirmed. ValidmodelFAIL,no newbenchproblem.42valid/48,7PASS35FAIL; River running queue37572/10244.1new since deepaudit. Evidence monitor-audits/20261009_1310-release-review.json.


## 2026-10-09 13:25 River review
River130207103DONE/FAIL valid: only note_lines_present_in_order fails, expected fragments allpresent but Zoeheadline pasted into Site line, volunteersection before siteopening/communications. Trajectorylongpress relocatedcursor; original orderedrequirements justified. Group/description/messages/uniquenotePASS, actualfinalscreen photos/replies verified. No newbenchdefect.43valid/48,7PASS36FAIL; OpenPhoto preflight running, Driverexecutionerror deferred.2new since deepaudit; nextcompletion deepaudit. Evidence monitor-audits/20261009_1325-river-review.json.


## 2026-10-09 OpenPhoto SystemUI ANR recovery
Clown132317 interrupted/excluded: repeated actual SystemUIisntresponding dialogs, input-focus ANR events05:40-05:47. DSrequests sometimes128sec; API latency separate. HostRAM3.86GBavailable, no provenmemoryrootcause. SystemUIrestart835to7300+apprelaunch restores realPhotoPicker withtask2clownRGBinputs; screenshotverified. Preparation now resets SystemUI onlyOpenPhoto beforeinitializer/model, requiresnewPID, savesprovenance. Not a businessgraderchange; internalrootcauseunknown, continuemonitor. Originalrun/trajectorypreserved interrupted, cleanretestqueued.43valid/48,7PASS36FAIL,Driverexcludedexecutionerror. Evidence monitor-audits/20261009_1343-openphoto-anr/repair.json.


## 2026-10-09 14:30 OpenPhoto GL incompatibility
AfterSystemUIrepair PhotoPickerworks but repeatedPhotoRenderer GLThreadFATAL: Fragmentshaderactiveuniforms exceed GL_MAX_FRAGMENT_UNIFORM_VECTORS261. Confirmedcrash, excludeinterruptedexecution, queue34752/35300 stopped. Savedcrashlog+status. cold_reset now takesexplicit validatedGPU parameter (defaultunchanged), controlledANGLEprobe launched withoutDS. No shader/functionality/graderweakening. Resumeonlyafter actualdevice render/preflightvalidated; Driveralternateprobe pending. Evidence monitor-audits/20261009_1430-openphoto-gl.43valid/48,7PASS36FAIL.

## OpenPhoto host GPU compatibility follow-up
Host NVIDIA GTX1650 translator actual editor and exposure0->49 rendered, Saved to gallery confirmed visually, empty fresh crash log. ANGLE same261-uniform crash. Startup screencap timeout transient, later capture succeeds. run_one selects host onlyOpenPhoto, original APK/shader/businessgrader unchanged; pristine preflight pending before DS resume. Probe edits occur only in disposable cold-reset environment, not formal attempt.

Pristine host-GPU preflight144545 INITIALIZER PASS, untouched baseline evaluator FAIL as expected, original calibrated clown input actually rendered in editor. Disposable probe reset again by queue before formal DS. Resumed sameexperiment queue 23276 companion 25680; valid43 preserved, Driver retry still deferred.

## 2026-10-09 16:30 OpenPhoto deep audit
Clown145DONE/FAIL: actual save button bounds y150-276 vs repeated y122-125 taps; zero exports, premature silent-success claim. Coastal180FAIL cap while first image Cyan Hue adjustment, no exports. Actual final PNGs both inspected, original grader file/UI checks preserved. Generic end-state WebView error is unsupported native Compose telemetry, independent original file evidence stored in reviews, not grader failure. Host render/export positive probe and untouched baseline negative reviewed; no new businessbench defect confirmed.45valid/48,7PASS38FAIL. Cooking running queue23276/25680; Driverexecutionerror deferred. Deepaudit counter reset. Evidence monitor-audits/20261009_1630-photo-deep.

## 2026-10-09 17:00 Cooking review
175DONE/FAIL: two exported files independently captured, count/size/dimensions pass, original RGB tolerance12 unmet delta35-40. Real final screenshot inspected; substitute downloaded portrait16 is survey/table scene, already documented missing outdoor-cooking source variant. Model misidentifies input and may reimport exported thumbnail. Classified reconstructed-scenario failure with source-variant limitation, not unqualified originalbenchmark modelFAIL. Native generic WebView snapshot error irrelevant to independent file grader evidence.46completed reconstructed/48,7PASS39FAIL; guitarpreflight; Driverexecutionerror deferred.1new since deepaudit. Evidence monitor-audits/20261009_1700-cooking-review/review.json.

## 2026-10-09 17:44 Guitar review and follow-up
148DONE/FAIL, actual final inspected Film Amount25 vs24. Two exports size/dimensions/count pass, RGB differences25-40 fail unchanged tolerance12. Cooking/Guitar consecutive calibration failures trigger exact-settings/export compatibility deep audit before unqualified model attribution. Queue23276/25680 ended normally after47completed7PASS40FAIL; formal artifacts immutable. Driver remaining executionerror requires alternateGPUprobe. Experiment monitorstate updated, no repeated valid tasks. Evidence monitor-audits/20261009_1744-guitar-driver/guitar-review.json.

## Driver host GPU retry
Pristine host preflight175912 INITIALIZER PASS baselineFAIL; repeated form focus/type/back actualGPUProbe text captured, QEMU remainslive. First screencap20sec timeout recovered followup. Limited initialkeyboard stability only, original latertrip-message crash cause remainsunproven. Host selected onlyremainingDriver task, fresh-screenshotguard unchanged; monitored DSretry queue36788 companion30116 automatically resumed sameexperiment, completed47skip. Formalrun resets disposable probe changes. Photo calibrationdeepaudit stillpending; originaltolerance unchanged.

## Driver confirmed active-offer backend repair
180844127FAIL excluded: driver active endpoint incorrectly returned requested offer, hiding Accept. Saved full backend/status, final actualscreen and readonlygrader state. Driver endpoint excludes requested, Rider polling unchanged. Offline positive/negative passed; actualRefresh restores realAccept/Reject buttons. No automaticbusinessaccept performed. Sameexperiment automaticretry queue32508 companion14304; completed47skip, hostGPUguard retained.47completed7PASS40FAIL pendingDriver and photo calibrationaudit. Evidence monitor-audits/20261009_1830-driver-active/repair.json.

## Driver final clean retry review
183449180FAIL maxsteps valid: accepted active ride, profile/document pass,6/9messages present, noarrived, actualfinal inspected. Repeated concatenatedArriving text and wrongcoordskeyboard confusion; modelclaimSenddiscard contradicted by7durablemessages. NoQEMUcrash. OriginalreadonlyAPIstate preserved in1900-driver-review.48terminal provisional7PASS41FAIL; Photo calibrationdeepaudit stillrequired beforefinalreport/pauseheartbeat.

## Final exact calibration audit
Exact guitar settings verified via real GUI; HDR8 from source YAML (not9). Actual export maxRGBdelta28>12. Guitar excluded; Cooking conservatively excluded for same missing calibrated input/source variant.46usable reconstructed tasks7PASS39FAIL,2environment unavailable. Final score/report saved. Probe never substitutes DS formal result.

## Author-authorized photo benchmark v2
Cooking indoor and outdoor sources replaced with generated cooking scenes (downloaded20alsofishtraining). Cooking/Guitar use unclipped RGBpatches190/40and exact original recipes, four realGUI correct/repeated reference pairs. New evaluator recalibratesmedians tolerance1 plusfullimageMAE2;12positive/negativechecks pass, realdevicegroupsbothPASS, coldCookinginitPASSbaselineFAIL, fixturehashesidenticaltoreferenceinputs. Recipe/stepcaps unchanged. Old reports immutablearchived/excluded; onlytwoDSretests queued. Newreports requirefresh modelaudits eveniftaskIDalreadyreviewed. Evidence benchmark-v2/repair.json.

## Photo v2 final model audit
Cooking200334180FAIL:1export only, secondoutdoor unfinished. Guitar204943138DONE/FAIL: acoustic source selectedfirstdespiteblueelectricrequirement, bothoutputswoodsource. Actualscreenshotsinspected; originalgraderreadonlyfile/UIendstate saved. Bothfixturehashesmatchindependentreferenceinputs, referencehashesvalid, prior12positive/negative/2realdevicePASSvalidation reviewed. No newbenchdefect. Final48valid7PASS41FAIL14.58%,2v2+46retainedv1; genericNativeComposeWebViewtelemetrylimitationdisclosed. Evidence monitor-audits/20261009_2130-photo-v2-final.
