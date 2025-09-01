import streamlit as st
import pandas as pd
import json, re, difflib, math
from datetime import date, datetime
from pathlib import Path

st.set_page_config(page_title="Smart Chef v11", page_icon="🍳", layout="wide")
BASE = Path(__file__).resolve().parent
DATA_BASE = BASE / "data"
PROFILES_PATH = BASE / "profiles.json"

def load_profiles():
    if PROFILES_PATH.exists(): return json.loads(PROFILES_PATH.read_text())
    return {"active":"Home","all":["Home"]}
def save_profiles(p): PROFILES_PATH.write_text(json.dumps(p, indent=2))
def ensure_profile_dirs(profile):
    d = DATA_BASE / profile
    d.mkdir(parents=True, exist_ok=True)
    for fname in ["inventory.csv","recipes.csv","ratings.csv","prefs.json","ads.csv","shopping_list.csv","goals.json","cooked_log.csv"]:
        (d / fname).touch(exist_ok=True)
    if not (d / "prefs.json").read_text().strip():
        (d / "prefs.json").write_text(json.dumps({
            "diet":{"gluten_free":False,"vegetarian":False,"vegan":False,"dairy_free":False},
            "allergens":{"peanuts":False,"tree_nuts":False,"soy":False,"dairy":False,"eggs":False,"fish":False,"shellfish":False,"sesame":False,"wheat":False}
        }, indent=2))
    if not (d / "goals.json").read_text().strip():
        (d / "goals.json").write_text(json.dumps({"daily_calorie_target":2000,"carb_pref":"balanced","adventurous":6,"dislikes":""}, indent=2))
    return d
def p_path(profile, name): return ensure_profile_dirs(profile) / name

@st.cache_data
def load_csv(path, parse_dates=None):
    if not path.exists() or path.stat().st_size==0: return pd.DataFrame()
    return pd.read_csv(path, parse_dates=parse_dates or [])
def save_csv(df, path): path.parent.mkdir(parents=True, exist_ok=True); df.to_csv(path, index=False)
def load_json(path, default):
    try: return json.loads(path.read_text())
    except Exception: return default

def days_left(d):
    if pd.isna(d): return None
    today = pd.to_datetime(date.today())
    return (d - today).days
def status_from_days(n):
    if n is None: return "N/A"
    return "Expired" if n<0 else ("Urgent (≤2d)" if n<=2 else ("Soon (≤7d)" if n<=7 else "OK"))

profiles = load_profiles()
with st.sidebar:
    st.header("👤 Profile")
    active = st.selectbox("Choose profile", profiles["all"], index=profiles["all"].index(profiles.get("active","Home")) if profiles.get("active","Home") in profiles["all"] else 0)
    new_name = st.text_input("Create new profile")
    c1,c2 = st.columns(2)
    if c1.button("Add profile") and new_name:
        if new_name not in profiles["all"]:
            profiles["all"].append(new_name); profiles["active"]=new_name; save_profiles(profiles); st.experimental_rerun()
    if c2.button("Set active"):
        profiles["active"]=active; save_profiles(profiles); st.experimental_rerun()

profile = profiles.get("active","Home")
inv = load_csv(p_path(profile,"inventory.csv"), parse_dates=["purchased_on","expires_on"])
if inv.empty: inv = pd.DataFrame(columns=["id","name","category","subcategory","location","quantity","unit","purchased_on","expires_on","barcode","notes"])
if not inv.empty:
    inv["days_left"] = inv["expires_on"].apply(days_left)
    inv["status"] = inv["days_left"].apply(status_from_days)
recipes = load_csv(p_path(profile,"recipes.csv"))
if recipes.empty:
    recipes = pd.DataFrame(columns=["id","title","ingredients","steps","tags","image","calories_per_serving","protein_g","carbs_g","fat_g","servings","meal_type"])
