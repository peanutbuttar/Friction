from friction.challenges import run as R
from friction.schedule import Item


def test_whole_tier_label_names_the_tier_not_one_site(config):
    """Opening the whole tier must not be described as opening one site."""
    item = Item("tier1", "site", "chess.com", ("chess.com",),
                "tier1:chess.com", "tier1")
    label = R.label_for(item, config, whole_tier=True)
    assert "chess.com" not in label and "2 items" in label


def test_single_item_label_names_the_site(config):
    item = Item("tier2", "site", "reddit.com", ("reddit.com",),
                "tier2:reddit.com", "tier2")
    assert R.label_for(item, config) == "reddit.com"
