"""사전등록된 산업 모멘텀의 적응형 top1/top2 집중 실험."""
from __future__ import annotations
import argparse, importlib.util, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]; sys.path.insert(0,str(ROOT))
from core import tax_fx as tx, research_power as rp
sp=importlib.util.spec_from_file_location("sector_concentrate",ROOT/"research/jobs/sector-concentrate-v1/run.py")
sc=importlib.util.module_from_spec(sp); sys.modules[sp.name]=sc; sp.loader.exec_module(sc)
ID="sector-adaptive-k-v1"; POLICIES=("top1","top2","adaptive_gap")
INITIAL=30_000_000; FX=1300.; COST=.001

def choose_k(gap, past_gaps):
    """최근 60개 완성 월만 기준으로 사용한다. 부족한 이력은 top2."""
    return 1 if gap is not None and len(past_gaps)>=60 and gap>float(np.median(past_gaps[-60:])) else 2

def schedules(data):
    inds,mkt=data["ind12"],data["mkt"]
    scores=sc.raw_signals(inds,mkt)["RS12"]
    idx=inds.index; ds=sc.decision_rows(idx)
    rank=scores.rank(axis=1,pct=True,method="average")
    gap=[]; rows={n:[] for n in POLICIES}; hist=[]
    for d in ds:
        row=rank.iloc[d-1].to_numpy(); finite=np.flatnonzero(np.isfinite(row))
        order=finite[np.argsort(-row[finite],kind="stable")]
        if len(order)<4:
            picks1=picks2=None; g=None
        else:
            picks1=[int(order[0])]; picks2=[int(order[0]),int(order[1])]
            g=float(row[order[0]]-row[order[1]])
        adaptive=picks1 if choose_k(g,hist)==1 else picks2
        for name,picks in (("top1",picks1),("top2",picks2),("adaptive_gap",adaptive)):
            rows[name].append((int(d),picks))
        threshold=float(np.median(hist[-60:])) if len(hist)>=60 else None
        if g is not None: gap.append({"date":str(idx[d].date()),"gap":g,"threshold":threshold,"picked_k":1 if adaptive is picks1 else 2})
        if g is not None: hist.append(g)
    return rows,gap

def weight_frame(inds,schedule,k_dynamic=False):
    cols=list(inds.columns)+["CASH"]
    w=np.zeros((len(inds),len(cols))); w[:,-1]=1
    for j,(d,picks) in enumerate(schedule):
        e=schedule[j+1][0] if j+1<len(schedule) else len(inds)
        row=np.zeros(len(cols))
        if picks is None: row[-1]=1
        else: row[picks]=1/len(picks)
        w[d:e]=row
    return pd.DataFrame(w,index=inds.index,columns=cols)

def metrics(weights,prices,start,end):
    w=weights.loc[start:end]; px=prices.reindex(w.index).ffill()
    cfg=tx.AccountConfig(initial_krw=INITIAL,fee_rate=COST,fx_spread=0.,apply_dividend_tax=False)
    sim=tx.simulate(w,px,px,pd.Series(FX,index=w.index),cfg)
    v=sim["values_krw"]; years=(v.index[-1]-v.index[0]).days/365.25
    monthly=v.resample("ME").last().dropna(); worst=float(monthly.pct_change(12).dropna().min()) if len(monthly)>12 else None
    return {"after_tax_cagr":float((sim["final_after_liquidation_krw"]/INITIAL)**(1/years)-1),"mdd":sc.max_drawdown(v,INITIAL),"worst_12m":worst,"tax_paid_krw":sim["totals"]["capital_gains_tax_krw"]}