ratings = load_csv(p_path(profile,"ratings.csv"))
if ratings.empty: ratings = pd.DataFrame(columns=["recipe_id","rating","ts"])
prefs = load_json(p_path(profile,"prefs.json"), {"diet":{},"allergens":{}})
goals = load_json(p_path(profile,"goals.json"), {"daily_calorie_target":2000,"carb_pref":"balanced","adventurous":6,"dislikes":""})
ads = load_csv(p_path(profile,"ads.csv"), parse_dates=["sale_end"])
if ads.empty: ads = pd.DataFrame(columns=["store","product","brand","category","price","unit","sale_end","is_new","tags"])
cooked_log = load_csv(p_path(profile,"cooked_log.csv"))
if cooked_log.empty: cooked_log = pd.DataFrame(columns=["ts","recipe_id","recipe_title","changes_json"])
shop_list = load_csv(p_path(profile,"shopping_list.csv"))
if shop_list.empty: shop_list = pd.DataFrame(columns=["store","product","qty","note"])

have = set(inv[inv["quantity"]>0]["name"].astype(str).str.strip().str.lower().tolist())
soon = set(inv[inv["status"].isin(["Urgent (≤2d)","Soon (≤7d)"])]["name"].astype(str).str.strip().str.lower().tolist())

st.title("🍳 Smart Chef v11")
st.caption("Zero‑waste, goal‑aware dinner picks with fuzzy matching & unit‑aware decrements.")

UNITS = {"g":1,"gram":1,"grams":1,"kg":1000,"oz":28.3495,"ounce":28.3495,"ounces":28.3495,"lb":453.592,"pound":453.592,"pounds":453.592,"ml":1,"l":1000,"cup":240,"cups":240,"tbsp":14.2,"tablespoon":14.2,"tablespoons":14.2,"tsp":4.2,"teaspoon":4.2,"teaspoons":4.2}
def normalize_name(s:str):
    s = re.sub(r"[\(\)\[\]\.,;:]", " ", str(s).lower()); s = re.sub(r"\s+"," ", s).strip()
    if s.endswith("es"): s = s[:-2]
    elif s.endswith("s") and not s.endswith("ss"): s = s[:-1]
    return s
def tokens(s:str): return set(t for t in re.split(r"[^a-z0-9]+", normalize_name(s)) if t)
def token_jaccard(a,b):
    A,B=tokens(a),tokens(b)
    return (len(A & B)/len(A | B)) if A and B else 0.0
def name_similarity(a,b): return max(token_jaccard(a,b), difflib.SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio())

def parse_qty_unit_name(ingredient_line:str):
    line = normalize_name(ingredient_line)
    m = re.match(r"(?:(\d+(?:\.\d+)?)\s+)?(?:(\d+)\s*/\s*(\d+)\s+)?([a-z]+)?\s*(.+)", line)
    qty = 1.0; unit=None; name=line
    if m:
        whole,num,den,unit,rest = m.groups()
        if whole:
            qty=float(whole); name = rest if unit in UNITS or (unit and unit.isalpha()) else line
        if num and den:
            qty += float(num)/float(den); name = rest if unit in UNITS or (unit and unit.isalpha()) else line
        if unit and unit in UNITS: name = rest
        else: unit=None
    name = name.strip()
    return qty, unit, name

def best_inventory_match(inv_df: pd.DataFrame, name: str, threshold=0.52):
    if inv_df.empty: return None
    name_norm = normalize_name(name); best_idx, best_score = None, 0.0
    for idx, inv_name in enumerate(inv_df["name"].astype(str)):
        s = name_similarity(inv_name, name_norm)
        if s > best_score: best_idx, best_score = idx, s
    return (best_idx, best_score) if (best_idx is not None and best_score>=threshold) else None

def decrement_for_ingredient(inv_df, idx, qty, unit, servings_scale, auto_list=False):
    changes=[]; name=str(inv_df.loc[idx,"name"]); current=float(inv_df.loc[idx,"quantity"] or 0); inv_unit=str(inv_df.loc[idx,"unit"] or "").lower().strip()
    delta = qty*servings_scale if (unit and inv_unit and unit==inv_unit) else 1.0*servings_scale
    new=max(0.0, current-delta); inv_df.loc[idx,"quantity"]=new
    changes.append({"name":name,"prev":current,"new":new,"delta":-delta,"unit":inv_unit})
    hit_zero = current>0 and new==0.0
    return inv_df, changes, hit_zero

