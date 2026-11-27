# iOS 源码静态审计报告（SOURCE_AUDIT）

- 审计基线：`main` @ `c365f9d`（2026-10-10，`Mark validated HF V3 submission ready for review`）。
- 审计方式：只读静态检查；未操作 GUI/模拟器，未启动模型评测或队列，未读取凭据，未推送代码，未修改业务判题。
- 审计范围：`tasks/v1/ios`、`executions/v1/ios.yaml`、`initializers/ios`（+ `evaluators/cua_review/initializers/ios`）、`evaluators/ios`、`platforms/ios`、`core/llm`、`configs/*.yaml`、`tasks/v1/manifest.json`、相关 `tests/`。
- 工作区状态：除本报告目录 `docs/ios/`（untracked）外工作树干净；其他人的修改均未动。
- 历史轨迹声明：本报告只依据上述基线源码，不把任何历史运行轨迹当作正式结果。

## 1. 执行面总览

- `executions/v1/ios.yaml` 列出 48 个 task，与 `tasks/v1/ios/*.yaml` 的 48 个文件逐字节比对（basename 排序 diff）**完全一致**。
- execution 要点：`models: [gpt5_4]`，`action_mode: code_adapter`，`observation_mode: screenshot_only`，`history_window: 3`。
- `tasks/v1/manifest.json` 中 `track == ios` 条目 48 条；`tests/test_live_release.py` 断言每平台 48 题且 execution 引用的 task 必须在 manifest 已知集合内。
- `tasks/v1/ios/oracle/` 另有 14 个 oracle task（calendar/contacts/flow/fsnotes/habit/reminders/safari 各 2），不在 v1 execution 内。

## 2. 全部 48 题：初始化 / evaluator / 资产依赖

符号验证方法：系统 `python3` + `importlib` 逐个导入每题 `init.initializer_id` 与 `evaluation.evaluator_id`（排除仅作元数据的 `original_*` 键）。
结果：**48 题现行符号全部可导入**。唯一例外是 4 个 openphotoedit evaluator 在裸系统解释器下因缺 `PIL` 导入失败，
但 `requirements.txt` / `pyproject.toml` 均已固定 `Pillow~=11.0.0`，属环境缺件而非源码缺陷（见 §5 D8）。

### 2.1 原生应用组（initializers/ios + platforms/ios/*_store，直连模拟器 sqlite）

