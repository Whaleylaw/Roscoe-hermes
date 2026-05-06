"""Regression tests for built-in OpenRouter model aliases."""

import hermes_cli.model_switch as ms


def _reset_direct_alias_cache() -> None:
    # DIRECT_ALIASES is populated lazily; reset so tests exercise built-ins.
    ms.DIRECT_ALIASES = {}


def test_deepseek_v4_alias_resolves_to_openrouter_v4_pro():
    _reset_direct_alias_cache()

    result = ms.resolve_alias("deepseek-v4", "openrouter")

    assert result == ("openrouter", "deepseek/deepseek-v4-pro", "deepseek-v4")


def test_deepseek_v4_compact_alias_resolves_to_openrouter_v4_pro():
    _reset_direct_alias_cache()

    result = ms.resolve_alias("deepseekv4", "openrouter")

    assert result == ("openrouter", "deepseek/deepseek-v4-pro", "deepseekv4")


def test_kimi_k26_alias_resolves_to_openrouter_kimi_k26():
    _reset_direct_alias_cache()

    result = ms.resolve_alias("kimi-k2.6", "openrouter")

    assert result == ("openrouter", "moonshotai/kimi-k2.6", "kimi-k2.6")


def test_kimi_k26_short_alias_resolves_to_openrouter_kimi_k26():
    _reset_direct_alias_cache()

    result = ms.resolve_alias("k2.6", "openrouter")

    assert result == ("openrouter", "moonshotai/kimi-k2.6", "k2.6")
