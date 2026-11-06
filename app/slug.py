"""Адрес категории (slug) из названия: русские буквы -> латиница, только a-z, 0-9 и _."""
import re

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґ", ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "i", "yi", "ye", "g"]))


def slugify(name: str) -> str:
    s = "".join(_TR.get(ch, ch) for ch in name.lower())
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "category")[:48]