| # | task 文件 | task_id | initializer | evaluator | 资产依赖 |
|---|-----------|---------|-------------|-----------|----------|
| 1 | calendar_finalize_schedule_with_two_followups.yaml | ios.calendar.finalize_schedule_with_two_followups | initializers.ios.calendar_seed_open_app:CalendarSeedOpenAppInitializer | evaluators.ios.calendar_event_state:CalendarEventStateEvaluator | com.apple.mobilecal；`Calendar.sqlitedb` 种子+终态比对 |
| 2 | calendar_update_and_create_followup.yaml | ios.calendar.update_and_create_followup | initializers.ios.calendar_seed_open_app:CalendarSeedOpenAppInitializer | evaluators.ios.calendar_event_state:CalendarEventStateEvaluator | 同上 |
| 3 | contacts_add_contact_card.yaml | ios.contacts.add_contact_card | initializers.ios.contacts_seed_open_app:ContactsSeedOpenAppInitializer | evaluators.ios.contacts_state:ContactsStateEvaluator | com.apple.MobileAddressBook；`AddressBook.sqlitedb` |
| 4 | contacts_reconcile_multi_field_directory.yaml | ios.contacts.reconcile_multi_field_directory | initializers.ios.contacts_seed_open_app:ContactsSeedOpenAppInitializer | evaluators.ios.contacts_state:ContactsStateEvaluator | 同上 |
| 5 | flow_add_expense_transaction.yaml | ios.flow.add_expense_transaction | initializers.ios.flow_seed_open_app:FlowSeedOpenAppInitializer | evaluators.ios.flow_state:FlowStateEvaluator | mn.flow.flow；`platforms/ios/flow_benchmark`（Flutter 记账应用源码/资源） |
| 6 | flow_rework_budget_with_transfer_and_income.yaml | ios.flow.rework_budget_with_transfer_and_income | initializers.ios.flow_seed_open_app:FlowSeedOpenAppInitializer | evaluators.ios.flow_state:FlowStateEvaluator | 同上 |
| 7 | fsnotes_archive_note_and_create_followup.yaml | ios.fsnotes.archive_note_and_create_followup | initializers.ios.fsnotes_seed_open_app:FSNotesSeedOpenAppInitializer | evaluators.ios.fsnotes_state:FSNotesStateEvaluator | co.fluder.mobile.FSNotes-iOS |
| 8 | fsnotes_move_rename_and_update_note.yaml | ios.fsnotes.move_rename_and_update_note | initializers.ios.fsnotes_seed_open_app:FSNotesSeedOpenAppInitializer | evaluators.ios.fsnotes_state:FSNotesStateEvaluator | 同上 |
| 9 | habit_manage_seeded_habits.yaml | ios.habit.manage_seeded_habits | initializers.ios.habit_seed_open_app:HabitSeedOpenAppInitializer | evaluators.ios.habit_state:HabitStateEvaluator | co.nazariizomko.Habit |
| 10 | habit_rework_seeded_routine.yaml | ios.habit.rework_seeded_routine | initializers.ios.habit_seed_open_app:HabitSeedOpenAppInitializer | evaluators.ios.habit_state:HabitStateEvaluator | 同上 |
| 11 | reminders_manage_seeded_list.yaml | ios.reminders.manage_seeded_list | initializers.ios.reminder_seed_open_app:ReminderSeedOpenAppInitializer | evaluators.ios.reminder_list_state:ReminderListStateEvaluator | com.apple.reminders |
| 12 | reminders_rework_seeded_agenda.yaml | ios.reminders.rework_seeded_agenda | initializers.ios.reminder_seed_open_app:ReminderSeedOpenAppInitializer | evaluators.ios.reminder_list_state:ReminderListStateEvaluator | 同上 |
| 13 | safari_build_two_reading_folders.yaml | ios.safari.build_two_reading_folders | initializers.ios.safari_prepare_open_app:SafariPrepareOpenAppInitializer | evaluators.ios.safari_state:SafariStateEvaluator | com.apple.mobilesafari |
| 14 | safari_organize_tabs_and_bookmarks.yaml | ios.safari.organize_tabs_and_bookmarks | initializers.ios.safari_prepare_open_app:SafariPrepareOpenAppInitializer | evaluators.ios.safari_state:SafariStateEvaluator | 同上 |
| 15 | deltachat_launch_checklist_saved_messages_4_3.yaml | ios.deltachat.launch_checklist_saved_messages_4_3 | initializers.ios.open_app:OpenAppInitializer | evaluators.ios.deltachat_launch_checklist_saved_messages_4_3:DeltaChatLaunchChecklistStateEvaluator | chat.delta（仅打开，无种子）；evaluator 读应用组容器 `accounts/*/dc.db`（要求恰好一个已绑定账号）+ FSNotes 交叉核对（`fsnotes_bundle_id: co.fluder.mobile.FSNotes-iOS`）；依赖基线 clone 自带登录态 |
| 16 | deltachat_mobile_qa_brief_saved_messages_4_1.yaml | ios.deltachat.mobile_qa_brief_saved_messages_4_1 | initializers.ios.open_app:OpenAppInitializer | evaluators.ios.deltachat_mobile_qa_brief_saved_messages_4_1:DeltaChatMobileQABriefStateEvaluator | 同上（含 `dc.db-blobs` 附件、`greenmail_local_state` 引用） |
| 17 | deltachat_route_approval_saved_messages_4_2.yaml | ios.deltachat.route_approval_saved_messages_4_2 | initializers.ios.open_app:OpenAppInitializer | evaluators.ios.deltachat_route_approval_saved_messages_4_2:DeltaChatRouteApprovalStateEvaluator | 同上 |
| 18 | deltachat_route_handoff_saved_messages_4_4.yaml | ios.deltachat.route_handoff_saved_messages_4_4 | initializers.ios.open_app:OpenAppInitializer | evaluators.ios.deltachat_route_handoff_saved_messages_4_4:DeltaChatRouteHandoffStateEvaluator | 同上 |

