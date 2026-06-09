"""Unit tests for the defensive LLM-output coercion (these shapes caused past bugs)."""
from app.llm import _to_str, _to_str_list


class TestToStr:
    def test_string_passthrough(self):
        assert _to_str("ciao") == "ciao"

    def test_dict_joins_values(self):
        assert _to_str({"a": "uno", "b": "due"}) == "uno due"

    def test_dict_skips_falsy_values(self):
        assert _to_str({"a": "uno", "b": "", "c": None}) == "uno"

    def test_list_joins_items(self):
        assert _to_str(["uno", "due"]) == "uno due"

    def test_number_becomes_str(self):
        assert _to_str(42) == "42"


class TestToStrList:
    def test_list_of_strings_passthrough(self):
        assert _to_str_list(["corso A", "corso B"]) == ["corso A", "corso B"]

    def test_list_of_dicts_prefers_nome(self):
        v = [{"nome": "Corso Python", "durata": "3 mesi"}]
        assert _to_str_list(v) == ["Corso Python"]

    def test_list_of_dicts_falls_back_to_name(self):
        assert _to_str_list([{"name": "Course"}]) == ["Course"]

    def test_dict_without_nome_or_name_joins_values(self):
        assert _to_str_list([{"titolo": "X", "ore": "10"}]) == ["X 10"]

    def test_plain_string_wrapped_in_list(self):
        assert _to_str_list("un solo suggerimento") == ["un solo suggerimento"]

    def test_none_yields_empty_list(self):
        assert _to_str_list(None) == []
