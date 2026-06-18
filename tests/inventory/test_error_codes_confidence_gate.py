"""CI gate: S2P2_EVENT_TYPES is DERIVED from the authoritative app catalog
[apk:g2408-plugin-ext1423], not hand-curated. This gate guards the derivation
integrity: every mapped code must be a catalog code (slug == event_slug) or an
explicit wire supplement, so apk/vacuum-lineage names can't creep back in."""
from custom_components.dreame_a2_mower.mower import fault_catalog as fc
from custom_components.dreame_a2_mower.mower.error_codes import (
    _SLUG_SUPPLEMENT,
    S2P2_EVENT_TYPES,
)


def test_every_mapped_code_is_catalog_or_supplement():
    catalog = fc.known_codes("iot")
    for code, slug in S2P2_EVENT_TYPES.items():
        if code in _SLUG_SUPPLEMENT:
            assert slug == _SLUG_SUPPLEMENT[code]
            assert code not in catalog, (
                f"code {code} is now in the catalog — drop it from _SLUG_SUPPLEMENT"
            )
        else:
            assert code in catalog, f"mapped code {code} not in catalog and not supplemented"
            assert slug == fc.event_slug(code), (
                f"slug for {code} ({slug!r}) != event_slug ({fc.event_slug(code)!r})"
            )


def test_every_catalog_code_is_mapped():
    for code in fc.known_codes("iot"):
        assert code in S2P2_EVENT_TYPES, f"catalog code {code} missing a slug"
