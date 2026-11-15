import ast,io,time,uuid,unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit,urlunsplit,urlencode,parse_qs
from geco_contract import free_parameters,spin_parameters,parse

class ResumeRequestTests(unittest.TestCase):
    def test_native_drop_settings_are_in_actual_encoded_request(self):
        source=Path(__file__).resolve().parents[2]/'netent-private-root/resume_geco_round.py'
        fn=next(n for n in ast.parse(source.read_text(encoding='utf8')).body if isinstance(n,ast.FunctionDef) and n.name=='request')
        sent=[]
        class Session:
            def get(self,url,**kwargs):
                sent.append(url)
                return SimpleNamespace(status_code=200,text='credit=99980&nextaction=spin')
        env={'base':{'sessid':'fixture'},'uuid':uuid,'time':time,'target':urlsplit('https://showcase.evo-games.com/public/rng/dragon/servlet/CasinoGameServlet'),
             'urlunsplit':urlunsplit,'urlencode':urlencode,'free_parameters':free_parameters,'spin_parameters':spin_parameters,
             'proof':{'free_actions':['dropwin'],'spin_settings_on_actions':['dropwin']},
             'bet':{'level':1,'denomination':1,'lines':'0-0','cost_cents':20},'case':{},'save':lambda:None,
             'session':Session(),'json':__import__('json'),'parse':parse}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),env)
        env['request']('dropwin',io.StringIO())
        params=parse_qs(urlsplit(sent[0]).query)
        self.assertEqual(params['action'],['dropwin'])
        self.assertEqual(params.get('bet.betlevel'),['1'])
        self.assertEqual(params.get('bet.denomination'),['1'])
        self.assertEqual(params.get('bet.betlines'),['0-0'])

        env['proof']['free_actions'].append('bonusaction')
        env['proof']['free_action_parameters']={'bonusaction':{'bonusid':'bonus_game','bonusactiontype':'pickbonus'}}
        env['request']('bonusaction',io.StringIO())
        bonus=parse_qs(urlsplit(sent[-1]).query)
        self.assertEqual(bonus.get('bonusid'),['bonus_game'])
        self.assertEqual(bonus.get('bonusactiontype'),['pickbonus'])
        self.assertNotIn('bet.betlevel',bonus)
