"""
Tests for import name normalisation and variant generation.
"""
from textwrap import dedent

import pytest

from nominatim.tokenizer.icu_rule_loader import ICURuleLoader
from nominatim.tokenizer.icu_name_processor import ICUNameProcessor, ICUNameProcessorRules

from nominatim.errors import UsageError

@pytest.fixture
def cfgfile(tmp_path, suffix='.yaml'):
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
        content += "variants:\n  - words:\n"
        content += '\n'.join(("      - " + s for s in variants)) + '\n'
        for k, v in kwargs:
            content += "    {}: {}\n".format(k, v)
        fpath = tmp_path / ('test_config' + suffix)
        fpath.write_text(dedent(content))
        return fpath

    return _create_config


def get_normalized_variants(proc, name):
    return proc.get_variants_ascii(proc.get_normalized(name))

def test_simple_variants(cfgfile):
    fpath = cfgfile('~strasse,~straße -> str',
                    '~weg => weg',
                    'prospekt -> pr')

    rules = ICUNameProcessorRules(loader=ICURuleLoader(fpath))
    proc = ICUNameProcessor(rules)

    assert set(get_normalized_variants(proc, "Bauwegstraße")) \
            == {'bauweg straße', 'bauweg str', 'bauwegstraße', 'bauwegstr'}
    assert get_normalized_variants(proc, "Bauwegstr") == ['bauwegstr']
    assert set(get_normalized_variants(proc, "holzweg")) \
            == {'holz weg', 'holzweg'}
    assert set(get_normalized_variants(proc, "Meier Weg")) \
            == {'meier weg', 'meierweg'}
    assert get_normalized_variants(proc, "hallo") == ['hallo']


def test_variants_empty(cfgfile):
    fpath = cfgfile('saint -> 🜵', 'street -> st')

    rules = ICUNameProcessorRules(loader=ICURuleLoader(fpath))
    proc = ICUNameProcessor(rules)

    assert get_normalized_variants(proc, '🜵') == []
    assert get_normalized_variants(proc, '🜳') == []
    assert get_normalized_variants(proc, 'saint') == ['saint']


def test_multiple_replacements(cfgfile):
    fpath = cfgfile('saint -> s,st', 'street -> st')

    rules = ICUNameProcessorRules(loader=ICURuleLoader(fpath))
    proc = ICUNameProcessor(rules)

    assert set(get_normalized_variants(proc, "Saint Johns Street")) == \
            {'saint johns street', 's johns street', 'st johns street',
             'saint johns st', 's johns st', 'st johns st'}


def test_search_normalized(cfgfile):
    fpath = cfgfile('~street => s,st', 'master => mstr')

    rules = ICUNameProcessorRules(loader=ICURuleLoader(fpath))
    proc = ICUNameProcessor(rules)

    assert proc.get_search_normalized('Master Street') == 'master street'
    assert proc.get_search_normalized('Earnes St') == 'earnes st'
    assert proc.get_search_normalized('Nostreet') == 'nostreet'
