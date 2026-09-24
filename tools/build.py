"""สร้าง index.html จาก M5317.mdb (Planfin) + กลุ่มบริการ.xlsx
ใช้งาน:  python tools/build.py M5317.mdb กลุ่มบริการ.xlsx
ต้องมี: pandas, openpyxl (ไม่ต้องติดตั้ง mdbtools / Access)
"""
import sys, os, re, json, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from jet import DB

mdb, xlsx = sys.argv[1], sys.argv[2]
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(__file__), '..', 'index.html')
db = DB(mdb); T = db.tables()
tb = lambda n: pd.DataFrame(list(db.rows(T[n])))
AccCode, AccPlan, PlanCur, PlanTbl, PlanAdmin, DimTime = [tb(n) for n in
    ['AccCode', 'AccPlan', 'plan_current', 'PlanTbl', 'PlanAdmin', 'DimTime']]
DataIn, Hig = tb('DataIn'), tb('hig_est_current')

REV = ['P04','P05','P06','P61','P07','P08','P09','P10','P11','P12','P121','P13']
EXP = ['P14','P15','P151','P16','P17','P18','P19','P20','P21','P22','P23','P24','P241','P25','P251']
G = REV + EXP; GI = {g: i for i, g in enumerate(G)}

# ผังบัญชี -> หมวด Planfin (AccCode ก่อน แล้วเสริมด้วย AccPlan)
amap = AccCode[AccCode.GroupID.isin(G) & (AccCode.UseYN == 'Yes')][['CodeL1','GroupID','Account1']].drop_duplicates('CodeL1')
ap = AccPlan.merge(PlanCur[['plan_id','plan_code']].drop_duplicates('plan_id'), on='plan_id', how='left')
pmap = pd.concat([amap.rename(columns={'CodeL1':'acc','GroupID':'g','Account1':'nm'}),
                  ap[ap.plan_code.isin(G)][['account_code','plan_code','account_title']]
                    .rename(columns={'account_code':'acc','plan_code':'g','account_title':'nm'})]).drop_duplicates('acc')
pm = pmap.set_index('acc')

# รพ. บางแห่งแตกบัญชีย่อยเพิ่มหลักเอง เช่น 5104030205.10101, 5104030205.101.01
# ให้รวมยอดกลับเข้าบัญชีมาตรฐานที่เป็นต้นทาง (บัญชีที่ยาวที่สุดที่เป็น prefix)
KNOWN = sorted(pmap.acc.unique(), key=len, reverse=True)
_pc = {}
def parent(c):
    if c in _pc: return _pc[c]
    r = None
    if c in pm.index: r = c
    else:
        for k in KNOWN:
            if c.startswith(k) and re.fullmatch(r'[.\d]+', c[len(k):]): r = k; break
    _pc[c] = r; return r

# ผลจริงสะสม (ยอดคงเหลืองบทดลอง) รายบัญชี รายเดือน
di = DataIn[DataIn.PDate > DataIn.PDate.min()].copy()
di['AccStd'] = di.AccCode.map(parent)
x = di.merge(pmap, left_on='AccStd', right_on='acc')
x['net'] = x.EndDr.fillna(0) - x.EndCr.fillna(0)
x.loc[x.g.isin(REV), 'net'] *= -1
months = sorted(x.PDate.unique())
act = x.pivot_table(index=['OrgID','acc'], columns='PDate', values='net', aggfunc='sum').reindex(columns=months).fillna(0)
# แผนรายบัญชี (256901 = แผนต้นปี, 256902 = แผนปรับกลางปี)
h = Hig.merge(pmap, left_on='account_code', right_on='acc')
pl = h.pivot_table(index=['hcode','acc'], columns='period_no', values='hig_value', aggfunc='sum').fillna(0)
pl.index.names = ['OrgID','acc']
for c in ['256901','256902']:
    if c not in pl: pl[c] = 0.0
al = act.join(pl, how='outer').fillna(0)
al = al[al.abs().sum(axis=1) > 0.5]
al['g'] = [pm.g[a] for a in al.index.get_level_values(1)]

# ข้อมูลโรงพยาบาล
hx = pd.read_excel(xlsx, header=None, skiprows=3).iloc[:, [2,3,4,5,6,7,8,10]]
hx.columns = ['prov','code','name','type','lvl','bed','pop','grp']
hx = hx.dropna(subset=['code']); hx['code'] = hx.code.astype(str).str.strip().str.zfill(5)

accs = sorted(al.index.get_level_values(1).unique(), key=lambda a: (GI[pm.g[a]], a))
AI = {a: i for i, a in enumerate(accs)}
catsum = al.groupby([al.index.get_level_values(0), 'g']).sum(numeric_only=True)
H = []
for _, r in hx.iterrows():
    c = r.code
    def cs(g, col):
        try: return float(catsum.loc[(c, g), col])
        except KeyError: return 0.0
    rows = []
    if c in al.index.get_level_values(0):
        for a, rr in al.loc[c].iterrows():
            rows.append([AI[a], round(rr['256901']), round(rr['256902'])] + [round(rr[m]) for m in months])
    H.append(dict(code=c, name=str(r['name']).strip(), prov=r.prov, type=r.type, lvl=r.lvl,
        bed=int(r.bed) if pd.notna(r.bed) else None, pop=int(r['pop']) if pd.notna(r['pop']) else None, grp=r.grp,
        a=[[round(cs(g, m)) for m in months] for g in G],
        p1=[round(cs(g, '256901')) for g in G], p2=[round(cs(g, '256902')) for g in G], x=sorted(rows)))

names = PlanTbl.set_index('GroupID').PlanName.to_dict()
assess = PlanAdmin.set_index('GroupID').gpa2.eq('y').to_dict()
dt = DimTime.set_index('pDate')
data = dict(
    months=[dict(fname=f"{dt.loc[m,'fName']} {dt.loc[m,'CYear']}", short=f"{dt.loc[m,'pName']}{str(dt.loc[m,'CYear'])[-2:]}", n=int(dt.loc[m,'NoMonth'])) for m in months],
    cats=[dict(id=g, name=re.sub(r'\s+', ' ', names.get(g, g)).strip(), side='rev' if g in REV else 'exp', assess=bool(assess.get(g, False))) for g in G],
    hosp=H, fy=str(dt.loc[months[-1], 'FYear']), src=os.path.basename(mdb),
    accs=[dict(c=a, n=re.sub(r'\s+', ' ', str(pm.nm[a])).strip(), g=GI[pm.g[a]]) for a in accs])
js = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
tpl = open(os.path.join(os.path.dirname(__file__), 'template.html'), encoding='utf-8').read()
open(out, 'w', encoding='utf-8').write(tpl.replace('__DATA__', js))
print(f'เขียน {out} แล้ว: {len(H)} รพ., {len(months)} เดือน, {len(accs)} บัญชี')
