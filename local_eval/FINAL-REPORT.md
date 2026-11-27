# 作者修订版 Android OS-Omni DeepSeek Flash 最终报告

48/48题均完成：7 PASS、41 FAIL，通过率14.58%。本轮两道图片题已修复并有效重测，不再因缺失照片/校准环境排除。当前结果没有未解决的环境、运行器或执行错误；历史受污染尝试仍保留并排除。

DeepSeek Flash，reasoning_effort=none，每题最多180步，保留原先更小上限。未代替DS执行正式任务。

## 图片v2的修复与验证

作者授权重新生成丢失素材并修订evaluation。Cooking室内/户外源图均替换为新生成的烹饪场景（原下载室内图也是鱼类培训场景）。Guitar复用下载源图。Cooking/Guitar改用不易截断的RGB校准块，原操作参数与指令、步数上限不变。

四套参考成片由真实模拟器上的原APK按精确参数生成，所有滑块值有nativeUI证据；重复导出一致。新判题保留导出数量、尺寸、大小、初始baseline排除与最后编辑器检查，使用校准值容差1和整图MAE<=2绑定正确来源及成片。它检查图像结果，不声称能够区分所有渲染效果相同的内部参数组合。

12组正反例、两题真实设备完整判题PASS、冷启动initializerPASS/未编辑baselineFAIL验证通过。正式两题初始化fixture哈希与参考输入完全一致，参考文件校验和有效。版本/来源/提示词/验证记录见benchmark-v2/README.md、repair.json、validation.json、real-device-validation.json及assets/generation-prompts.md。

## 两题重测失败审计

Cooking：180步耗尽，只导出一张室内成片，仍在调整户外照片，没有第二张导出。室内整图MAE1.213、RGB最大差2（超过容差1），但缺少户外导出已能独立判定未完成，不依赖这一校准边界。实际最终截图及只读文件/UI证据已审阅。

Guitar：138步后自行宣告DONE；第一次导入了白色木/声学吉他，模型发现与蓝色电吉他要求不符却继续编辑。两张输出均接近木吉他来源，未生成要求的电吉他成片；最终Film24正确不能弥补选图错误。早期、最终真实截图、轨迹及原始grader文件证据已核对。独立审计见monitor-audits/20261009_2130-photo-v2-final。

原生Compose图片应用不支持通用WebView end-state采集，end-state-error.json属于通用遥测限制；判题使用独立只读UI/文件证据，已保存end-state-from-grader.json，不能将该遥测错误误认为DS执行或判题错误。

## 版本与历史结果

当前48题成绩由2道作者图片v2任务重测和46道保留的有效v1结果组成，属于混合版本修订套件。旧两题尝试和旧7/46成绩在benchmark-v2/legacy，未被修改成PASS；作者参考探针不计入DS成绩。

此前已修复后端、登录、种子数据、导航记录、路径引号、GPU与新鲜截图保护；Driver requested offer隐藏Accept问题修复后重测，180步内未完成到达及全部必需消息，记模型失败。银行Details故障说法已被实际坐标/事件审计反驳。修复范围见FAILURE-AUDIT.md和各题provenance。

作者授权重建使新版定义可用，但这些结果仍不能当成丢失旧快照版本的逐项复现；应用/后端重建和版本差异应随成绩披露。

## 逐题结果

