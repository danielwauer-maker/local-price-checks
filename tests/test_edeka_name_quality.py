from app.engine_v140.edeka_name_quality import choose_consensus_name, strict_name_ok


def test_rejects_real_ocr_garbage_seen_in_edeka_audit():
    bad = [
        "Classica Integral sta",
        "Himbeeren Er Pr",
        "THUNFISCH 99",
        "Straße 35, 56305 Pi Drokthler Haftung",
        "rASSO statt",
        "Bio-Avocados ie",
        "< der Woche",
        "Feaa Früchte creen",
    ]
    assert all(not strict_name_ok(value) for value in bad)


def test_keeps_clean_product_names():
    good = [
        "Himbeeren rot",
        "Hähnchenschenkel",
        "Delverde Classica Pasta",
        "Doppio Passo",
        "Storck Toffifee",
        "Original Wagner Steinofenpizza",
        "Mini-Pak-Choi",
        "Speisezwiebeln",
        "Brokkoli",
    ]
    assert all(strict_name_ok(value) for value in good)


def test_consensus_requires_two_independent_ocr_agreements():
    assert choose_consensus_name([
        "Delverde Classica Pasta",
        "DELVERDE Classica Pasta",
        "Classica Integral sta",
    ]) in {"Delverde Classica Pasta", "DELVERDE Classica Pasta"}
    assert choose_consensus_name(["Hähnchen Zwei", "Hähnchenschenkel"]) is None
    assert choose_consensus_name(["Storck Toffifee", "Storck Toffifee", "Toffifee"]) == "Storck Toffifee"
