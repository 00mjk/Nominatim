"""
Tests for import name normalisation and variant generation.
"""
from textwrap import dedent

import pytest

from nominatim.tokenizer.icu_rule_loader import ICURuleLoader

from nominatim.errors import UsageError

@pytest.fixture
def cfgfile(def_config, tmp_path):
    project_dir = tmp_path / 'project_dir'
    project_dir.mkdir()
    def_config.project_dir = project_dir

    def _create_config(*variants, **kwargs):
        content = dedent("""\
        normalization:
            - ":: NFD ()"
            - "'🜳' > ' '"
            - "[[:Nonspacing Mark:] [:Cf:]] >"
            - ":: lower ()"
            - "[[:Punctuation:][:Space:]]+ > ' '"
            - ":: NFC ()"
        transliteration:
            - "::  Latin ()"
            - "'🜵' > ' '"
        """)
        content += "token-analysis:\n  - analyzer: generic\n    variants:\n      - words:\n"
        content += '\n'.join(("          - " + s for s in variants)) + '\n'
        for k, v in kwargs:
            content += "        {}: {}\n".format(k, v)
        (project_dir / 'icu_tokenizer.yaml').write_text(content)

        return def_config

    return _create_config


def get_normalized_variants(proc, name):
    return proc.get_variants_ascii(proc.get_normalized(name))


def test_variants_empty(cfgfile):
    config = cfgfile('saint -> 🜵', 'street -> st')

    proc = ICURuleLoader(config).make_token_analysis()

    assert get_normalized_variants(proc, '🜵') == []
    assert get_normalized_variants(proc, '🜳') == []
    assert get_normalized_variants(proc, 'saint') == ['saint']


VARIANT_TESTS = [
(('~strasse,~straße -> str', '~weg => weg'), "hallo", {'hallo'}),
(('weg => wg',), "holzweg", {'holzweg'}),
(('weg -> wg',), "holzweg", {'holzweg'}),
(('~weg => weg',), "holzweg", {'holz weg', 'holzweg'}),
(('~weg -> weg',), "holzweg",  {'holz weg', 'holzweg'}),
(('~weg => w',), "holzweg", {'holz w', 'holzw'}),
(('~weg -> w',), "holzweg",  {'holz weg', 'holzweg', 'holz w', 'holzw'}),
(('~weg => weg',), "Meier Weg", {'meier weg', 'meierweg'}),
(('~weg -> weg',), "Meier Weg", {'meier weg', 'meierweg'}),
(('~weg => w',), "Meier Weg", {'meier w', 'meierw'}),
(('~weg -> w',), "Meier Weg", {'meier weg', 'meierweg', 'meier w', 'meierw'}),
(('weg => wg',), "Meier Weg", {'meier wg'}),
(('weg -> wg',), "Meier Weg", {'meier weg', 'meier wg'}),
(('~strasse,~straße -> str', '~weg => weg'), "Bauwegstraße",
     {'bauweg straße', 'bauweg str', 'bauwegstraße', 'bauwegstr'}),
(('am => a', 'bach => b'), "am bach", {'a b'}),
(('am => a', '~bach => b'), "am bach", {'a b'}),
(('am -> a', '~bach -> b'), "am bach", {'am bach', 'a bach', 'am b', 'a b'}),
(('am -> a', '~bach -> b'), "ambach", {'ambach', 'am bach', 'amb', 'am b'}),
(('saint -> s,st', 'street -> st'), "Saint Johns Street",
     {'saint johns street', 's johns street', 'st johns street',
      'saint johns st', 's johns st', 'st johns st'}),
(('river$ -> r',), "River Bend Road", {'river bend road'}),
(('river$ -> r',), "Bent River", {'bent river', 'bent r'}),
(('^north => n',), "North 2nd Street", {'n 2nd street'}),
(('^north => n',), "Airport North", {'airport north'}),
(('am -> a',), "am am am am am am am am", {'am am am am am am am am'}),
(('am => a',), "am am am am am am am am", {'a a a a a a a a'})
]

@pytest.mark.parametrize("rules,name,variants", VARIANT_TESTS)
def test_variants(cfgfile, rules, name, variants):
    config = cfgfile(*rules)
    proc = ICURuleLoader(config).make_token_analysis()

    result = get_normalized_variants(proc, name)

    assert len(result) == len(set(result))
    assert set(get_normalized_variants(proc, name)) == variants


def test_search_normalized(cfgfile):
    config = cfgfile('~street => s,st', 'master => mstr')
    proc = ICURuleLoader(config).make_token_analysis()

    assert proc.get_search_normalized('Master Street') == 'master street'
    assert proc.get_search_normalized('Earnes St') == 'earnes st'
    assert proc.get_search_normalized('Nostreet') == 'nostreet'
