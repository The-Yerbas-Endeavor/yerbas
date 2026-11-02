import copy
import unittest
from raw_reward import candidate,verify_decoded,units
class Tests(unittest.TestCase):
 def setUp(self):
  self.scripts={'treasury':'76a914'+'ab'*20+'88ac','provider':'76a914'+'cd'*20+'88ac'}
  self.plan={'outputs':[dict(address='provider',amount_base_units=35388)],'total_base_units':35388}
  self.utxo=dict(coinbase=True,confirmations=11,value='4.20000000',scriptPubKey=dict(addresses=['treasury'],hex=self.scripts['treasury']))
 def build(self,utxo=None,fee=1000):return candidate(self.plan,'a'*64,0,utxo or self.utxo,'treasury',self.scripts,fee)
 def decoded(self,e):return dict(locktime=0,type=0,vin=[dict(**e['inputs'][0],scriptSig={'hex':''})],vout=[dict(value=str(v/100000000),scriptPubKey=dict(addresses=[a],hex=self.scripts[a])) for a,v in e['outputs'].items()])
 def test_exact_arithmetic_and_decode(self):
  e=self.build();self.assertEqual(e['change_base_units'],419963612);self.assertTrue(verify_decoded(self.decoded(e),e))
 def test_maturity_and_wrong_owner(self):
  for bad in [dict(self.utxo,confirmations=10),dict(self.utxo,coinbase=False),dict(self.utxo,scriptPubKey=dict(addresses=['other'],hex=self.scripts['treasury']))]:
   with self.assertRaises(ValueError):self.build(bad)
 def test_fee_and_insufficient_funds(self):
  for fee in (0,-1,10001,True):
   with self.assertRaises(ValueError):self.build(fee=fee)
  with self.assertRaises(ValueError):self.build(dict(self.utxo,value='0.00036'))
 def test_tampered_decode(self):
  e=self.build();original=self.decoded(e)
  for mutation in ('signature','amount','input','script','extra'):
   d=copy.deepcopy(original)
   if mutation=='signature':d['vin'][0]['scriptSig']['hex']='01'
   if mutation=='amount':d['vout'][0]['value']='1'
   if mutation=='input':d['vin'][0]['txid']='b'*64
   if mutation=='script':d['vout'][0]['scriptPubKey']['hex']=self.scripts['treasury']
   if mutation=='extra':d['vout'].append(d['vout'][0])
   with self.assertRaises(ValueError):verify_decoded(d,e)
 def test_dust_and_change_address_conflict(self):
  self.plan['outputs'][0]['amount_base_units']=1
  with self.assertRaises(ValueError):self.build()
  self.plan['outputs'][0]=dict(address='treasury',amount_base_units=35388)
  with self.assertRaises(ValueError):self.build()
 def test_money_rejects_fractional_base_units(self):
  for value in ('0.000000001','NaN','Infinity','-1',True):
   with self.assertRaises(ValueError):units(value)
if __name__=='__main__':unittest.main()