def allowed_by_prefs(tags_str,prefs):
    tags=[t.strip().lower() for t in str(tags_str or '').split(",")]
    if prefs.get("diet",{}).get("gluten_free") and "gluten-free" not in tags: return False
    if prefs.get("diet",{}).get("vegetarian") and "vegetarian" not in tags and "vegan" not in tags: return False
    if prefs.get("diet",{}).get("vegan") and "vegan" not in tags: return False
    if prefs.get("diet",{}).get("dairy_free") and "dairy-free" not in tags: return False
    for key in ["peanuts","tree-nuts","soy","dairy","eggs","fish","shellfish","sesame","wheat"]:
        toggle=prefs.get("allergens",{}).get(key.replace("-","_"),False)
        if toggle and key in tags: return False
    return True

def macro_targets(daily_cals:int, carb_pref:str, share:float=0.4):
    daily_cals=daily_cals or 2000
    if carb_pref=="lower‑carb": ratios=(0.30,0.30,0.40)
    elif carb_pref=="higher‑carb": ratios=(0.60,0.20,0.20)
    else: ratios=(0.50,0.20,0.30)
    cal=max(100,int(daily_cals*share)); C,P,F=ratios
    return {"cal":cal,"carb_g":cal*C/4,"protein_g":cal*P/4,"fat_g":cal*F/9}

def macro_fit(vals,t):
    s=n=0
    for k,v in [("cal",vals.get("calories_per_serving")),("carb_g",vals.get("carbs_g")),("protein_g",vals.get("protein_g")),("fat_g",vals.get("fat_g"))]:
        tt=t[k]
        if v and tt>0:
            dev=abs(v-tt)/tt; s+=max(0.0,1.0-dev); n+=1
    return s/n if n else 0.0

def estimate_fallback(ingredients_text,servings:int=4):
    MACRO={"chicken breast":(165,31,0,4),"salmon":(208,20,0,13),"tofu":(144,15,3,9),"black beans":(130,9,23,1),"pasta":(157,6,31,1),"rice":(130,2.7,28,0.3),"olive oil":(119,0,0,13.5),"oats":(389,17,66,7)}
    toks=[t.strip().lower() for t in re.split(r"[,\n]", str(ingredients_text)) if t.strip()]
    cal=p=c=f=0.0; used=set()
    for t in toks:
        for k,(kc,kp,kc2,kf) in MACRO.items():
            if k in t and k not in used: cal+=kc; p+=kp; c+=kc2; f+=kf; used.add(k)
    servings=max(1,int(servings or 4))
    return {"calories_per_serving":cal/servings if cal else None,"protein_g":p/servings if p else None,"carbs_g":c/servings if c else None,"fat_g":f/servings if f else None}

def recipe_macros(row):
    vals=row.to_dict()
    if pd.isna(vals.get("calories_per_serving")) or not vals.get("calories_per_serving"):
        vals.update(estimate_fallback(vals.get("ingredients",""), int(vals.get("servings") or 4)))
    return vals

def adventure_bonus(ingredients, adventurous:int):
    if adventurous<=5: return 0.0
    common={"salt","pepper","water","oil","olive oil","sugar","flour","garlic","onion","butter"}
    toks=[t.strip().lower() for t in re.split(r"[,\n]", str(ingredients)) if t.strip()]
    uncommon=[t for t in toks if not any(c in t for c in common)]
    uniq=len(set(uncommon))
    return min(0.3, math.log1p(uniq)/10.0) * ((adventurous-5)/5.0)

def dislike_penalty(ingredients,dislikes_text):
    if not dislikes_text: return 0.0
    dislikes=[d.strip().lower() for d in dislikes_text.split(",") if d.strip()]
    ing_all=str(ingredients).lower()
    return -0.4 if any(d in ing_all for d in dislikes) else 0.0

def expiry_score(ingredients):
    ings=[i.strip().lower() for i in str(ingredients).split(",")]
    return 0.3*sum(1 for i in ings if i in soon) + 0.1*sum(1 for i in ings if i in have)

def sale_hint(ingredients, ads_df):
    if ads_df.empty: return ""
    ings=[w for w in re.split(r"[,\s]", str(ingredients).lower()) if w]
    for _,r in ads_df.iterrows():
        prod=str(r.get("product","")).lower()
        if any(w and w in prod for w in ings):
            price=r.get("price",""); store=r.get("store","")
            return f"{store} deal: {str(price) or 'sale'} on {r.get('product','')}"
    return ""