### 2.2 移植应用组（initializer 来自 `evaluators/cua_review/initializers/ios`，状态经 `DEVICE_ROOT`/容器读取）

| # | task 文件 | task_id | initializer | evaluator | 资产依赖 |
|---|-----------|---------|-------------|-----------|----------|
| 19 | maily_instruction_3_1.yaml | ios.maily.instruction_3_1 | evaluators.cua_review.initializers.ios.maily_open_app:MailyOpenAppInitializer | evaluators.ios.maily_instruction_3_1:MailyInstruction31StateEvaluator | de.enough.maily；起点为客户端账号列表，需基线已配账号（README 要求 GreenMail + 基线模拟器配好邮件账号） |
| 20 | maily_instruction_3_2.yaml | ios.maily.instruction_3_2 | evaluators.cua_review.initializers.ios.maily_open_app:MailyOpenAppInitializer | evaluators.ios.maily_instruction_3_2:MailyInstruction32StateEvaluator | 同上 |
| 21 | maily_instruction_3_3.yaml | ios.maily.instruction_3_3 | evaluators.cua_review.initializers.ios.maily_open_app:MailyOpenAppInitializer | evaluators.ios.maily_instruction_3_3:MailyInstruction33Round9StateEvaluator | 同上 |
| 22 | openbank_2_2_transfer_security_448872.yaml | ios.openbank.2_2.transfer_security_448872 | evaluators.cua_review.initializers.ios.openbank_open_app:OpenBankOpenAppInitializer | evaluators.ios.openbank_2_2_transfer_security_448872:OpenBankTransferSecurity448872Evaluator | com.killt.openbank；容器内状态（`DEVICE_ROOT`） |
| 23 | openbank_card_rebate_dispute_183183.yaml | ios.openbank.card_rebate_dispute_183183 | evaluators.cua_review.initializers.ios.openbank_open_app:OpenBankOpenAppInitializer | evaluators.ios.openbank_card_rebate_dispute_183183:OpenBankCardRebateDispute183183Evaluator | 同上 |
| 24 | openbank_lena_marco_dispute_security_086132.yaml | ios.openbank.lena_marco_dispute_security_086132 | evaluators.cua_review.initializers.ios.openbank_open_app:OpenBankOpenAppInitializer | evaluators.ios.openbank_lena_marco_dispute_security_086132:OpenBankLenaMarcoDisputeSecurity086132Evaluator | 同上 |
| 25 | opendriver_11-1.yaml | ios.opendriver.11-1 | evaluators.cua_review.initializers.ios.opendriver_open_app:OpenDriverOpenAppInitializer | evaluators.ios.opendriver_11-1:OpenDriverStateEvaluator | com.killt.opendriver（注意 evaluator 文件名含连字符，见 §5 D1） |
| 26 | opendriver_11-2.yaml | ios.opendriver.11-2 | evaluators.cua_review.initializers.ios.opendriver_open_app:OpenDriverOpenAppInitializer | evaluators.ios.opendriver_11-2:OpenDriverState112Evaluator | 同上 |
| 27 | opendriver_driver_payout_trip_support_profile.yaml | ios.opendriver.driver_payout_trip_support_profile | evaluators.cua_review.initializers.ios.opendriver:OpenDriverIOSInitializer | evaluators.ios.opendriver_driver_payout_trip_support_profile:OpenDriverIOSDriverWorkflowEvaluator | com.killt.opendriver |
| 28 | opendriver_driver_requests_insurance_support_payout.yaml | ios.opendriver.driver_requests_insurance_support_payout | evaluators.cua_review.initializers.ios.opendriver:OpenDriverIOSInitializer | evaluators.ios.opendriver_driver_requests_insurance_support_payout:OpenDriverIOSDriverWorkflowEvaluator | 同上 |
| 29 | opennote_community_meal_three_notes_618106.yaml | ios.opennote.community_meal_three_notes_618106 | evaluators.cua_review.initializers.ios.opennote_open_app:OpenNoteOpenAppInitializer | evaluators.ios.opennote_community_meal_three_notes_618106:OpenNoteCommunityMealThreeNotes618106Evaluator | com.killt.opennote |
| 30 | opennote_forum_outfit_three_notes_194503.yaml | ios.opennote.forum_outfit_three_notes_194503 | evaluators.cua_review.initializers.ios.opennote_open_app:OpenNoteOpenAppInitializer | evaluators.ios.opennote_forum_outfit_three_notes_194503:OpenNoteForumOutfitThreeNotes194503Evaluator | 同上 |
| 31 | opennote_live_music_visuals_three_notes_495011.yaml | ios.opennote.live_music_visuals_three_notes_495011 | evaluators.cua_review.initializers.ios.opennote_open_app:OpenNoteOpenAppInitializer | evaluators.ios.opennote_live_music_visuals_three_notes_495011:OpenNoteLiveMusicVisualsThreeNotes495011Evaluator | 同上 |
| 32 | opennote_stage_makeup_three_notes_870344.yaml | ios.opennote.stage_makeup_three_notes_870344 | evaluators.cua_review.initializers.ios.opennote_open_app:OpenNoteOpenAppInitializer | evaluators.ios.opennote_stage_makeup_three_notes_870344:OpenNoteStageMakeupThreeNotes870344Evaluator | 同上 |
| 33 | openphotoedit_community_activity_cards_memory_482863.yaml | ios.openphotoedit.community_activity_cards_memory_482863 | evaluators.cua_review.initializers.ios.openphotoedit_community_activity_cards_memory_482863:OpenPhotoEditCommunityActivityCardsMemory482863Initializer | evaluators.ios.openphotoedit_community_activity_cards_memory_482863:OpenPhotoEditCommunityActivityCardsMemory482863Evaluator | com.killt.openphotoedit；RGB-marker 图像比对，需 Pillow |
| 34 | openphotoedit_music_media_portraits_four_exports_186365.yaml | ios.openphotoedit.music_media_portraits_four_exports_186365 | evaluators.cua_review.initializers.ios.openphotoedit_music_media_portraits_four_exports_186365:OpenPhotoEditMusicMediaPortraitsFourExports186365Initializer | evaluators.ios.openphotoedit_music_media_portraits_four_exports_186365:OpenPhotoEditMusicMediaPortraitsFourExports186365Evaluator | 同上 |
| 35 | openphotoedit_outdoor_brand_four_exports_memory_enhanced_429078.yaml | ios.openphotoedit.outdoor_brand_four_exports_memory_enhanced_429078 | evaluators.cua_review.initializers.ios.openphotoedit_outdoor_brand_four_exports_memory_enhanced_429078:OpenPhotoEditOutdoorBrandFourExportsMemoryEnhanced429078Initializer | evaluators.ios.openphotoedit_outdoor_brand_four_exports_memory_enhanced_429078:OpenPhotoEditOutdoorBrandFourExportsMemoryEnhanced429078Evaluator | 同上 |
| 36 | openphotoedit_theater_visuals_four_exports_137027.yaml | ios.openphotoedit.theater_visuals_four_exports_137027 | evaluators.cua_review.initializers.ios.openphotoedit_theater_visuals_four_exports_137027:OpenPhotoEditTheaterVisualsFourExports137027Initializer | evaluators.ios.openphotoedit_theater_visuals_four_exports_137027:OpenPhotoEditTheaterVisualsFourExports137027Evaluator | 同上 |
| 37 | openshop_beauty_office_checkout_review_807073.yaml | ios.openshop.beauty_office_checkout_review_807073 | evaluators.cua_review.initializers.ios.openshop_login_entry:OpenShopLoginEntryInitializer | evaluators.ios.openshop_beauty_office_checkout_review_807073:OpenShopBeautyOfficeCheckoutReview807073Evaluator | com.killt.openshop（登录入口初始化） |
| 38 | openshop_coffee_baby_dual_checkout_958608.yaml | ios.openshop.coffee_baby_dual_checkout_958608 | evaluators.cua_review.initializers.ios.openshop_login_entry:OpenShopLoginEntryInitializer | evaluators.ios.openshop_coffee_baby_dual_checkout_958608:OpenShopCoffeeBabyDualCheckout958608Evaluator | 同上 |
| 39 | openshop_home_four_item_cart_checkout_368575.yaml | ios.openshop.home_four_item_cart_checkout_368575 | initializers.ios.open_app:OpenAppInitializer | evaluators.ios.openshop_home_four_item_cart_checkout_368575:OpenShopHomeFourItemCartCheckout368575Evaluator | com.killt.openshop（仅打开） |
| 40 | openshop_trip_gear_dual_checkout_review_263796.yaml | ios.openshop.trip_gear_dual_checkout_review_263796 | evaluators.cua_review.initializers.ios.openshop_instruction_entry:OpenShopInstructionEntryInitializer | evaluators.ios.openshop_trip_gear_dual_checkout_review_263796:OpenShopTripGearDualCheckoutReview263796Evaluator | com.killt.openshop（instruction 入口初始化） |
| 41 | opentrip_nr2269_sanya_seabreeze_booking_158915.yaml | ios.opentrip.nr2269_sanya_seabreeze_booking_158915 | evaluators.cua_review.initializers.ios.opentrip_instruction_entry:OpenTripInstructionEntryInitializer | evaluators.ios.opentrip_nr2269_sanya_seabreeze_booking_158915:OpenTripNr2269SanyaSeabreezeBooking158915Evaluator | com.killt.opentrip |
| 42 | opentrip_review_flight_hotel_reschedule_234497.yaml | ios.opentrip.review_flight_hotel_reschedule_234497 | evaluators.cua_review.initializers.ios.opentrip_instruction_entry:OpenTripInstructionEntryInitializer | evaluators.ios.opentrip_review_flight_hotel_reschedule_234497:OpenTripReviewFlightHotelReschedule234497Evaluator | 同上 |
| 43 | opentrip_sanya_parkline_review_mj2158_638214.yaml | ios.opentrip.sanya_parkline_review_mj2158_638214 | evaluators.cua_review.initializers.ios.opentrip_sanya_parkline_review_mj2158_638214:OpenTripSanyaParklineReviewMj2158638214Initializer | evaluators.ios.opentrip_sanya_parkline_review_mj2158_638214:OpenTripSanyaParklineReviewMj2158638214Evaluator | 同上 |
| 44 | opentrip_sc2306_grand_axis_booking_284952.yaml | ios.opentrip.sc2306_grand_axis_booking_284952 | evaluators.cua_review.initializers.ios.opentrip_sc2306_grand_axis_entry_284952:OpenTripSc2306GrandAxisEntry284952Initializer | evaluators.ios.opentrip_sc2306_grand_axis_booking_284952:OpenTripSc2306GrandAxisBooking284952Evaluator | 同上 |
| 45 | opentwitter_accessibility_audit_engagement_567657.yaml | ios.opentwitter.accessibility_audit_engagement_567657 | evaluators.cua_review.initializers.ios.opentwitter_accessibility_audit_engagement_567657:OpenTwitterAccessibilityAuditEngagement567657Initializer | evaluators.ios.opentwitter_accessibility_audit_engagement_567657:OpenTwitterAccessibilityAuditEngagement567657Evaluator | com.killt.opentwitter；读 WebKit localStorage，不做 GUI 判题 |
| 46 | opentwitter_incident_engagement_profile_451238.yaml | ios.opentwitter.incident_engagement_profile_451238 | evaluators.cua_review.initializers.ios.opentwitter_open_app:OpenTwitterOpenAppInitializer | evaluators.ios.opentwitter_incident_engagement_profile_451238:OpenTwitterIncidentEngagementProfile451238Evaluator | 同上 |
| 47 | opentwitter_release_gate_engagement_245250.yaml | ios.opentwitter.release_gate_engagement_245250 | evaluators.cua_review.initializers.ios.opentwitter_open_app:OpenTwitterOpenAppInitializer | evaluators.ios.opentwitter_release_gate_engagement_245250:OpenTwitterReleaseGateEngagement245250Evaluator | 同上 |
| 48 | opentwitter_transit_signal_engagement_483271.yaml | ios.opentwitter.transit_signal_engagement_483271 | evaluators.cua_review.initializers.ios.opentwitter_open_app:OpenTwitterOpenAppInitializer | evaluators.ios.opentwitter_transit_signal_engagement_483271:OpenTwitterTransitSignalEngagement483271Evaluator | 同上 |

