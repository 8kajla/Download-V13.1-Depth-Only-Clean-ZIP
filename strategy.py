from __future__ import annotations
from dataclasses import dataclass
import json,time
from pathlib import Path
from typing import Dict,Iterable,List,Optional,Tuple

@dataclass
class Signal:
    side:str
    price:float
    score:float
    notional:float
    reason:str

class CapitalFirstStrategy:
    VERSION="V14_40PCT_TRADER_REPLICA"
    DATA_FILE=Path(__file__).with_name("trader_behavior.json")
    BANDS:Tuple[Tuple[str,float,float,str],...]=(("C00_05",0,.05,"CHEAP"),("C05_10",.05,.10,"CHEAP"),("C10_15",.10,.15,"CHEAP"),("C15_20",.15,.20,"CHEAP"),("C20_30",.20,.30,"CHEAP"),("M30_40",.30,.40,"MID"),("M40_50",.40,.50,"MID"),("M50_60",.50,.60,"MID"),("M60_70",.60,.70,"MID"),("R70_80",.70,.80,"CORE"),("R80_90",.80,.90,"CORE"),("H90_95",.90,.95,"HIGH"),("H95_100",.95,1.0,"HIGH"))
    TRAJECTORY_SHARE={"CHEAP":{"rising":.200,"falling":.564,"flat":.236},"MID":{"rising":.410,"falling":.450,"flat":.140},"CORE":{"rising":.542,"falling":.334,"flat":.124},"HIGH":{"rising":.610,"falling":.171,"flat":.219}}
    HARD_CUTOFF=60.0
    def __init__(self,bankroll=1000,start_sec=0,stop_sec=240,hard_cutoff_seconds=60,max_total_exposure=300,min_trade_gap_seconds=0,behavior_file=None,**_):
        self.bankroll=float(bankroll); self.start_sec=max(0,float(start_sec)); self.stop_sec=min(300,float(stop_sec)); self.hard_cutoff_seconds=max(60,float(hard_cutoff_seconds)); self.max_total_exposure=max(0,float(max_total_exposure)); self.min_trade_gap_seconds=max(0,float(min_trade_gap_seconds)); self._last_trade_at=None
        path=Path(behavior_file) if behavior_file else self.DATA_FILE
        with path.open(encoding='utf-8') as f:self.behavior=json.load(f)
        self.notional_scale=float(self.behavior.get('notional_scale',.4))
        self.fine_band_trade_share={x['fine_band']:float(x['trade_share']) for x in self.behavior['fine_bands']}
        self.entry_medians=self.behavior['entry_median_by_fine_band']
    @classmethod
    def fine_band(cls,price):
        p=float(price)
        for band,lo,hi,regime in cls.BANDS:
            if lo<=p<hi:return band,regime
        if p==1:return 'H95_100','HIGH'
        return None,None
    def entry_target(self,price,market='BTC',entry_count=0):
        del market
        band,_=self.fine_band(price)
        if not band:return 0.0
        lookup=self.entry_medians.get(band,{})
        key=str(entry_count+1) if int(entry_count)<20 else '21+'
        value=lookup.get(key)
        if value is None:
            for k in ('1','2','21+'):
                if k in lookup:value=lookup[k];break
        return max(0.10,float(value or 0.0))
    capital_target=entry_target
    @staticmethod
    def _points(history):
        out=[]
        for item in history or []:
            try:
                ts=float(item['ts']) if isinstance(item,dict) else float(item[0]); p=float(item.get('best_bid',item.get('mid'))) if isinstance(item,dict) else float(item[1])
                if 0<p<1:out.append((ts,p))
            except (TypeError,ValueError,KeyError,IndexError):pass
        return sorted(out)
    @classmethod
    def movement(cls,price,history,now):
        pts=cls._points(history); out={}
        for sec in (1,3,5,10,30):
            prev=[p for t,p in pts if t<=float(now)-sec]
            out[f'm{sec}']=float(price)-prev[-1] if prev else 0
        return out
    @staticmethod
    def _trajectory_class(delta):return 'rising' if delta>0 else ('falling' if delta<0 else 'flat')
    def _candidate(self,market,side,bid,ask,depth,history,now,thesis_side,entries,burst_age):
        if bid is None:return None
        try:bid=float(bid); ask=None if ask is None else float(ask); depth=None if depth is None else float(depth)
        except (TypeError,ValueError):return None
        if not 0<bid<1:return None
        band,regime=self.fine_band(bid)
        if not regime:return None
        mv=self.movement(bid,history,now); traj=self._trajectory_class(mv['m5']); tl=self.TRAJECTORY_SHARE[regime][traj]; bp=self.fine_band_trade_share.get(band,0)
        return {'side':side,'bid':bid,'ask':ask,'depth':depth,'band':band,'regime':regime,'trajectory':traj,'trajectory_likelihood':tl,'band_prior':bp,'same_side':bool(thesis_side and side==thesis_side),'target':self.entry_target(bid,market,entries),'movement':mv,'entries':int(entries),'burst_age':float(burst_age)}
    def decide(self,elapsed,up_ask,down_ask,up_bid,down_bid,up_history,down_history,current_exposure,available_cash,up_depth=0,down_depth=0,now=None,asset_exposure=0,total_exposure=0,market_entry_count=0,seconds_since_first_entry=0,thesis_side=None,thesis_price=None,asset=None,market=None):
        del current_exposure,asset_exposure,thesis_price
        now=time.time() if now is None else float(now); elapsed=float(elapsed)
        if elapsed<self.start_sec or elapsed>=self.stop_sec or self.stop_sec-elapsed<=self.hard_cutoff_seconds:return None
        if self._last_trade_at is not None and self.min_trade_gap_seconds and now-self._last_trade_at<self.min_trade_gap_seconds:return None
        m=str(market or asset or 'BTC').upper(); candidates=[c for c in (self._candidate(m,'Up',up_bid,up_ask,up_depth,up_history,now,thesis_side,market_entry_count,seconds_since_first_entry),self._candidate(m,'Down',down_bid,down_ask,down_depth,down_history,now,thesis_side,market_entry_count,seconds_since_first_entry)) if c]
        if not candidates:return None
        same=[c for c in candidates if c['same_side']]; pool=same if thesis_side and same else candidates
        best=max(pool,key=lambda c:(c['band_prior']*c['trajectory_likelihood'],c['band_prior'],c['trajectory_likelihood']))
        target=float(best['target']); remaining=max(0,self.max_total_exposure-float(total_exposure)); notion=min(target,max(0,float(available_cash)),remaining)
        if notion<.10:return None
        self._last_trade_at=now; mv=best['movement']
        reason=(f'{self.VERSION} band={best["band"]} regime={best["regime"]} trajectory={best["trajectory"]} band_prior={best["band_prior"]:.6f} trajectory_likelihood={best["trajectory_likelihood"]:.3f} same_side={best["same_side"]} passive=bid target_40pct=${target:.2f} entry_count={market_entry_count} burst_age={float(seconds_since_first_entry):.1f}s bid={best["bid"]:.4f} ask={best["ask"] if best["ask"] is not None else 0:.4f} depth={best["depth"] if best["depth"] is not None else 0:.2f} m1={mv["m1"]:+.4f} m3={mv["m3"]:+.4f} m5={mv["m5"]:+.4f} m10={mv["m10"]:+.4f} m30={mv["m30"]:+.4f} elapsed={elapsed:.1f}s left={self.stop_sec-elapsed:.1f}s')
        return Signal(best['side'],best['bid'],best['trajectory_likelihood'],round(notion,2),reason)
    def size(self,price,regime=None,market='BTC',entry_count=0,**_):del regime;return self.entry_target(price,market,entry_count)