def rating_adj(recipe_id):
    if ratings.empty: return 0.0
    s=ratings[ratings["recipe_id"]==recipe_id]["rating"].sum()
    return 0.1*s

def compute_tonight_rankings():
    if recipes.empty: return pd.DataFrame()
    daily=int(goals.get("daily_calorie_target") or 2000)
    targets=macro_targets(daily, goals.get("carb_pref","balanced"), share=0.4)
    adv=int(goals.get("adventurous",6)); dislikes=goals.get("dislikes","")
    rows=[]
    for _,r in recipes.iterrows():
        if not allowed_by_prefs(r.get("tags",""),prefs): continue
        vals=recipe_macros(r); mfit=macro_fit(vals,targets); exp=expiry_score(r.get("ingredients",""))
        advb=adventure_bonus(r.get("ingredients",""),adv); disp=dislike_penalty(r.get("ingredients",""),dislikes); adj=rating_adj(r.get("id",-1))
        total=mfit+exp+advb+disp+adj; hint=sale_hint(r.get("ingredients",""), ads)
        rows.append({"id":r["id"],"title":r["title"],"ingredients":r.get("ingredients",""),"tags":r.get("tags",""),
                     "kcal":vals.get("calories_per_serving") or 0,"score":round(max(total,0),4),
                     "why":{"macro":mfit,"expiry":exp,"adventure":advb,"prefs":disp,"learn":adj},
                     "hint":hint})
    df=pd.DataFrame(rows); return df.sort_values("score", ascending=False)

tab_tonight, tab_inventory, tab_log = st.tabs(["Tonight's Picks","Inventory","Cook Log"])