|任务|版本|结果|步数|报告|
|---|---|---|---:|---|
|android.deltachat.bot_evidence_device_location_684193|reconstructed-suite-v1|FAIL|138|.\local_eval\runs\android.deltachat.bot_evidence_device_location_684193\20261009_114829\result.json|
|android.deltachat.delivery_claim_record_1787390185793_240468|reconstructed-suite-v1|FAIL|14|.\local_eval\runs\android.deltachat.delivery_claim_record_1787390185793_240468\20261009_120944\result.json|
|android.deltachat.mobility_safety_actual_input_1787395000000_739204|reconstructed-suite-v1|FAIL|164|.\local_eval\runs\android.deltachat.mobility_safety_actual_input_1787395000000_739204\20261009_121707\result.json|
|android.deltachat.release_control_room_1787364494557_711349|reconstructed-suite-v1|FAIL|130|.\local_eval\runs\android.deltachat.release_control_room_1787364494557_711349\20261009_124056\result.json|
|android.deltachat.river_park_action_team_1787372393006_488939|reconstructed-suite-v1|FAIL|103|.\local_eval\runs\android.deltachat.river_park_action_team_1787372393006_488939\20261009_130207\result.json|
|android.openbank.ace_dispute_paperless_security_lena_marco_1787394510087_195225|reconstructed-suite-v1|FAIL|58|.\local_eval\runs\android.openbank.ace_dispute_paperless_security_lena_marco_1787394510087_195225\20261008_163042\result.json|
|android.openbank.ace_tessa_security_city_nora_1787392720204_995198|reconstructed-suite-v1|FAIL|19|.\local_eval\runs\android.openbank.ace_tessa_security_city_nora_1787392720204_995198\20261008_172328\result.json|
|android.openbank.card_rebate_dispute_1787391981468_550137|reconstructed-suite-v1|FAIL|108|.\local_eval\runs\android.openbank.card_rebate_dispute_1787391981468_550137\20261008_184951\result.json|
|android.openbank.city_rainy_lena_marco_security_1787396657268_013944|reconstructed-suite-v1|FAIL|140|.\local_eval\runs\android.openbank.city_rainy_lena_marco_security_1787396657268_013944\20261008_193315\result.json|
|android.openbank.lena_marco_dispute_security_paperless_1787390266564_553878|reconstructed-suite-v1|FAIL|133|.\local_eval\runs\android.openbank.lena_marco_dispute_security_paperless_1787390266564_553878\20261008_195142\result.json|
|android.openbank.maya_leo_security_dispute_payment_paperless_transfer_1787397914946_938252|reconstructed-suite-v1|FAIL|94|.\local_eval\runs\android.openbank.maya_leo_security_dispute_payment_paperless_transfer_1787397914946_938252\20261008_181934\result.json|
|android.opendriver.driver_workspace_support_ticket_final|reconstructed-suite-v1|PASS|94|.\local_eval\runs\android.opendriver.driver_workspace_support_ticket_final\20261009_075736\result.json|
|android.opendriver.rider_full_service_logout|reconstructed-suite-v1|FAIL|68|.\local_eval\runs\android.opendriver.rider_full_service_logout\20261009_081237\result.json|
|android.opendriver.rider_three_scheduled_bay_rides_20260729|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.opendriver.rider_three_scheduled_bay_rides_20260729\20261009_092137\result.json|
|android.opendriver.seeded_driver_profile_document_arrival_5930_20260729|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.opendriver.seeded_driver_profile_document_arrival_5930_20260729\20261009_183449\result.json|
|android.openfood.dumpling_biryani_coupon_merchant_clean_20260731|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.openfood.dumpling_biryani_coupon_merchant_clean_20260731\20261009_040636\result.json|
|android.openfood.poke_sushi_wallet_merchant_clean_20260729|reconstructed-suite-v1|FAIL|78|.\local_eval\runs\android.openfood.poke_sushi_wallet_merchant_clean_20260729\20261009_050848\result.json|
|android.openfood.smokehouse_espresso_feast20_merchant_clean_20260801|reconstructed-suite-v1|FAIL|128|.\local_eval\runs\android.openfood.smokehouse_espresso_feast20_merchant_clean_20260801\20261009_052511\result.json|
|android.openfood.smokehouse_pizza_merchant_ops_clean_20260729|reconstructed-suite-v1|FAIL|141|.\local_eval\runs\android.openfood.smokehouse_pizza_merchant_ops_clean_20260729\20261009_054615\result.json|
|android.opennavigation.meta_campus_transit_records_20260803|reconstructed-suite-v1|PASS|91|.\local_eval\runs\android.opennavigation.meta_campus_transit_records_20260803\20261009_062700\result.json|
|android.opennavigation.saved_routes_incidents_records_20260801|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.opennavigation.saved_routes_incidents_records_20260801\20261009_064549\result.json|
|android.opennavigation.silicon_station_campus_records_20260803|reconstructed-suite-v1|PASS|138|.\local_eval\runs\android.opennavigation.silicon_station_campus_records_20260803\20261009_073821\result.json|
|android.opennote.city_food_469121|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.opennote.city_food_469121\20261008_200759\result.json|
|android.opennote.fashion_trip_970990|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.opennote.fashion_trip_970990\20261008_203739\result.json|
|android.opennote.film_beauty_573866|reconstructed-suite-v1|FAIL|173|.\local_eval\runs\android.opennote.film_beauty_573866\20261008_210825\result.json|
|android.opennote.fitness_mind_940880|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.opennote.fitness_mind_940880\20261008_213501\result.json|
|android.opennote.gaming_home_461774|reconstructed-suite-v1|FAIL|90|.\local_eval\runs\android.opennote.gaming_home_461774\20261008_220419\result.json|
|android.opennote.style_home_477136|reconstructed-suite-v1|FAIL|77|.\local_eval\runs\android.opennote.style_home_477136\20261008_222609\result.json|
|android.openphoto.clown_dual_calibrated_export_20260804|reconstructed-suite-v1|FAIL|145|.\local_eval\runs\android.openphoto.clown_dual_calibrated_export_20260804\20261009_145513\result.json|
|android.openphoto.coastal_dual_calibrated_export_20260803|reconstructed-suite-v1|FAIL|180|.\local_eval\runs\android.openphoto.coastal_dual_calibrated_export_20260803\20261009_152932\result.json|
|android.openphoto.cooking_dual_calibrated_export_20260804|author-rebuilt-photo-v2|FAIL|180|.\local_eval\runs\android.openphoto.cooking_dual_calibrated_export_20260804\20261009_200334\result.json|
|android.openphoto.guitar_dual_calibrated_export_20260804|author-rebuilt-photo-v2|FAIL|138|.\local_eval\runs\android.openphoto.guitar_dual_calibrated_export_20260804\20261009_204943\result.json|
|android.openshop.beauty_care_checkout_review_20260821|reconstructed-suite-v1|FAIL|100|.\local_eval\runs\android.openshop.beauty_care_checkout_review_20260821\20261009_003756\result.json|
|android.openshop.commute_summary_order_review|reconstructed-suite-v1|FAIL|95|.\local_eval\runs\android.openshop.commute_summary_order_review\20261009_005546\result.json|
|android.openshop.family_weekend_checkout_20260821|reconstructed-suite-v1|FAIL|100|.\local_eval\runs\android.openshop.family_weekend_checkout_20260821\20261009_011336\result.json|
|android.openshop.garage_setup_checkout_backpack_review_20260821|reconstructed-suite-v1|FAIL|96|.\local_eval\runs\android.openshop.garage_setup_checkout_backpack_review_20260821\20261009_013200\result.json|
|android.openshop.gift_trip_bundle_checkout_document_review_20260821|reconstructed-suite-v1|FAIL|178|.\local_eval\runs\android.openshop.gift_trip_bundle_checkout_document_review_20260821\20261009_015028\result.json|
|android.openshop.home_refresh_2026_alipay_checkout|reconstructed-suite-v1|FAIL|100|.\local_eval\runs\android.openshop.home_refresh_2026_alipay_checkout\20261009_021710\result.json|
|android.opentrip.flight_voucher_baggage_booking|reconstructed-suite-v1|PASS|52|.\local_eval\runs\android.opentrip.flight_voucher_baggage_booking\20261009_023558\result.json|
|android.opentrip.hotel_voucher_family_suite_booking|reconstructed-suite-v1|FAIL|112|.\local_eval\runs\android.opentrip.hotel_voucher_family_suite_booking\20261009_024838\result.json|
|android.opentrip.seed_hotel_review_wallet_audit|reconstructed-suite-v1|PASS|55|.\local_eval\runs\android.opentrip.seed_hotel_review_wallet_audit\20261009_031007\result.schema-corrected.json|
|android.opentrip.seed_orders_reschedule|reconstructed-suite-v1|PASS|64|.\local_eval\runs\android.opentrip.seed_orders_reschedule\20261009_033746\result.schema-corrected.json|
|android.opentwitter.01_release_review_coordination|reconstructed-suite-v1|FAIL|47|.\local_eval\runs\android.opentwitter.01_release_review_coordination\20261008_224720\result.json|
|android.opentwitter.03_research_search_coordination|reconstructed-suite-v1|FAIL|22|.\local_eval\runs\android.opentwitter.03_research_search_coordination\20261008_225653\result.json|
|android.opentwitter.04_mobile_incident_frontend_audit|reconstructed-suite-v1|FAIL|32|.\local_eval\runs\android.opentwitter.04_mobile_incident_frontend_audit\20261008_230535\result.json|
|android.opentwitter.05_security_billing_api_audit|reconstructed-suite-v1|PASS|121|.\local_eval\runs\android.opentwitter.05_security_billing_api_audit\20261008_231613\result.json|
|android.opentwitter.changelog_follow_audit_workflow_20260822|reconstructed-suite-v1|FAIL|100|.\local_eval\runs\android.opentwitter.changelog_follow_audit_workflow_20260822\20261008_233451\result.json|
|android.opentwitter.focus_research_community_workflow_20260822_v2|reconstructed-suite-v1|FAIL|96|.\local_eval\runs\android.opentwitter.focus_research_community_workflow_20260822_v2\20261008_235241\result.json|