## 3. Runner 命令与重置 / 截图 / 坐标 / 终态流程

### 3.1 当前 runner 命令

- 公开入口（`platforms/ios/cli.py`）：`python3 -m platforms.ios.cli --execution executions/v1/ios.yaml`。
  依次读取 execution（`runtime_config.load_execution_handoff`）与 `configs/ios.yaml`（`load_ios_runtime_config`），
  按 model × task 串行调用 `platforms/ios/runners/benchmark.py:run_benchmark_command`，结果写入
  `results/<model>/ios/<execution>_<timestamp>/`。action/observation/history 非法值直接抛 `ValueError`。
- 内部单题命令：`... cli.py __benchmark_job --task-file <task> --execution-file <exec> --model <id>
  --action-mode code_adapter --observation-mode screenshot_only --history-window 3 --udid <clone> ...`。
- README 另提到 `python scripts/run_benchmark.py --execution ...`，但同文件注明该校验入口“暂时没用不用做”；
  以 `cli.py` 为准。

### 3.2 重置流程（`runners/benchmark.py` + `runtime_env/simulator_manager.py`）

`clone -> run -> delete`，串行：源模拟器关机等待 → `xcrun simctl clone <source> <name>`（3 次重试）
→ clone 关机等待 → `boot` + `bootstatus -b` → 建 Appium 会话执行 → `shutdown` + `delete` 临时 clone。
源模拟器本身从不 erase；Appium 能力固定 `noReset: True`（`runtime.py:get_device_capabilities`）。
因此题间隔离 = 新 clone，题内初始态 = initializer 负责；基线 UDID 来自 `configs/ios.yaml`
（当前值为 `9FF31490-...`，换机必须重配）。

