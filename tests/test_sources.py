"""Unit tests for the Flow-1 extractor adapter (pure functions, no DB/model/network)."""
from app.sources import _as_skill_list, profile_from_extracted


class TestAsSkillList:
    def test_list_of_strings_is_lowercased(self):
        assert _as_skill_list(["Python", "Java"]) == ["python", "java"]

    def test_list_of_dicts_uses_first_available_key(self):
        v = [{"name": "Python"}, {"label": "SQL"}, {"skill": "Docker"},
             {"nome": "Git"}, {"descrizione": "Linux"}]
        assert _as_skill_list(v) == ["python", "sql", "docker", "git", "linux"]

    def test_dict_without_known_key_is_dropped(self):
        assert _as_skill_list([{"durata": "3 mesi"}]) == []

    def test_string_is_split_on_newlines_and_semicolons(self):
        assert _as_skill_list("Python; Java\nSQL") == ["python", "java", "sql"]

    def test_bullet_and_number_markers_are_stripped(self):
        assert _as_skill_list(["- Python", "1. Java", "• SQL"]) == ["python", "java", "sql"]

    def test_markdown_emphasis_is_stripped(self):
        assert _as_skill_list(["**Python**", "`SQL`", "## Docker"]) == ["python", "sql", "docker"]

    def test_empty_and_whitespace_are_filtered(self):
        assert _as_skill_list(["", "   ", "Python"]) == ["python"]

    def test_unknown_type_returns_empty(self):
        assert _as_skill_list(None) == []
        assert _as_skill_list(42) == []


class TestProfileFromExtracted:
    def test_combines_tecniche_and_soft(self):
        data = {"competenze_tecniche": ["Python"], "competenze_soft": ["Teamwork"]}
        assert profile_from_extracted(data).skills == ["python", "teamwork"]

    def test_unwraps_nested_data_key(self):
        data = {"data": {"competenze_tecniche": ["Python"]}}
        assert profile_from_extracted(data).skills == ["python"]

    def test_role_is_read_from_role_keys(self):
        data = {"competenze_tecniche": ["Python"], "ruolo": "Sviluppatore"}
        assert profile_from_extracted(data).role == "Sviluppatore"

    def test_case_insensitive_dedup(self):
        # "Python" and "python" collapse to one after lowercasing.
        data = {"competenze_tecniche": ["Python", "python", "PYTHON"]}
        assert profile_from_extracted(data).skills == ["python"]

    def test_no_skill_keys_yields_empty(self):
        assert profile_from_extracted({"foo": "bar"}).skills == []
