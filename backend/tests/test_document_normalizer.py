from services.document_normalizer import normalize_text


def test_normalize_text_converts_fullwidth_alphanumerics_to_halfwidth():
    assert normalize_text("ＡＩ Ｖｉｓｉｂｉｌｉｔｙ １２３") == "AI Visibility 123"


def test_normalize_text_applies_nfkc_unicode_normalization():
    # Half-width katakana (a compatibility form) folds to the standard
    # full-width katakana under NFKC.
    assert normalize_text("ﾃｽﾄ") == "テスト"


def test_normalize_text_removes_invisible_characters():
    text = "AI​Visibility﻿ Platform"

    assert normalize_text(text) == "AIVisibility Platform"


def test_normalize_text_collapses_tabs_and_multiple_spaces():
    assert normalize_text("AI\t\tVisibility    Platform") == "AI Visibility Platform"


def test_normalize_text_collapses_three_or_more_blank_lines():
    assert normalize_text("line1\n\n\n\nline2") == "line1\n\nline2"


def test_normalize_text_keeps_japanese_text_intact():
    text = "OpenAIの料金プランについて教えてください。"

    assert normalize_text(text) == text


def test_normalize_text_preserves_single_space_between_japanese_words():
    # A single space carries meaning here and must not be removed.
    assert normalize_text("料金 プラン") == "料金 プラン"


def test_normalize_text_does_not_raise_on_empty_or_whitespace_only_input():
    assert normalize_text("") == ""
    assert normalize_text("   \n\t  ") == ""


def test_normalize_text_collapses_excessive_repeated_punctuation():
    assert normalize_text("すごい！！！！！！") == "すごい!!!"


def test_normalize_text_leaves_normal_punctuation_runs_untouched():
    # A 3-character ellipsis/emphasis run is meaningful, not noise.
    assert normalize_text("wait...") == "wait..."
    assert normalize_text("本当に！！！") == "本当に!!!"