### 3.3 截图流程

- 每步与终态截图均来自 WDA `driver.get_screenshot_as_png()`（`runtime.py:save_screenshot`），
  落盘 `<run>/screenshots/step_<n>_<ts>.png` 与 `final.png`；`simulator_manager.take_screenshot`
 （`simctl io screenshot`）在当前 runner 路径中未被调用。
- 是否送模型由 `observation_mode` 决定；v1 execution 为 `screenshot_only`，即纯截图 + 坐标动作。

### 3.4 坐标流程

- 统一使用 Appium 逻辑坐标（`get_window_size`）：节点中心 `rect -> tap/tap_norm`（`observation.py:summarize_ui_tree`）；
  动作目标三形态（`runtime.py:_parse_target`）：节点 id、`[x, y]` 像素直通、`{"x","y"}` 0..1 归一化经
  `_norm_to_px` 换算；`tap/doubleTap/touchAndHold/dragFromToForDuration` 均为 `mobile:` 直调。
- prompt 侧（`agent/prompt_builder.py`、`runners/base_episode.py:98-116`）向模型提供
  `viewportRect` 与相对位置换算提示；`code_adapter` 下 prompt 内 observation_mode 被强制为 `screenshot_only`。

### 3.5 终态与判题流程

`base_episode`：initializer（`runners/initialization.py`，失败则整题 ERROR）→ 多步 agent 循环 →
`_observe_final_state`（UI 树 + `final.png`）→ `run_task_evaluation`（`runners/evaluation.py`）：
以 `load_evaluator(evaluation.evaluator_id)` 构造，上下文仅 `{params, controller, final_observation}`，
并自动注入运行期 `udid`；`PASS/FAIL -> 终态`，异常/`ERROR` -> `ERROR`。判题一律读终态（sqlite/容器/localStorage），
除 deltachat 系列读取既有进程与介质外，task YAML 内均声明 eval-only 不得做 GUI/初始化（元数据约束，非代码强制）。

