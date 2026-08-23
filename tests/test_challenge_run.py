from friction.challenges import run as R
from friction.schedule import Item


def test_tier_granularity_label_names_the_tier_not_one_site(config):
    """Tier 1 unlocks as a whole, so naming a single site would be a lie."""
    item = Item("tier1", "site", "chess.com", "tier1")
    label = R.label_for(item, config)
    assert "chess.com" not in label and "2 items" in label


def test_item_granularity_label_names_the_site(config):
    item = Item("tier2", "site", "reddit.com", "tier2:reddit.com")
    assert R.label_for(item, config) == "reddit.com"
