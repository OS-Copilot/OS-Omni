# DeepSeek Flash Android 评测进度

> 最终审计：46题可用于重建环境评分，7 PASS、39 FAIL（15.22%）；2题因照片校准环境缺失排除。下方保留48题原始跑分，最终分类见 local_eval/FINAL-REPORT.md。

正式队列：已完成 48/48，PASS 7，FAIL 41；环境错误 0，运行器错误 0，执行错误 0。

这是重建环境评测。缺失原始快照、替代后端、照片来源差异和判题兼容修复见 local_eval/README.md 与每题 provenance。首次 Python 3.14 环境试跑不纳入正式计数。

| 任务 | 状态 | 修复判分 | 原始判分 | 步数 |
|---|---|---|---|---|
| android.deltachat.bot_evidence_device_location_684193 | completed | FAIL | FAIL | 138 |
| android.deltachat.delivery_claim_record_1787390185793_240468 | completed | FAIL | FAIL | 14 |
| android.deltachat.mobility_safety_actual_input_1787395000000_739204 | completed | FAIL | FAIL | 164 |
| android.deltachat.release_control_room_1787364494557_711349 | completed | FAIL | FAIL | 130 |
| android.deltachat.river_park_action_team_1787372393006_488939 | completed | FAIL | FAIL | 103 |
| android.openbank.ace_dispute_paperless_security_lena_marco_1787394510087_195225 | completed | FAIL | FAIL | 58 |
| android.openbank.ace_tessa_security_city_nora_1787392720204_995198 | completed | FAIL | FAIL | 19 |
| android.openbank.card_rebate_dispute_1787391981468_550137 | completed | FAIL | FAIL | 108 |
| android.openbank.city_rainy_lena_marco_security_1787396657268_013944 | completed | FAIL | FAIL | 140 |
| android.openbank.lena_marco_dispute_security_paperless_1787390266564_553878 | completed | FAIL | FAIL | 133 |
| android.openbank.maya_leo_security_dispute_payment_paperless_transfer_1787397914946_938252 | completed | FAIL | FAIL | 94 |
| android.opendriver.driver_workspace_support_ticket_final | completed | PASS | PASS | 94 |
| android.opendriver.rider_full_service_logout | completed | FAIL | PASS | 68 |
| android.opendriver.rider_three_scheduled_bay_rides_20260729 | completed | FAIL | FAIL | 180 |
| android.opendriver.seeded_driver_profile_document_arrival_5930_20260729 | completed | FAIL | FAIL | 180 |
| android.openfood.dumpling_biryani_coupon_merchant_clean_20260731 | completed | FAIL | FAIL | 180 |
| android.openfood.poke_sushi_wallet_merchant_clean_20260729 | completed | FAIL | FAIL | 78 |
| android.openfood.smokehouse_espresso_feast20_merchant_clean_20260801 | completed | FAIL | FAIL | 128 |
| android.openfood.smokehouse_pizza_merchant_ops_clean_20260729 | completed | FAIL | FAIL | 141 |
| android.opennavigation.meta_campus_transit_records_20260803 | completed | PASS | PASS | 91 |
| android.opennavigation.saved_routes_incidents_records_20260801 | completed | FAIL | FAIL | 180 |
| android.opennavigation.silicon_station_campus_records_20260803 | completed | PASS | PASS | 138 |
| android.opennote.city_food_469121 | completed | FAIL | FAIL | 180 |
| android.opennote.fashion_trip_970990 | completed | FAIL | FAIL | 180 |
| android.opennote.film_beauty_573866 | completed | FAIL | FAIL | 173 |
| android.opennote.fitness_mind_940880 | completed | FAIL | FAIL | 180 |
| android.opennote.gaming_home_461774 | completed | FAIL | FAIL | 90 |
| android.opennote.style_home_477136 | completed | FAIL | FAIL | 77 |
| android.openphoto.clown_dual_calibrated_export_20260804 | completed | FAIL | FAIL | 145 |
| android.openphoto.coastal_dual_calibrated_export_20260803 | completed | FAIL | FAIL | 180 |
| android.openphoto.cooking_dual_calibrated_export_20260804 | completed | FAIL | FAIL | 175 |
| android.openphoto.guitar_dual_calibrated_export_20260804 | completed | FAIL | FAIL | 148 |
| android.openshop.beauty_care_checkout_review_20260821 | completed | FAIL | FAIL | 100 |
| android.openshop.commute_summary_order_review | completed | FAIL | FAIL | 95 |
| android.openshop.family_weekend_checkout_20260821 | completed | FAIL | FAIL | 100 |
| android.openshop.garage_setup_checkout_backpack_review_20260821 | completed | FAIL | FAIL | 96 |
| android.openshop.gift_trip_bundle_checkout_document_review_20260821 | completed | FAIL | FAIL | 178 |
| android.openshop.home_refresh_2026_alipay_checkout | completed | FAIL | FAIL | 100 |
| android.opentrip.flight_voucher_baggage_booking | completed | PASS | PASS | 52 |
| android.opentrip.hotel_voucher_family_suite_booking | completed | FAIL | FAIL | 112 |
| android.opentrip.seed_hotel_review_wallet_audit | completed | PASS | PASS | 55 |
| android.opentrip.seed_orders_reschedule | completed | PASS | PASS | 64 |
| android.opentwitter.01_release_review_coordination | completed | FAIL | FAIL | 47 |
| android.opentwitter.03_research_search_coordination | completed | FAIL | FAIL | 22 |
| android.opentwitter.04_mobile_incident_frontend_audit | completed | FAIL | FAIL | 32 |
| android.opentwitter.05_security_billing_api_audit | completed | PASS | PASS | 121 |
| android.opentwitter.changelog_follow_audit_workflow_20260822 | completed | FAIL | FAIL | 100 |
| android.opentwitter.focus_research_community_workflow_20260822_v2 | completed | FAIL | FAIL | 96 |