def calc(data):
    ss,gap=schedules(data); inds=data["ind12"].fillna(0.); mkt=data["mkt"].reindex(inds.index).fillna(0.)
    ret=pd.concat([inds,mkt.rename("CASH")],axis=1); prices=(1+ret).cumprod(); out={}; periods=(("select","1927-07-01","1966-12-31"),("confirm","1967-01-01","2007-12-31"),("report_only","2008-01-01",None))
    for n,s in ss.items():
        k=weight_frame(inds,s); out[n]={p:metrics(k,prices,a,b) for p,a,b in periods if pd.Timestamp(a)<=prices.index[-1]}
    # Market baseline has a separately controlled 100% market weight.
    mw=pd.DataFrame(0.,index=inds.index,columns=list(inds.columns)+["CASH"]); mw["CASH"]=1.
    mp=(1+pd.concat([inds,mkt.rename("CASH")],axis=1)).cumprod()
    out["market"]={p:metrics(mw,mp,a,b) for p,a,b in periods if pd.Timestamp(a)<=mp.index[-1]}
    return out,gap

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out",required=True); ap.add_argument("--checkpoint",required=True); ap.add_argument("--smoke",action="store_true"); a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    data=sc.lab.synthetic_data() if a.smoke else sc.lab.load_real()
    rows,gap=calc(data); ss,_=schedules(data); base=rows["market"]; eligible=[]
    for n in POLICIES:
        x=rows[n].get("select"); b=base.get("select")
        if x and b and x["mdd"]>=b["mdd"] and x["worst_12m"] is not None and b["worst_12m"] is not None and x["worst_12m"]>=b["worst_12m"]-.05: eligible.append(n)
    tie={"top2":0,"adaptive_gap":1,"top1":2}
    chosen=sorted(eligible,key=lambda n:(-rows[n]["select"]["after_tax_cagr"],tie[n]))[0] if eligible else None
    sub=[]
    if chosen and "confirm" in rows[chosen]:
        for a0,b0 in (("1967-01-01","1986-12-31"),("1987-01-01","2007-12-31")):
            sub.append(metrics(weight_frame(data["ind12"],ss[chosen]),(1+pd.concat([data["ind12"].fillna(0),data["mkt"].rename("CASH")],axis=1)).cumprod(),a0,b0)["after_tax_cagr"])
    mw=pd.DataFrame(0.,index=data["ind12"].index,columns=list(data["ind12"].columns)+["CASH"]); mw["CASH"]=1.
    mp=(1+pd.concat([data["ind12"].fillna(0),data["mkt"].rename("CASH")],axis=1)).cumprod()
    market_sub=[]
    for a0,b0 in (("1967-01-01","1986-12-31"),("1987-01-01","2007-12-31")):
        market_sub.append(metrics(mw,mp,a0,b0)["after_tax_cagr"])
    confirm=rows.get(chosen,{}).get("confirm"); market=base.get("confirm")
    if a.smoke: verdict="SMOKE_ONLY"
    elif chosen is None or confirm is None: verdict="NOT_EVALUABLE"
    elif rp.noop_guard([confirm["after_tax_cagr"]-market["after_tax_cagr"]]): verdict="NOT_EVALUABLE"
    else:
        passed=(confirm["after_tax_cagr"]>=market["after_tax_cagr"]+.01 and confirm["mdd"]>=market["mdd"] and confirm["worst_12m"] is not None and market["worst_12m"] is not None and confirm["worst_12m"]>=market["worst_12m"]-.05 and len(sub)==2 and all(x>y for x,y in zip(sub,market_sub)))
        verdict="PASS_FORWARD_CANDIDATE" if passed else rp.classify_fail(confirm["after_tax_cagr"]-market["after_tax_cagr"],rp.power_report(39.5,2))
    result={"id":ID,"source":data.get("source"),"smoke":a.smoke,"selected":chosen,"cells":rows,"adaptive_months":gap,"subperiod_cagr":sub,"subperiod_market_cagr":market_sub,"power":rp.power_report(39.5,2),"thresholds":{"selection_mdd_vs_market":0.,"selection_worst12_vs_market":-.05,"confirmation_cagr_vs_market":.01,"confirmation_mdd_vs_market":0.,"confirmation_worst12_vs_market":-.05,"both_subperiods_beat_market":True},"verdicts":{"adaptive_k":verdict},"notes":["1927~2007는 관련 연구에서 이미 사용됐으며 독립 표본외 근거가 아님.","세금은 단순화한 KRW 근사이며 산업 포트폴리오는 직접투자 상품이 아님."]}
    (out/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    lines=[f"# {ID}","",f"판정: {verdict}; 선택 정책: {chosen}",rp.power_line(result["power"]),"","|정책|선택 세후 CAGR|선택 MDD|선택 최악12m|확인 세후 CAGR|확인 MDD|확인 최악12m|","|---|---:|---:|---:|---:|---:|---:|"]
    for n in POLICIES:
        s=rows[n].get("select",{}); c=rows[n].get("confirm",{}); lines.append(f"|{n}|{s.get('after_tax_cagr',float('nan')):.2%}|{s.get('mdd',float('nan')):.2%}|{s.get('worst_12m',float('nan')):.2%}|{c.get('after_tax_cagr',float('nan')):.2%}|{c.get('mdd',float('nan')):.2%}|{c.get('worst_12m',float('nan')):.2%}|")
    lines += ["","적응 정책은 각 날짜의 직전 60개월 격차 중앙값만 기준으로 사용한다. 판정 통과는 전진 원장 후보이며 엔진 변경을 의미하지 않는다."]
    (out/"REPORT.md").write_text("\n".join(lines)+"\n"); return 0
if __name__=="__main__": raise SystemExit(main())
