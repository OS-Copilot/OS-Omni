from scripts.author_eval_queue import next_attempt_index


def test_preserves_manual_history_when_queue_counter_is_stale(tmp_path):
    (tmp_path / "attempt_001").mkdir()
    (tmp_path / "attempt_002").mkdir()
    assert next_attempt_index(tmp_path, 0) == 3
    assert next_attempt_index(tmp_path, 7) == 8


def test_occupied_file_is_not_reused_and_unrelated_names_are_ignored(tmp_path):
    (tmp_path / "attempt_004").write_text("Historical occupied path")
    (tmp_path / "attempt_notes").mkdir()
    assert next_attempt_index(tmp_path, 0) == 5