with tab_tonight:
    st.subheader("Tonight's Picks")
    if recipes.empty:
        st.info("Add some recipes first.")
    else:
        servings=st.slider("Servings to cook",1,12,4); auto_list=st.toggle("Auto add to Shopping List when an item hits zero",True)
        view=compute_tonight_rankings().head(6)
        if view.empty: st.warning("No recipes match your current diet filters/preferences.")
        else:
            for _,row in view.iterrows():
                with st.container(border=True):
                    c1,c2=st.columns([5,2])
                    with c1:
                        st.markdown(f"### {row['title']}")
                        st.caption(f"Score: **{row['score']:.2f}** • ~{int(row['kcal'])} kcal/serving • Tags: {row['tags']}")
                        bullets=[]
                        if row["why"]["expiry"]>0: bullets.append("Uses ingredients that are expiring soon")
                        if row["why"]["macro"]>0.6: bullets.append("Strong macro match to tonight's target")
                        if row["why"]["adventure"]>0.05: bullets.append("Adds a touch of flavor adventure")
                        if row["why"]["learn"]>0: bullets.append("Similar to meals you liked")
                        if row["hint"]: bullets.append(row["hint"])
                        if bullets: st.write("• " + "\n• ".join(bullets))
                    with c2:
                        colA,colB=st.columns(2)
                        if colA.button("👍", key=f"up_{row['id']}"):
                            new_row={"recipe_id":row["id"],"rating":1,"ts":datetime.utcnow().isoformat()}
                            r2=pd.concat([ratings,pd.DataFrame([new_row])], ignore_index=True); save_csv(r2, p_path(profile,"ratings.csv")); st.success("Thanks!")
                        if colB.button("👎", key=f"down_{row['id']}"):
                            new_row={"recipe_id":row["id"],"rating":-1,"ts":datetime.utcnow().isoformat()}
                            r2=pd.concat([ratings,pd.DataFrame([new_row])], ignore_index=True); save_csv(r2, p_path(profile,"ratings.csv")); st.info("We’ll show fewer like this.")
                        if st.button("🛒 Missing items", key=f"miss_{row['id']}"]):
                            ing_lines=[i.strip() for i in str(row['ingredients']).split(",") if i.strip()]; missing=[]
                            for line in ing_lines:
                                _,_,name=parse_qty_unit_name(line); m=best_inventory_match(inv,name)
                                if not m: missing.append(name)
                            st.write(", ".join(sorted(set(missing))) if missing else "You have everything!")
                        if st.button("🍴 Cook this", key=f"cook_{row['id']}"]):
                            inv_current=load_csv(p_path(profile,"inventory.csv"), parse_dates=["purchased_on","expires_on"])
                            if inv_current.empty: st.error("Inventory is empty — add items first.")
                            else:
                                ing_lines=[i.strip() for i in str(row['ingredients']).split(",") if i.strip()]
                                all_changes=[]; zeros=[]
                                base_servings=(recipes[recipes['id']==row['id']].iloc[0].get('servings') or 4)
                                scale=servings / max(1,int(base_servings))
                                for line in ing_lines:
                                    qty,unit,name=parse_qty_unit_name(line); m=best_inventory_match(inv_current,name)
                                    if not m: continue
                                    idx,score=m
                                    inv_current,changes,hit_zero=decrement_for_ingredient(inv_current, idx, qty, (unit or "").lower(), scale, auto_list)
                                    all_changes+=changes
                                    if hit_zero: zeros.append(inv_current.loc[idx,"name"])
                                save_csv(inv_current, p_path(profile,"inventory.csv"))
                                entry={"ts":datetime.utcnow().isoformat(),"recipe_id":row["id"],"recipe_title":row["title"],"changes_json":json.dumps(all_changes)}
                                log_df=load_csv(p_path(profile,"cooked_log.csv")); log_df=pd.concat([log_df,pd.DataFrame([entry])], ignore_index=True); save_csv(log_df, p_path(profile,"cooked_log.csv"))
                                if auto_list and zeros:
                                    sl=load_csv(p_path(profile,"shopping_list.csv"))
                                    for item in zeros: sl=pd.concat([sl,pd.DataFrame([{"store":"","product":item,"qty":1,"note":"auto-added (hit zero)"}])], ignore_index=True)
                                    save_csv(sl, p_path(profile,"shopping_list.csv"))
                                if all_changes:
                                    st.success("Cooked! Updated:")
                                    for ch in all_changes: st.write(f"• {ch['name']}: {ch['prev']} → {ch['new']} {(' '+ch['unit']) if ch['unit'] else ''}")
                                    if zeros: st.info("Added to Shopping List: " + ", ".join(zeros))
                                    st.session_state["last_cook_ts"]=entry["ts"]
                                else: st.info("No matches found to decrement.")
                        if st.session_state.get("last_cook_ts"):
                            if st.button("↩️ Undo last cook", key=f"undo_{row['id']}"]):
                                log_df=load_csv(p_path(profile,"cooked_log.csv")); undo_row=log_df[log_df["ts"]==st.session_state["last_cook_ts"]]
                                if undo_row.empty: st.error("Nothing to undo.")
                                else:
                                    changes=json.loads(undo_row.iloc[0]["changes_json"] or "[]")
                                    inv_current=load_csv(p_path(profile,"inventory.csv"), parse_dates=["purchased_on","expires_on"])
                                    name_to_idx={str(n).strip().lower(): idx for idx,n in enumerate(inv_current["name"].astype(str))}
                                    for ch in changes:
                                        nm=str(ch["name"]).strip().lower()
                                        if nm in name_to_idx:
                                            idx=name_to_idx[nm]; inv_current.loc[idx,"quantity"]=float(inv_current.loc[idx,"quantity"] or 0) - ch["delta"]
                                    save_csv(inv_current, p_path(profile,"inventory.csv"))
                                    log_df=log_df[log_df["ts"]!=st.session_state["last_cook_ts"]]; save_csv(log_df, p_path(profile,"cooked_log.csv"))
                                    st.session_state["last_cook_ts"]=None; st.success("Undo complete — pantry restored.")

with tab_inventory:
    st.subheader("Inventory")
    st.dataframe(inv.sort_values("expires_on") if not inv.empty else inv, use_container_width=True)

with tab_log:
    st.subheader("Cook Log")
    log=load_csv(p_path(profile,"cooked_log.csv"))
    st.dataframe(log.sort_values("ts", ascending=False) if not log.empty else log, use_container_width=True)
