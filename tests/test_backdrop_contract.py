"""Contract tests for the procedural backdrop (fatia A)."""

import unittest

from scripts.karaoke_styles.backdrop import BACKDROP_PALETTE, backdrop_for_color
from scripts.karaoke_styles.library import STYLE_DEFAULTS

_RANGES = {"hue": (-180.0, 180.0), "saturation": (-1.0, 1.0), "intensity": (-1.0, 1.0)}


class PaletteCoverageTests(unittest.TestCase):
    def test_every_colour_used_by_style_defaults_has_a_palette_entry(self):
        used = {v["color"] for v in STYLE_DEFAULTS.values()}
        self.assertEqual(5, len(used), f"eixo de cor mudou: {sorted(used)}")
        self.assertEqual(used, set(BACKDROP_PALETTE), "paleta divergiu de STYLE_DEFAULTS")

    def test_palette_has_no_orphan_entries(self):
        used = {v["color"] for v in STYLE_DEFAULTS.values()}
        self.assertEqual(set(), set(BACKDROP_PALETTE) - used)

    def test_every_style_resolves_to_a_backdrop(self):
        resolved = [backdrop_for_color(v["color"]) for v in STYLE_DEFAULTS.values()]
        self.assertEqual(len(STYLE_DEFAULTS), len(resolved))
        self.assertEqual(9, len(resolved), "denominador: 9 styles")

    def test_all_values_are_inside_the_filter_ranges(self):
        checked = 0
        for colour, params in BACKDROP_PALETTE.items():
            self.assertEqual({"hue", "saturation", "intensity"}, set(params), colour)
            for param, value in params.items():
                low, high = _RANGES[param]
                self.assertIsInstance(value, float, f"{colour}.{param}")
                self.assertGreaterEqual(value, low, f"{colour}.{param}")
                self.assertLessEqual(value, high, f"{colour}.{param}")
                checked += 1
        self.assertEqual(15, checked, "denominador: 5 cores x 3 params")

    def test_unknown_colour_falls_back_to_neutral(self):
        self.assertEqual(
            {"hue": 0.0, "saturation": 0.0, "intensity": 0.0},
            backdrop_for_color("nao-existe"),
        )


from scripts.karaoke_styles.backdrop import emit_backdrop_commands, _command


def _line(color, start):
    return {"color": color, "start": start, "text": "x", "end": start + 1.0}


class EmitCommandTests(unittest.TestCase):
    def test_emits_one_block_per_colour_change_plus_initial(self):
        lines = [_line("soft", 0.5), _line("soft", 2.0),
                 _line("intense", 4.0), _line("intense", 6.0),
                 _line("warm", 8.0)]
        out = emit_backdrop_commands(lines)
        blocks = [l for l in out.splitlines() if l.strip()]
        # 3 cores observadas (soft inicial, ->intense, ->warm) x 3 params
        self.assertEqual(9, len(blocks), f"esperado 3 blocos x 3 params, veio:\n{out}")

    def test_timestamps_are_monotonic_and_start_at_zero(self):
        lines = [_line("soft", 5.0), _line("warm", 9.0)]
        times = [float(l.split()[0])
                 for l in emit_backdrop_commands(lines).splitlines() if l.strip()]
        self.assertEqual(6, len(times), "denominador: 2 blocos x 3 params")
        self.assertEqual(0.0, times[0], "primeiro bloco tem de ancorar em t=0")
        self.assertEqual(sorted(times), times)

    def test_every_command_targets_only_the_whitelisted_filter_and_params(self):
        lines = [_line(c, i * 2.0) for i, c in enumerate(BACKDROP_PALETTE)]
        emitted = [l for l in emit_backdrop_commands(lines).splitlines() if l.strip()]
        self.assertEqual(15, len(emitted), "denominador: 5 cores x 3 params")
        for line in emitted:
            _t, target, param, _value = line.rstrip(";").split()
            self.assertEqual("huesaturation", target)
            self.assertIn(param, {"hue", "saturation", "intensity"})

    def test_hostile_section_label_cannot_escape_into_the_filtergraph(self):
        # Rotulo hostil vindo do caminho Whisper/LLM. So indexa a paleta.
        lines = [_line("chorus; drawtext=text=pwn", 0.0)]
        out = emit_backdrop_commands(lines)
        self.assertNotIn("drawtext", out)
        self.assertNotIn("pwn", out)
        emitted = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(3, len(emitted), "cai no neutro, ainda 3 params")

    def test_empty_lines_produce_empty_output(self):
        self.assertEqual("", emit_backdrop_commands([]))

    def test_out_of_range_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            emit_backdrop_commands([_line("soft", 0.0), _line("warm", -5.0)])

    def test_nan_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            emit_backdrop_commands([_line("soft", 0.0), _line("warm", float("nan"))])

    def test_infinity_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            emit_backdrop_commands([_line("soft", 0.0), _line("warm", float("inf"))])

    def test_param_outside_whitelist_raises_valueerror(self):
        with self.assertRaises(ValueError):
            _command(0.0, "evil_param", 0.5, 0.0)

    def test_value_outside_range_raises_valueerror(self):
        with self.assertRaises(ValueError):
            _command(0.0, "hue", 999.0, 0.0)