## 主代理复核（2026-10-10）

以下是静态审计而非正式模型结果。§4.2/D3 关于当前 DeepSeek 官方不支持 deepseek-flash/Responses/none 的判断已被现场官方文档否定，不能作为修复依据。当前官方 Responses API 支持 deepseek-flash 图像输入，reasoning.effort=none 关闭思考；基址为 https://api.deepseek.com。文档来源：https://api-docs.deepseek.com/guides/responses_api/ 与 https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/。正式开测前仍需实际请求探针。不要按 D3 切换模型或协议。D1 的 importlib 加载已成功，不能仅因模块带连字符认定 runner 缺陷；D2 original_* 是历史来源元数据，不应擅自删除。其他条目是待真实环境验证的风险，不是已复现故障。

## 4. `deepseek_flash` + `reasoning_effort=none` 核查

配置原文（`configs/models.yaml:336-344`）：`provider: openai`，`model_name: deepseek-flash`，
`api_key_env: DEEPSEEK_API_KEY`，`base_url_env: DEEPSEEK_BASE_URL`，`max_output_tokens: 4096`，
`metadata: {api_mode: responses, reasoning_effort: none}`。

### 4.1 `none` 是否真正进入请求——是（静态链路追踪，未发任何网络请求）

1. `core/llm/llm_client.py:454-457`（`_load_model_parameters`）：`reasoning_effort` 非空字符串即收入
   `parameters["reasoning_effort"]`——`"none".strip()` 非空，故 `parameters = {..., "reasoning_effort": "none"}`。
