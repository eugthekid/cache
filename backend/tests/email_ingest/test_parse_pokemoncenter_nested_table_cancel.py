"""
Fixture is a REAL plaintext body (uid=287573, part of a batch of 18
Pokémon Center cancellation emails all dated Mon 07 Sep 2026 09:27:58),
captured live 2026-09-18 while investigating why a large batch of real
cancellations weren't showing up in Cache despite classify() correctly
recognizing every one of them as CANCELLED_FULL.

THE BUG THIS FIXTURE PROVES FIXED: this batch renders through a MORE
DEEPLY NESTED html->text table than the two cancellation fixtures
test_parse_pokemoncenter_tracking_and_cancel.py was built against (orders
P0038894998 / P0038918210). Two differences, both real:
  1. name and SKU rows carry leading whitespace before "|" instead of
     starting at column 0 (_NAME_ROW_RE used to anchor with a bare `^\\|`).
  2. SKU and Qty land on two separate physical lines instead of one (the
     shared regex required both on one line via `.search`).
Both silently produced parse_cancelled_lines() -> [], and because
ingest.py's PC CANCELLED_FULL branch has no per-line fallback (unlike its
SHIPPED branch, which does), that meant ZERO claims for the whole email --
order_number extracted fine and then wasted, no cancellation recorded at
all. Confirmed live: all 18 of this batch's emails failed the same way,
including one for a "30th Celebration Pokemon Center Elite Trainer Box"
line -- the exact product the user reported still showing as in-stock
despite being cancelled.

The fixture also carries the SAME rows re-rendered 2-4 more times at
shallower nesting, mangled together with no line break between a Qty and
the NEXT item's SKU (lines 8-10, 21-23, 34-54 below) -- the fix must
extract the three real lines from the first clean copy and silently
refuse the mangled duplicates, not attempt to parse them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_cancelled_lines

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}")
        print(f"        got:      {got!r}")
    if ok:
        passed += 1
    else:
        failed += 1


NESTED_CANCEL_BODY = """Order Summary |

                              | Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario) |

                              | SKU #: 10-10449-122
                                    Qty: 1 |

                        | SKU #: 10-10449-122
                                    Qty: 1 | SKU #: 10-10449-122
                                    Qty: 1 |

               |  |

            |  |  |

                              | Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box |

                              | SKU #: 10-10447-111
                                    Qty: 2 |

                        | SKU #: 10-10447-111
                                    Qty: 2 | SKU #: 10-10447-111
                                    Qty: 2 |

               |  |

            |  |  |

                              | Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |

                              | SKU #: 10-10449-121
                                    Qty: 1 |

                        | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 |

                  | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 |

            | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 |

      | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 | SKU #: 10-10449-121
                                    Qty: 1 |

                                |  | New Releases |

                          |  | New Releases | New Releases |

                    |  | New Releases | New Releases | New Releases |
"""

lines = parse_cancelled_lines(NESTED_CANCEL_BODY)
check("exactly 3 lines extracted, not the mangled duplicates", len(lines), 3)

by_sku = {l.external_sku: l for l in lines}
check("Elite Trainer Box line present", "10-10447-111" in by_sku, True)
if "10-10447-111" in by_sku:
    etb = by_sku["10-10447-111"]
    check("Elite Trainer Box name", etb.raw_product_text, "Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box")
    check("Elite Trainer Box quantity", etb.quantity, 2)

check("Tech Sticker (Lucario) quantity", by_sku.get("10-10449-122").quantity if "10-10449-122" in by_sku else None, 1)
check("Tech Sticker (Alolan Exeggutor) quantity -- first clean copy only, not summed with the mangled 2/3/4/5x duplicates", by_sku.get("10-10449-121").quantity if "10-10449-121" in by_sku else None, 1)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
