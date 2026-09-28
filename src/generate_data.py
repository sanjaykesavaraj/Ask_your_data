"""
STEP 1: Generate a realistic, DELIBERATELY MESSY raw dataset for a fictional
Indian D2C retail brand ("Sarvana Stores Online" -> brand name: SARVANA).

Why messy on purpose?
Recruiters repeatedly say the #1 gap in fresher portfolios is proof you can
handle real-world dirty data. So the raw files contain:
  - mixed-case / whitespace-padded city names  ("chennai", "CHENNAI ", "Chennai")
  - two different date formats in the same column (DD-MM-YYYY and YYYY-MM-DD)
  - currency stored as text with symbols/commas ("Rs.1,299.00", "₹1,299")
  - duplicate rows
  - missing customer_id / null emails
  - inconsistent status casing ("DELIVERED", "Delivered ", "delivered")
  - negative and zero quantities (data-entry errors)
  - orphan order_items pointing at non-existent orders

Run:  python src/generate_data.py
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
CITIES = {
    # city: (state, weight)
    "Chennai": ("Tamil Nadu", 0.170),
    "Bengaluru": ("Karnataka", 0.115),
    "Mumbai": ("Maharashtra", 0.105),
    "Delhi": ("Delhi", 0.095),
    "Hyderabad": ("Telangana", 0.085),
    "Coimbatore": ("Tamil Nadu", 0.070),
    "Pune": ("Maharashtra", 0.060),
    "Kolkata": ("West Bengal", 0.055),
    "Ahmedabad": ("Gujarat", 0.050),
    "Kochi": ("Kerala", 0.045),
    "Madurai": ("Tamil Nadu", 0.040),
    "Jaipur": ("Rajasthan", 0.040),
    "Lucknow": ("Uttar Pradesh", 0.035),
    "Chandigarh": ("Chandigarh", 0.035),
}
CITY_LIST = list(CITIES)
CITY_W = np.array([CITIES[c][1] for c in CITY_LIST])
CITY_W = CITY_W / CITY_W.sum()

CATEGORIES = {
    "Electronics": ["Mobile Phones", "Laptops", "Audio", "Accessories", "Smart Home"],
    "Fashion": ["Mens Wear", "Womens Wear", "Footwear", "Ethnic Wear", "Bags"],
    "Home & Kitchen": ["Cookware", "Furniture", "Appliances", "Decor", "Storage"],
    "Beauty": ["Skincare", "Haircare", "Makeup", "Fragrance", "Personal Care"],
    "Sports": ["Fitness", "Cycling", "Cricket", "Outdoor", "Yoga"],
    "Grocery": ["Staples", "Snacks", "Beverages", "Organic", "Dairy"],
}
CHANNELS = ["Website", "Mobile App", "Instagram", "Marketplace", "Offline Store"]
CHANNEL_W = np.array([0.30, 0.28, 0.14, 0.20, 0.08])
PAYMENTS = ["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery", "Wallet"]
PAY_W = np.array([0.42, 0.16, 0.13, 0.07, 0.15, 0.07])
REASONS = ["Damaged product", "Wrong size", "Late delivery", "Changed mind",
           "Quality issue", "Better price elsewhere"]
GENDERS = ["F", "M", "Other"]
GENDER_W = np.array([0.47, 0.50, 0.03])

FIRST = ["Aarav", "Priya", "Karthik", "Divya", "Rahul", "Ananya", "Vijay", "Meera",
         "Sanjay", "Lakshmi", "Arjun", "Nisha", "Rohit", "Kavya", "Aditya", "Sneha",
         "Manoj", "Deepika", "Suresh", "Pooja", "Imran", "Fatima", "Nikhil", "Ritu"]
LAST = ["Kumar", "Sharma", "Iyer", "Reddy", "Nair", "Rao", "Gupta", "Menon",
        "Joshi", "Pillai", "Das", "Verma", "Krishnan", "Patel", "Singh", "Chatterjee"]

START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2026-08-31")
N_CUSTOMERS, N_PRODUCTS, N_ORDERS = 6000, 420, 36000


def _messy_city(city: str) -> str:
    """Inject the classic dirty-city-name problem."""
    r = RNG.random()
    if r < 0.06:
        return city.lower()
    if r < 0.10:
        return city.upper()
    if r < 0.14:
        return f"  {city}  "
    if r < 0.155:
        return city.replace(" ", "") if " " in city else city + " "
    return city


def _messy_money(value: float) -> str:
    """Currency stored as text, with symbols and Indian-style commas."""
    r = RNG.random()
    s = f"{value:,.2f}"
    if r < 0.20:
        return f"Rs.{s}"
    if r < 0.30:
        return f"₹{s}"
    if r < 0.36:
        return f"INR {s}"
    if r < 0.40:
        return s.replace(",", "")
    return s


def _messy_date(ts: pd.Timestamp) -> str:
    """Two date formats in one column - the classic Excel export nightmare."""
    return ts.strftime("%d-%m-%Y") if RNG.random() < 0.28 else ts.strftime("%Y-%m-%d")


def _messy_status(s: str) -> str:
    r = RNG.random()
    if r < 0.10:
        return s.upper()
    if r < 0.16:
        return s.lower()
    if r < 0.19:
        return s + " "
    return s


# --------------------------------------------------------------------------
# 1. CUSTOMERS
# --------------------------------------------------------------------------
print("Generating customers ...")
signup_offsets = RNG.integers(0, (END - START).days + 1, N_CUSTOMERS)
customers = pd.DataFrame({
    "customer_id": [f"CUST{100000 + i}" for i in range(N_CUSTOMERS)],
    "customer_name": [f"{FIRST[RNG.integers(len(FIRST))]} {LAST[RNG.integers(len(LAST))]}"
                      for _ in range(N_CUSTOMERS)],
    "email": [f"user{100000 + i}@example.com" for i in range(N_CUSTOMERS)],
    "city": [_messy_city(c) for c in RNG.choice(CITY_LIST, N_CUSTOMERS, p=CITY_W)],
    "state": [CITIES[c][0] for c in RNG.choice(CITY_LIST, N_CUSTOMERS, p=CITY_W)],
    "signup_date": [START + pd.Timedelta(days=int(d)) for d in signup_offsets],
    "acquisition_channel": RNG.choice(CHANNELS, N_CUSTOMERS, p=CHANNEL_W),
    "gender": RNG.choice(GENDERS, N_CUSTOMERS, p=GENDER_W),
})
# Dirt: ~3% missing emails, ~2% missing city, 120 exact duplicate rows
customers.loc[customers.sample(frac=0.03, random_state=1).index, "email"] = np.nan
customers.loc[customers.sample(frac=0.02, random_state=2).index, "city"] = np.nan
customers = pd.concat([customers, customers.sample(120, random_state=3)], ignore_index=True)


# --------------------------------------------------------------------------
# 2. PRODUCTS
# --------------------------------------------------------------------------
print("Generating products ...")
rows = []
pid = 0
for cat, subs in CATEGORIES.items():
    for sub in subs:
        for _ in range(int(N_PRODUCTS / 30)):
            pid += 1
            cost = float(np.round(RNG.gamma(3.0, 320) + 80, 2))
            margin_mult = float(RNG.uniform(1.25, 2.4))
            rows.append({
                "product_id": f"PRD{5000 + pid}",
                "product_name": f"{sub} Product {pid:03d}",
                "category": cat,
                "subcategory": sub,
                "cost_price": cost,
                "mrp": float(np.round(cost * margin_mult, 2)),
            })
products = pd.DataFrame(rows)
# Dirt: 8 products with missing cost_price
products.loc[products.sample(8, random_state=4).index, "cost_price"] = np.nan


# --------------------------------------------------------------------------
# 3. ORDERS  (skewed so recent months grow + Nov/Dec festive spike)
# --------------------------------------------------------------------------
print("Generating orders ...")
all_days = pd.date_range(START, END, freq="D")
month_mult = np.array([1.0 + 0.025 * (i / 30.44) for i in range(len(all_days))])  # ~2.5%/month compounding
festive = np.where(all_days.month.isin([10, 11, 12]), 1.45, 1.0)
weekend = np.where(all_days.dayofweek >= 5, 1.18, 1.0)
w = month_mult * festive * weekend
w = w / w.sum()

order_days = RNG.choice(all_days, N_ORDERS, p=w)
order_days = pd.to_datetime(sorted(order_days))
status_pool = ["Delivered", "Delivered", "Delivered", "Delivered", "Delivered",
               "Delivered", "Delivered", "Returned", "Cancelled", "In Transit", "Pending"]
orders = pd.DataFrame({
    "order_id": [f"ORD{2000000 + i}" for i in range(N_ORDERS)],
    "customer_id": RNG.choice(customers["customer_id"].unique(), N_ORDERS),
    "order_date": order_days,
    "status": RNG.choice(status_pool, N_ORDERS),
    "payment_method": RNG.choice(PAYMENTS, N_ORDERS, p=PAY_W),
    "channel": RNG.choice(CHANNELS, N_ORDERS, p=CHANNEL_W),
})
# City follows the customer's (dirty) city so joins are consistent
cmap = customers.drop_duplicates("customer_id").set_index("customer_id")["city"]
orders["city"] = orders["customer_id"].map(cmap)
orders["state"] = orders["customer_id"].map(
    customers.drop_duplicates("customer_id").set_index("customer_id")["state"])

# Seasonality boost for specific categories (festive electronics, etc.)
orders["_month"] = orders["order_date"].dt.month
orders["_year"] = orders["order_date"].dt.year


# --------------------------------------------------------------------------
# 4. ORDER ITEMS
# --------------------------------------------------------------------------
print("Generating order items ...")
cat_list = list(CATEGORIES)
# base category popularity
cat_w = np.array([0.20, 0.24, 0.18, 0.16, 0.10, 0.12]); cat_w = cat_w / cat_w.sum()

items_per_order = RNG.choice([1, 1, 1, 2, 2, 3, 4], N_ORDERS)
order_ids = np.repeat(orders["order_id"].to_numpy(), items_per_order)

n_items = len(order_ids)
sel_cat = RNG.choice(cat_list, n_items, p=cat_w)
# festive boost: Electronics/Home & Kitchen over-index in Oct-Dec
festive_mask = orders.set_index("order_id").loc[order_ids, "_month"].isin([10, 11, 12]).to_numpy()
boost = RNG.random(n_items) < 0.18
sel_cat = np.where(festive_mask & boost,
                   RNG.choice(["Electronics", "Home & Kitchen", "Fashion"], n_items), sel_cat)

prod_by_cat = {c: products.loc[products.category == c, "product_id"].to_numpy() for c in cat_list}
sel_pid = np.array([prod_by_cat[c][RNG.integers(len(prod_by_cat[c]))] for c in sel_cat])

prod_meta = products.set_index("product_id")
mrp = prod_meta.loc[sel_pid, "mrp"].to_numpy()
cost = prod_meta.loc[sel_pid, "cost_price"].to_numpy()
qty = RNG.choice([1, 1, 1, 1, 2, 2, 3, 5], n_items)
disc_pct = RNG.choice([0, 0, 0.05, 0.10, 0.15, 0.20, 0.30], n_items,
                      p=[0.30, 0.22, 0.14, 0.14, 0.10, 0.07, 0.03])
unit_price = np.round(mrp * (1 - disc_pct), 2)

order_items = pd.DataFrame({
    "item_id": np.arange(1, n_items + 1),
    "order_id": order_ids,
    "product_id": sel_pid,
    "quantity": qty,
    "unit_price": unit_price,
    "discount_amount": np.round(mrp * disc_pct * qty, 2),
})

# Dirt: negative / zero quantities (data entry errors) on ~0.6% of rows
bad_idx = order_items.sample(frac=0.006, random_state=7).index
order_items.loc[bad_idx, "quantity"] = -1
order_items.loc[order_items.sample(frac=0.003, random_state=8).index, "quantity"] = 0
# Dirt: 40 orphan items pointing to non-existent orders
orphan = order_items.sample(40, random_state=9).copy()
orphan["order_id"] = ["ORD9999999"] * 40
orphan["item_id"] = np.arange(n_items + 1, n_items + 41)
order_items = pd.concat([order_items, orphan], ignore_index=True)
# Dirt: 200 exact duplicate rows
order_items = pd.concat([order_items, order_items.sample(200, random_state=10)], ignore_index=True)


# --------------------------------------------------------------------------
# 5. RETURNS
# --------------------------------------------------------------------------
print("Generating returns ...")
ret_orders = orders.loc[orders["status"] == "Returned", ["order_id", "order_date"]]
returns = pd.DataFrame({
    "return_id": [f"RET{300000 + i}" for i in range(len(ret_orders))],
    "order_id": ret_orders["order_id"].to_numpy(),
    "return_reason": RNG.choice(REASONS, len(ret_orders)),
})
returns["return_date"] = (
    pd.to_datetime(ret_orders["order_date"]).to_numpy()
    + pd.to_timedelta(RNG.integers(2, 21, len(ret_orders)), unit="D")
)
returns = returns[["return_id", "order_id", "return_date", "return_reason"]]
# Dirt: duplicate return rows
returns = pd.concat([returns, returns.sample(25, random_state=11)], ignore_index=True)


# --------------------------------------------------------------------------
# 6. MARKETING SPEND (monthly, per channel)
# --------------------------------------------------------------------------
print("Generating marketing spend ...")
months = pd.date_range(START, END, freq="MS")
spend_rows = []
base = {"Website": 180000, "Mobile App": 150000, "Instagram": 220000,
        "Marketplace": 130000, "Offline Store": 90000}
for m in months:
    growth = 1.0 + 0.022 * (m - START).days / 30.0
    fest = 1.35 if m.month in (10, 11, 12) else 1.0
    for ch, b in base.items():
        spend_rows.append({
            "month": m.strftime("%Y-%m"),
            "channel": ch,
            "spend": float(np.round(b * growth * fest * RNG.uniform(0.85, 1.15), 2)),
        })
marketing = pd.DataFrame(spend_rows)


# --------------------------------------------------------------------------
# WRITE RAW FILES (with the dirt baked in as text, like a real CSV export)
# --------------------------------------------------------------------------
print("Writing raw files ...")
cust_out = customers.copy()
cust_out["signup_date"] = cust_out["signup_date"].apply(_messy_date)
cust_out.to_csv(os.path.join(RAW_DIR, "customers.csv"), index=False)

prod_out = products.copy()
prod_out["cost_price"] = prod_out["cost_price"].apply(
    lambda v: "" if pd.isna(v) else _messy_money(v))
prod_out["mrp"] = prod_out["mrp"].apply(_messy_money)
prod_out.to_csv(os.path.join(RAW_DIR, "products.csv"), index=False)

ord_out = orders.drop(columns=["_month", "_year"]).copy()
ord_out["order_date"] = ord_out["order_date"].apply(_messy_date)
ord_out["status"] = ord_out["status"].apply(_messy_status)
ord_out.to_csv(os.path.join(RAW_DIR, "orders.csv"), index=False)

it_out = order_items.copy()
it_out["unit_price"] = it_out["unit_price"].apply(_messy_money)
it_out["discount_amount"] = it_out["discount_amount"].apply(_messy_money)
it_out.to_csv(os.path.join(RAW_DIR, "order_items.csv"), index=False)

ret_out = returns.copy()
ret_out["return_date"] = pd.to_datetime(ret_out["return_date"]).apply(_messy_date)
ret_out.to_csv(os.path.join(RAW_DIR, "returns.csv"), index=False)

marketing.to_csv(os.path.join(RAW_DIR, "marketing_spend.csv"), index=False)

for f in sorted(os.listdir(RAW_DIR)):
    n = sum(1 for _ in open(os.path.join(RAW_DIR, f))) - 1
    print(f"  {f:<24} {n:>8,} rows")
print(f"\nRaw files written to {os.path.abspath(RAW_DIR)}")
