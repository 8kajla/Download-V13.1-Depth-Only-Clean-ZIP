import tempfile
from pathlib import Path
import pytest
from strategy import CapitalFirstStrategy
from paper_ledger import PaperLedger
from research_logger import ResearchLogger

def S(): return CapitalFirstStrategy(min_trade_gap_seconds=0,hard_cutoff_seconds=60,max_total_exposure=300)
def H(p,now=1000): return [{"ts":now-30,"best_bid":p},{"ts":now-10,"best_bid":p},{"ts":now-5,"best_bid":p},{"ts":now,"best_bid":p}]

def test_all_fine_bands():
    s=S(); expected=[(.02,'C00_05','CHEAP'),(.07,'C05_10','CHEAP'),(.12,'C10_15','CHEAP'),(.17,'C15_20','CHEAP'),(.25,'C20_30','CHEAP'),(.35,'M30_40','MID'),(.45,'M40_50','MID'),(.55,'M50_60','MID'),(.65,'M60_70','MID'),(.75,'R70_80','CORE'),(.85,'R80_90','CORE'),(.925,'H90_95','HIGH'),(.975,'H95_100','HIGH')]
    for p,b,r in expected: assert s.fine_band(p)==(b,r)

def test_40pct_high_sizing():
    s=S(); assert s.entry_target(.96,'BTC',0)==pytest.approx(32.6502*.4, abs=0.01)

def test_high_candidate_not_blocked():
    s=S(); c=s._candidate('BTC','Up',.96,.99,0,H(.96),1000,None,0,0); assert c is not None and c['regime']=='HIGH'

def test_high_signal_uses_scaled_size():
    s=S(); x=s.decide(30,.99,.50,.96,.49,H(.96),H(.49),0,1000,now=1000,total_exposure=0,market_entry_count=0,asset='BTC',market='BTC'); assert x and x.side=='Up' and x.notional==pytest.approx(32.6502*.4, abs=0.01)

def test_total_300_is_only_cap():
    s=S(); x=s.decide(30,.99,.50,.96,.49,H(.96),H(.49),0,1000,now=1000,total_exposure=295,asset='BTC',market='BTC'); assert x and x.notional==pytest.approx(5.0)

def test_no_depth_or_spread_gate():
    s=S(); assert s._candidate('BTC','Up',.96,.99,0,H(.96),1000,None,0,0) is not None

def test_final_minute_cutoff(): assert S().decide(180,.51,.21,.50,.20,H(.50),H(.20),0,1000,now=1000,asset='BTC',market='BTC') is None

def test_side_persistence_prefers_existing_side():
    s=S(); x=s.decide(120,.81,.99,.80,.98,H(.80),H(.98),0,1000,now=1000,market_entry_count=1,seconds_since_first_entry=90,thesis_side='Up',asset='BTC',market='BTC'); assert x and x.side=='Up'

def test_trajectory_gradient():
    s=S(); falling=[{'ts':970,'best_bid':.25},{'ts':995,'best_bid':.24},{'ts':1000,'best_bid':.20}]; rising=[{'ts':970,'best_bid':.75},{'ts':995,'best_bid':.79},{'ts':1000,'best_bid':.80}]; a=s._candidate('BTC','Up',.20,.21,0,falling,1000,None,0,0); b=s._candidate('BTC','Up',.80,.81,0,rising,1000,None,0,0); assert a['trajectory_likelihood']==.564 and b['trajectory_likelihood']==.542

def test_empirical_data_loaded():
    s=S(); assert len(s.fine_band_trade_share)==13 and len(s.entry_medians)==13

def test_cash_constraint():
    s=S(); x=s.decide(30,.99,.50,.96,.49,H(.96),H(.49),0,1.0,now=1000,total_exposure=0,asset='BTC',market='BTC'); assert x and x.notional==pytest.approx(1.0)

def test_resolution_accounting_and_research():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); ledger=PaperLedger(root/'paper_state.json',1000); m={'id':'m1','condition':'c1','slug':'btc-updown-5m-1000000000','asset':'BTC','market':'BTC Up or Down','start_ts':1000000000.0,'end_ts':1000000300.0}; ledger.buy('c1','up-token',m['market'],'Up',.20,1.0,1000000010,meta={'asset':'BTC','slug':m['slug'],'market_id':'m1'}); closed=ledger.settle('c1','up-token'); assert len(closed)==1 and closed[0]['pnl']==4.0; logger=ResearchLogger(root); logger.record_resolution(ts=1000000302,market=m,winner='Up',winner_token='up-token',closed=closed); assert 'RESOLVED' in (root/'resolutions.csv').read_text()
