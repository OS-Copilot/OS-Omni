from evaluators.ios.openphotoedit_community_activity_cards_memory_482863 import (
    EXPORT_FILENAME,
    EXPECTED_SOURCE_SHA256,
    validate_export_files,
)


def test_exactly_named_window_sample_passes():
    result = validate_export_files([(EXPORT_FILENAME, EXPECTED_SOURCE_SHA256)])

    assert result["status"] == "PASS"
    assert all(check["passed"] for check in result["checks"])


def test_wrong_image_bytes_fail_even_with_correct_filename():
    result = validate_export_files([(EXPORT_FILENAME, "0" * 64)])

    assert result["status"] == "FAIL"
    assert "export.matches_source_sample" in result["failures"]


def test_prior_exports_do_not_contaminate_same_simulator_followup_tasks():
    result = validate_export_files(
        [
            (EXPORT_FILENAME, EXPECTED_SOURCE_SHA256),
            ("unexpected.png", "1" * 64),
        ]
    )

    assert result["status"] == "PASS"