2. `core/llm/providers/base.py:208-227`（`_apply_common_parameters`，responses 分支）：
   `parameters` 命中则覆盖 `default_reasoning_effort("high")`，得 `payload["reasoning"] = {"effort": "none"}`。
3. `core/llm/providers/base.py:144,155-167`（`_build_responses_payload`）：先弹掉顶层 `reasoning_effort`，
   再按 `metadata.reasoning_effort` 回填 `reasoning.effort = "none"`。
4. `invoke`（`base.py:97-102`）按 `api_mode=responses` 经 `resolve_responses_url` 发往 `<base>/responses`。

最终线载荷为 `{"model": "deepseek-flash", "reasoning": {"effort": "none"}, ...}`（另有 `max_output_tokens: 4096`）。
因本机解释器缺 `httpx`/`yaml` 且审计禁止发请求，以上是逐行静态结论，未做执行验证；
`tests/` 下无任何 `reasoning_effort` 单测可作旁证。

### 4.2 需要何种 API base URL

- `DEEPSEEK_BASE_URL`（`*_env` 形式，无字面默认值）：必须指向一个同时满足两点的网关——
  (a) 以 OpenAI Responses 协议在 `<base>/responses` 应答；(b) 实际提供模型 id `deepseek-flash`。
- 两点均存疑，需向网关提供方确认后再跑，**不要直接开测**：
  (a) `reasoning.effort="none"` 不是 OpenAI Responses 公开取值（公开为 minimal/low/medium/high 等），
  严格网关可能 400；(b) `deepseek-flash` 不是 DeepSeek 官方公开模型 id（官方为 `deepseek-chat`/`deepseek-reasoner`），
  参考 `docs/android/environment.example` 与 `HANDOVER.md` 亦只写 `DEEPSEEK_BASE_URL=https://api.deepseek.com`
  且要求“网关实际暴露该模型与 Responses 协议”。
