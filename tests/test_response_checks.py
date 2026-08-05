from app.response_checks import WORD_COUNT_HARD_MAX, check_response

SIXTY_WORDS = " ".join(["słowo"] * 60) + "."


def test_complete_sentence_passes_every_check() -> None:
    checks = check_response(SIXTY_WORDS)

    assert checks.is_clean
    assert checks.failures == ()


def test_stop_reason_max_tokens_is_a_hard_fail_even_when_punctuation_looks_fine() -> None:
    # The whole point of capturing stop_reason: a response can end on a period and still have
    # been cut off, which the punctuation heuristic alone would wave through.
    checks = check_response(SIXTY_WORDS, stop_reason="max_tokens")

    assert checks.hit_token_ceiling is True
    assert checks.ends_mid_sentence is False
    assert checks.truncated is True
    assert checks.failures == ("truncated (max_tokens)",)


def test_end_turn_stop_reason_with_mid_word_ending_still_flags_via_heuristic() -> None:
    checks = check_response("Dziękujemy za opinię.\n\nZ po", stop_reason="end_turn")

    assert checks.hit_token_ceiling is False
    assert checks.truncated is True
    assert "truncated" in checks.failures


def test_word_count_over_hard_limit_fails_but_target_overshoot_does_not() -> None:
    tolerated = check_response(" ".join(["słowo"] * 125) + ".")
    hard_fail = check_response(" ".join(["słowo"] * (WORD_COUNT_HARD_MAX + 1)) + ".")

    # LOGIC.md §7: 121–130 is tolerated, >130 is a hard fail.
    assert tolerated.outside_word_target is True
    assert tolerated.over_hard_word_limit is False
    assert tolerated.failures == ()

    assert hard_fail.over_hard_word_limit is True
    assert hard_fail.failures == ("131 words",)


def test_response_ending_in_a_closing_quote_is_not_truncated() -> None:
    checks = check_response('Odniesiemy się do tego, co Państwo nazwali "chaosem".')

    assert checks.truncated is False


def test_truncated_mid_word_is_caught() -> None:
    # The two real v1.1 failures the PM had to find by eye: max_tokens cut them mid-word.
    assert check_response("Szanowni Państwo, dziękujemy za opinię.\n\nWła").truncated is True
    assert check_response("Dziękujemy za opinię i przepraszamy.\n\nZ po").truncated is True


def test_empty_response_counts_as_truncated() -> None:
    assert check_response("").truncated is True
    assert check_response("   ").truncated is True


def test_signature_variants_are_caught() -> None:
    for text in (
        "Dziękujemy za opinię.\n\nZ poważaniem,\nWłaściciel.",
        "Dziękujemy.\n\nPozdrawiam.",
        "Thank you for your feedback.\n\nKind regards,\nNamaste India.",
        "Thank you.\n\nBest Regards.",
    ):
        assert check_response(text).has_signature is True, text


def test_ordinary_response_has_no_signature() -> None:
    assert check_response(SIXTY_WORDS).has_signature is False


def test_denial_phrases_are_flagged_for_human_review() -> None:
    # The real v1.1 lead 50 wording, plus the English equivalent.
    pl = check_response("Zapewniam, że nasze dania są zawsze świeże. " + SIXTY_WORDS)
    en = check_response("I assure you that our kitchen follows every standard. " + SIXTY_WORDS)

    assert pl.has_denial is True
    assert en.has_denial is True
    # A denial is surfaced, not counted as a hard failure.
    assert pl.failures == ()
    assert pl.is_clean is False


def test_failures_lists_each_broken_rule() -> None:
    checks = check_response("Dziękujemy za opinię.\n\nZ poważaniem,\nWła")

    assert set(checks.failures) == {"truncated", "signature"}
    assert checks.is_clean is False
