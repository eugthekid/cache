"""
Product families (variants): suggestions, grouping, the one-row-per-family
list, the family screen's per-version numbers, moving units out of a random
version once you know what they were, and the product's type / category /
variant-kind fields.

Built around the real case: the 30th Celebration tech stickers come as
[Lucario] and [Alolan Exeggutor] from Pokemon Center and as a random
"(Lucario or Alolan Exeggutor)- Styles May Vary" from Target.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, families, models
from app.database import Base, get_db
from app.main import app

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


# --- the pure naming helpers --------------------------------------------------
LUCARIO = "Pokémon TCG: 30th Celebration Tech Sticker Collection [Lucario]"
EXEGGUTOR = "Pokémon TCG: 30th Celebration Tech Sticker Collection [Alolan Exeggutor]"
RANDOM = "Pokémon Trading Card Game: 30th Celebration Tech Sticker Collection (Lucario or Alolan Exeggutor)- Styles May Vary"
BASE = "Pokémon TCG: 30th Celebration Tech Sticker Collection"
check("family base: bracket version", families.family_base(LUCARIO), BASE)
check("family base: random version, long prefix", families.family_base(RANDOM), BASE)
check("a plain product is its own base", families.family_base("Pokémon TCG: Pitch Black Booster Display Box"), "Pokémon TCG: Pitch Black Booster Display Box")
check("guess: bracket is specific", families.guess_kind(LUCARIO), "specific")
check("guess: 'or' and 'Styles May Vary' is random", families.guess_kind(RANDOM), "random")
check("label: specific", families.variant_label(LUCARIO, "specific"), "Lucario")
check("label: random", families.variant_label(RANDOM, "random"), "Random · Lucario or Alolan Exeggutor")
GAS = "Pokémon TCG: Mega Evolution—Ascended Heroes Tech Sticker Collection - Gastly"
pg = families.parse_product(GAS, "ME: Ascended Heroes")
check("parse: series / set / line / variant", (pg["series"], pg["set"], pg["line"], pg["variant"], pg["kind"]), ("Mega Evolution", "Ascended Heroes", "Tech Sticker Collection", "Gastly", "specific"))
check("parse: hyphen suffix is a version", families.family_base(GAS), "Pokémon TCG: Mega Evolution—Ascended Heroes Tech Sticker Collection")
check("parse: (Series 2) is not a version", families.parse_product("Foo Collection (Series 2)")["variant"], None)
check("parse: exclusive is not a version", families.parse_product("Elite Trainer Box - Pokémon Center Exclusive")["variant"], None)
check("parse: (3 Pack) is not a version", families.parse_product("Blister (3 Pack)")["variant"], None)
check("random options", families.random_options("Random · Lucario or Alolan Exeggutor"), ["Lucario", "Alolan Exeggutor"])

# --- a throwaway database behind the real routes ------------------------------
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def override():
    db = Session()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override
db = Session()
user = crud.get_or_create_default_user(db)


def product(name, key, category="Pokémon TCG"):
    p = models.Product(user_id=user.id, canonical_name=name, normalized_key=key, category=category)
    db.add(p)
    db.commit()
    return p


def stock(p, retailer, n, status, price, sold_price=None):
    o = models.Order(user_id=user.id, source_id="s", external_id=f"{p.id}{retailer}{status}{price}", status="success",
                     site="x", retailer=retailer, quantity=n, unit_price=price, product_id=p.id, shipping_status="delivered",
                     order_number=f"{retailer}-{p.id[:4]}-{status}")
    db.add(o)
    db.commit()
    for k in range(n):
        db.add(models.InventoryItem(user_id=user.id, order_id=o.id, unit_index=k + 1, status=status, cost_basis=price,
                                    sold_price=sold_price, sold_at=None if not sold_price else models.datetime(2026, 10, 1)))
    db.commit()


p_luc = product(LUCARIO, "luc")
p_exe = product(EXEGGUTOR, "exe")
p_rnd = product(RANDOM, "rnd")
p_etb = product("Pokémon TCG: Pitch Black Elite Trainer Box", "etb")
p_s2 = product("Pokémon TCG: First Partner Illustration Collection (Series 2)", "fp2")
p_s3 = product("Pokémon TCG: First Partner Illustration Collection (Series 3)", "fp3")
stock(p_luc, "Pokémon Center", 6, "in_hand", 16.0)
stock(p_exe, "Pokémon Center", 4, "in_hand", 16.0)
stock(p_rnd, "Target", 10, "in_hand", 22.0)
stock(p_rnd, "Target", 5, "sold", 22.0, sold_price=40.0)
stock(p_etb, "Target", 3, "in_hand", 76.0)
stock(p_s2, "Target", 2, "in_hand", 20.0)
stock(p_s3, "Target", 3, "in_hand", 20.0)

client = TestClient(app)

# --- automatic grouping --------------------------------------------------------
# Nothing was grouped by hand: reading the list groups what belongs together.
rows = client.get("/products/grouped").json()
fam_rows = [r for r in rows if r["family_id"]]
check("the three sticker versions grouped themselves into one family", [r["variant_count"] for r in fam_rows], [3])
fid = fam_rows[0]["family_id"]
check("the family is named after the product, version removed", fam_rows[0]["name"], BASE)
check("different series are NOT grouped, nor plain products", sorted(r["name"] for r in rows if not r["family_id"]), sorted([
    "Pokémon TCG: Pitch Black Elite Trainer Box",
    "Pokémon TCG: First Partner Illustration Collection (Series 2)",
    "Pokémon TCG: First Partner Illustration Collection (Series 3)"]))
check("reading again changes nothing", client.get("/products/grouped").json() == rows, True)
check("one-member family refused", client.post("/families", json={"name": "x", "members": [{"product_id": p_etb.id, "variant_kind": "specific"}]}).status_code, 422)
check("a product can't join two families", client.post("/families", json={"name": "y", "members": [
    {"product_id": p_luc.id, "variant_kind": "specific"}, {"product_id": p_etb.id, "variant_kind": "specific"}]}).status_code, 422)

# a new version that turns up later joins the family by itself
p_new = product("Pokémon TCG: 30th Celebration Tech Sticker Collection (Mew)", "mew")
stock(p_new, "Target", 2, "in_hand", 18.0)
rows = client.get("/products/grouped").json()
check("a new version joins the existing family", [r["variant_count"] for r in rows if r["family_id"] == fid], [4])
db.expire_all()
check("and is marked specific", db.get(models.Product, p_new.id).variant_kind, "specific")
client.delete(f"/families/{fid}/members/{p_new.id}")
check("a version taken out stays out", [r["variant_count"] for r in client.get("/products/grouped").json() if r["family_id"] == fid], [3])

# --- hyphen-suffix versions (Ascended Heroes) -----------------------------------
g1 = product("Pokémon TCG: Mega Evolution—Ascended Heroes Tech Sticker Collection - Gastly", "gas")
g2 = product("Pokémon TCG: Mega Evolution—Ascended Heroes Tech Sticker Collection - Charmander", "cha")
stock(g1, "Target", 4, "in_hand", 10.0)
stock(g2, "Target", 2, "in_hand", 10.0)
rows = client.get("/products/grouped").json()
asc = [r for r in rows if r["family_id"] and r["family_id"] != fid]
check("hyphen-suffix versions group", [(r["variant_count"], r["total_units"]) for r in asc], [(2, 6)])
asc_id = asc[0]["family_id"]
client.delete(f"/families/{asc_id}")
check("an ungrouped family is not regrouped", [r["family_id"] for r in client.get("/products/grouped").json() if r["family_id"] != fid and r["family_id"]], [])

# --- the list: one row per family ------------------------------------------------
rows = client.get("/products/grouped").json()
fam_rows = [r for r in rows if r["family_id"] == fid]
check("exactly one list row for the family", len(fam_rows), 1)
fr = fam_rows[0]
check("family row: name, no product id, 3 versions", (fr["name"], fr["product_id"], fr["variant_count"]), (BASE, None, 3))
check("family row: units add up across versions", (fr["total_units"], fr["in_hand"], fr["sold"]), (25, 20, 5))
check("family row lists its member products", sorted(fr["member_product_ids"]), sorted([p_luc.id, p_exe.id, p_rnd.id]))
check("the versions don't also appear as their own rows", {r["name"] for r in rows if r["family_id"] is None} & {LUCARIO, EXEGGUTOR, RANDOM}, set())
check("other products are untouched", any(r["product_id"] == p_etb.id and r["total_units"] == 3 for r in rows), True)

# --- the family screen ------------------------------------------------------------
dash = client.get(f"/families/{fid}/dashboard").json()
check("family totals", (dash["total_units"], dash["in_hand"], dash["sold"]), (25, 20, 5))
v = {x["label"]: x for x in dash["variants"]}
check("each version has its own counts", {k: (x["units"], x["in_hand"], x["sold"]) for k, x in v.items()},
      {"Random · Lucario or Alolan Exeggutor": (15, 10, 5), "Lucario": (6, 6, 0), "Alolan Exeggutor": (4, 4, 0)})
check("each version has its own average cost", {k: round(x["avg_cost"], 2) for k, x in v.items()}, {"Random · Lucario or Alolan Exeggutor": 22.0, "Lucario": 16.0, "Alolan Exeggutor": 16.0})
check("sold version shows profit and sale price", (v["Random · Lucario or Alolan Exeggutor"]["avg_sale_price"], v["Random · Lucario or Alolan Exeggutor"]["profit"]), (40.0, 90.0))
check("retailers roll up across versions", {r["retailer"]: r["units"] for r in dash["retailers"]}, {"Target": 15, "Pokémon Center": 10})
check("a random variant lists the variants it could be", sorted(v["Random · Lucario or Alolan Exeggutor"]["option_product_ids"]), sorted([p_luc.id, p_exe.id]))
check("a specific variant lists none", v["Lucario"]["option_product_ids"], [])
check("ungrouped products are offered for adding", p_etb.id in {x["product_id"] for x in dash["ungrouped_products"]}, True)

pdash = client.get(f"/products/{p_rnd.id}/dashboard").json()
check("a version's own screen knows its family and siblings", (pdash["family"]["name"], pdash["variant_kind"], sorted(s["label"] for s in pdash["siblings"])),
      (BASE, "random", ["Alolan Exeggutor", "Lucario", "Random · Lucario or Alolan Exeggutor"]))

# --- opening random units: move them to the specific version -----------------------
res = client.post(f"/products/{p_rnd.id}/resolve", json={"to_product_id": p_luc.id, "quantity": 4})
check("move 4 random units to Lucario", res.status_code, 200)
dash = client.get(f"/families/{fid}/dashboard").json()
v = {x["label"]: x for x in dash["variants"]}
check("Lucario gained 4, random lost 4", (v["Lucario"]["units"], v["Random · Lucario or Alolan Exeggutor"]["units"]), (10, 11))
check("the family total is unchanged", dash["total_units"], 25)
check("moved units keep their own cost, so Lucario's average reflects them", round(v["Lucario"]["avg_cost"], 2), round((6 * 16 + 4 * 22) / 10, 2))
check("units can't be moved to another family's product", client.post(f"/products/{p_rnd.id}/resolve", json={"to_product_id": p_etb.id, "quantity": 1}).status_code, 422)
check("can't move more than the unsold units", client.post(f"/products/{p_rnd.id}/resolve", json={"to_product_id": p_luc.id, "quantity": 99}).status_code, 422)
check("sold units are never moved", client.post(f"/products/{p_rnd.id}/resolve", json={"to_product_id": p_luc.id, "quantity": 7}).status_code, 422)

# moving works in either direction, so a wrong guess can be corrected
res = client.post(f"/products/{p_luc.id}/resolve", json={"to_product_id": p_rnd.id, "quantity": 2})
check("move 2 back from Lucario to the random version", res.status_code, 200)
dash = client.get(f"/families/{fid}/dashboard").json()
v = {x["label"]: x for x in dash["variants"]}
check("counts follow, family total unchanged", ({k: x["units"] for k, x in v.items()}, dash["total_units"]),
      ({"Random · Lucario or Alolan Exeggutor": 13, "Lucario": 8, "Alolan Exeggutor": 4}, 25))

# --- type, category, kind ------------------------------------------------------------
check("set a product's type", client.patch(f"/products/{p_etb.id}", json={"product_type": "Elite Trainer Box"}).json()["product_type"], "Elite Trainer Box")
check("set variant kind", client.patch(f"/products/{p_etb.id}", json={"variant_kind": "random"}).json()["variant_kind"], "random")
check("an empty string clears it (back to standard)", client.patch(f"/products/{p_etb.id}", json={"variant_kind": ""}).json()["variant_kind"], None)
check("a bad variant kind is refused", client.patch(f"/products/{p_etb.id}", json={"variant_kind": "bogus"}).status_code, 422)
check("setting one field leaves the others alone", client.patch(f"/products/{p_etb.id}", json={"category": "One Piece"}).json()["product_type"], "Elite Trainer Box")

res = client.patch(f"/families/{fid}", json={"product_type": "Sticker Collection", "category": "Pokémon TCG"}).json()
db.expire_all()
check("family type applies to every version", (res["product_type"], {p.product_type for p in db.query(models.Product).filter_by(family_id=fid)}), ("Sticker Collection", {"Sticker Collection"}))
check("renaming the family", client.patch(f"/families/{fid}", json={"name": "30th Tech Stickers"}).json()["name"], "30th Tech Stickers")

# --- membership ------------------------------------------------------------------------
check("add a version", client.post(f"/families/{fid}/members", json={"product_id": p_etb.id, "variant_kind": "specific"}).status_code, 200)
check("remove it again", client.delete(f"/families/{fid}/members/{p_etb.id}").json(), {"dissolved": False})
client.delete(f"/families/{fid}/members/{p_exe.id}")
res = client.delete(f"/families/{fid}/members/{p_luc.id}").json()
check("removing down to one version dissolves the family", res, {"dissolved": True})
db.expire_all()
check("and the leftover product is a plain product again", (db.get(models.Product, p_rnd.id).family_id, db.get(models.Product, p_rnd.id).variant_kind), (None, None))

# --- ungroup leaves everything in place -----------------------------------------------------
fid2 = client.post("/families", json={"name": BASE, "members": [
    {"product_id": p_luc.id, "variant_kind": "specific"}, {"product_id": p_exe.id, "variant_kind": "specific"}]}).json()["family_id"]
before = db.query(models.InventoryItem).count()
check("ungroup", client.delete(f"/families/{fid2}").json(), {"ungrouped": True})
db.expire_all()
check("ungrouping removes the family but not a single unit", (db.query(models.ProductFamily).count(), db.query(models.InventoryItem).count()), (0, before))
check("the list shows the products individually again", len([r for r in client.get("/products/grouped").json() if r["family_id"]]), 0)

# --- a variant you only bought once, and a random product with no siblings -------------
TIN = "Pokémon TCG: 30th Celebration Tin - Sylveon or Greninja"
p_tin = product(TIN, "tin")
stock(p_tin, "Target", 6, "in_hand", 30.0)
p_one = product("Pokémon TCG: Ascended Heroes Premium Poster Collection - Mega Gardevoir", "gard")
stock(p_one, "Target", 4, "in_hand", 56.0)
client.get("/products/grouped")
db.expire_all()
check("a lone random product is marked random from its name", db.get(models.Product, p_tin.id).variant_kind, "random")
check("a lone variant is marked specific", db.get(models.Product, p_one.id).variant_kind, "specific")
check("and none of that makes a family", (db.get(models.Product, p_tin.id).family_id, db.get(models.Product, p_one.id).family_id), (None, None))
hint = client.get(f"/products/{p_tin.id}/dashboard").json()["variant_hint"]
check("a random product lists the variants it could be", [o["label"] for o in hint["others"]], ["Sylveon", "Greninja"])
check("choosing Standard sticks (not re-marked)", client.patch(f"/products/{p_one.id}", json={"variant_kind": ""}).json()["variant_kind"], None)
client.get("/products/grouped")
db.expire_all()
check("automatic marking respects that choice", db.get(models.Product, p_one.id).variant_kind, None)

res = client.post(f"/products/{p_tin.id}/resolve", json={"to_variant": "Sylveon", "quantity": 2})
check("opening tins as a variant with no product yet works", res.status_code, 200)
db.expire_all()
sylveon = db.query(models.Product).filter_by(canonical_name="Pokémon TCG: 30th Celebration Tin - Sylveon").one()
check("the new variant's product is specific and shares a family with the random one", (sylveon.variant_kind, sylveon.family_id is not None and sylveon.family_id == db.get(models.Product, p_tin.id).family_id), ("specific", True))
check("two units moved", (len(client.get(f"/products/{sylveon.id}/dashboard").json()["retailers"]) , client.get(f"/products/{sylveon.id}/dashboard").json()["total_units"]), (1, 2))
check("the random product has four left", client.get(f"/products/{p_tin.id}/dashboard").json()["total_units"], 4)
check("a variant the name doesn't list is refused", client.post(f"/products/{p_tin.id}/resolve", json={"to_variant": "Pikachu", "quantity": 1}).status_code, 422)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