- 附带发现：`deepseek_chat` 条目（`provider: deepseek`，chat_completions）解析为 `<base>/chat/completions`，
  而官方文档基址带 `/v1` 前缀——现有字面 `https://api.deepseek.com` 是否缺 `/v1` 未经证实，一并向网关确认。

## 5. 可复现源码缺陷与最小修复建议（均未动手，仅审计）

- D1 连字符模块名：`evaluators/ios/opendriver_11-1.py`、`opendriver_11-2.py`。
  `importlib` 可导入，但 `from evaluators.ios.opendriver_11-1 import …` 为语法错误，lint/静态导入与部分测试收集写法会坏。
  最小修复：改名为 `opendriver_11_1.py` / `opendriver_11_2.py`，同步改两处 task 的 `evaluator_id`，类名不动。
- D2 陈旧 `original_*` 元数据：约 30 个 task 的 `metadata.original_evaluator_id / original_initializer_id`
  指向不存在的模块（`initializers.ios.maily_open_app`、`evaluators.ios.*_evaluator`、
  `evaluators.ios.opendriver_state` 等）。`core` 三个 loader 均不读 `original_` 前缀，无运行时影响，
  但会误导审计与复现者。最小修复：删除或更正这些元数据键（不动现行 `init/evaluation`）。
- D3 `reasoning_effort: none` 的网关兼容风险（见 §4.2）。最小修复：为 deepseek 另设
  `api_mode: chat_completions` 且不带 `reasoning_effort` 的条目（如既有 `deepseek_chat` 形状），或先以单条
  Responses 手工探针确认网关接受 `"none"` 后再用于评测。
- D4 DeltaChat 4 题无种子初始化（`OpenAppInitializer` 仅打开），而 evaluator 硬要求容器内恰好一个已绑定
  `dc.db` 账号：复现性完全系于基线 clone 的隐含登录态，换机/重建基线即挂。最小修复：在 task 或 initializer
  侧显式声明基线前置条件并做前置断言（缺账号时报清晰 ERROR 而非 FAIL），或补一个幂等种子 initializer。
- D5 同类弱依赖：maily（GreenMail + 基线配号）、openbank/opentrip/openshop/opentwitter/opennote/opendriver
  的 cua_review 初始化器同样依赖基线登录/预置态。最小修复：同 D4，把 README §3/§4 的手工基线步骤沉淀为
  每个受影响 task 的 `prerequisites` + 初始化前置检查。
- D6 `configs/ios.yaml` 已提交机器相关的 `source_simulator_udid`。最小修复：换机复现时重写该值；
  建议后续以环境变量覆盖而非提交本机 UDID（现状不动）。
- D7 `executions/v1/ios.yaml` 的 `models` 仅含 `gpt5_4`，`deepseek_flash` 不在执行面内——§4 结论为配置层结论，
  任何 flash 实测都需另改 execution（本次不动）。
- D8 openphotoedit evaluator 顶层 `from PIL import …`：裸解释器下 evaluator 加载即失败；
  仓库已在 `requirements.txt`/`pyproject.toml` 固定 Pillow，用仓库 venv 即无事。无需源码改动。

## 6. 本次未做事项

未操作模拟器/GUI（含 Appium、`simctl`），未启动任何模型评测或队列，未读取凭据（`DEEPSEEK_API_KEY` 等仅核对 env 名），
未推送代码，未改业务判题；pytest 未执行（可用解释器缺依赖，安装依赖超出只读审计授权）。报告落盘后即停止。
